"""Metrics, structured logs and request ids.

What an operator needs to know about a compliance assistant is different from a normal web
service: not only "is it up and fast" but "is it still *trustworthy*" - how often it abstains,
how often citations fail verification, whether the LLM is failing over to source-text-only
answers, whether someone is guessing passwords, and whether the audit chain is intact.
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
import time
import uuid
from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

# --- trust and quality ------------------------------------------------------------------
CHAT = Counter("copilot_chat_total", "Chat answers by final status", ["status"])
CHAT_LATENCY = Histogram(
    "copilot_chat_latency_seconds", "Time to the final verified answer",
    buckets=(0.5, 1, 2, 4, 8, 15, 30, 60, 120),
)
CITATIONS = Counter("copilot_citations_total", "Citations returned by the model")
CITATIONS_VERIFIED = Counter("copilot_citations_verified_total", "Citations found verbatim in the source text")
LLM_ERRORS = Counter("copilot_llm_errors_total", "LLM failures that degraded an answer", ["kind"])
STREAM_RESETS = Counter("copilot_stream_resets_total", "Streams restarted after the provider dropped them")
INTERRUPTED = Counter("copilot_chat_interrupted_total", "Streams abandoned by the reader after a draft was delivered")

# --- security ---------------------------------------------------------------------------
RATE_LIMITED = Counter("copilot_rate_limited_total", "Requests refused by a rate limit", ["scope"])
LOGIN_FAILURES = Counter("copilot_login_failures_total", "Failed password logins", ["reason"])

# --- integrity --------------------------------------------------------------------------
AUDIT_VALID = Gauge("copilot_audit_chain_valid", "1 if the last audit-chain verification passed, 0 if it failed")
AUDIT_CHECKED_AT = Gauge("copilot_audit_chain_checked_timestamp_seconds", "When the audit chain was last verified")
AUDIT_ROWS = Gauge("copilot_audit_chain_rows", "Rows covered by the last audit-chain verification")

# --- http -------------------------------------------------------------------------------
HTTP = Counter("copilot_http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_LATENCY = Histogram(
    "copilot_http_request_duration_seconds", "HTTP request duration (streams: until the first byte)",
    ["route"], buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)


def record_chat(resp: Any, latency_s: float) -> None:
    """Called once per finished answer (blocking and streaming alike)."""
    CHAT.labels(resp.status).inc()
    CHAT_LATENCY.observe(latency_s)
    g = resp.grounding or {}
    CITATIONS.inc(g.get("citations", 0))
    CITATIONS_VERIFIED.inc(g.get("verified", 0))
    if err := (resp.trace or {}).get("llm_error"):
        LLM_ERRORS.labels("quota" if "quota" in err else "error").inc()


def render() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST


# --- logging ----------------------------------------------------------------------------


class JsonFormatter(logging.Formatter):
    """One JSON object per line, ready for a log shipper. Never logs request bodies."""

    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "level": record.levelname, "logger": record.name, "msg": record.getMessage(),
            "request_id": request_id.get(),
        }
        out.update(getattr(record, "fields", {}))
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False, default=str)


def configure_logging(fmt: str = "text", level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())


def new_request_id(incoming: str | None) -> str:
    # accept a proxy-supplied id only if it is short and plain, so it cannot be used to forge log lines
    if incoming and len(incoming) <= 64 and incoming.replace("-", "").isalnum():
        return incoming
    return uuid.uuid4().hex
