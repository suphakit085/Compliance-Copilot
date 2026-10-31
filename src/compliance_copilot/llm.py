"""Provider-agnostic LLM access.

The app needs two capabilities from a model, and nothing provider-specific:

* ``generate_json`` - output validated against a Pydantic schema (grounded answers,
  query rewriting, gap analysis, eval judging);
* ``generate_text`` with optional images - OCR of scanned PDF pages.

Grounding does **not** rely on any provider feature: answers carry verbatim quotes
that our own code verifies against the retrieved source text (see
``generation/citations.py``). Swapping Gemini for Claude or an on-prem model is a
configuration change.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel

from .config import get_settings

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


class QuotaExceeded(LLMError):
    """Daily/plan quota exhausted - retrying will not help until the quota resets."""


@dataclass
class Usage:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0


class LLMProvider(Protocol):
    name: str
    model: str

    def generate_json(
        self, system: str, prompt: str, schema: type[T], images: list[bytes] | None = None,
        effort: str | None = None,
    ) -> tuple[T, Usage]: ...

    def generate_text(
        self, system: str, prompt: str, images: list[bytes] | None = None, effort: str | None = None
    ) -> tuple[str, Usage]: ...


# --------------------------------------------------------------------------- Gemini


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str, max_output_tokens: int):
        from google import genai
        from google.genai import types

        self._genai = genai
        # Retries are handled below so that quota exhaustion fails fast instead of retrying.
        self.client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=180_000, retry_options=types.HttpRetryOptions(attempts=1)),
        )
        self.model = model
        self.max_output_tokens = max_output_tokens

    def _call(self, system: str, prompt: str, images: list[bytes] | None, effort: str | None = None,
              **config):
        from google.genai import errors, types

        if effort:  # minimal | low | medium | high -> Gemini thinking level
            config["thinking_config"] = types.ThinkingConfig(thinking_level=effort.upper())
        parts: list = [types.Part.from_bytes(data=img, mime_type="image/png") for img in images or []]
        parts.append(prompt)
        cfg = types.GenerateContentConfig(
            system_instruction=system, max_output_tokens=self.max_output_tokens, **config
        )
        delay = 2.0
        for attempt in range(5):
            started = time.perf_counter()
            try:
                resp = self.client.models.generate_content(model=self.model, contents=parts, config=cfg)
            except errors.APIError as e:
                msg = str(e.message or e)
                if e.code == 429 and ("per day" in msg.lower() or "PerDay" in str(e.details)):
                    raise QuotaExceeded(f"Gemini daily quota exhausted for {self.model}: {msg[:300]}") from e
                retryable = e.code in (429, 500, 502, 503, 504)
                if retryable and attempt < 4:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise LLMError(f"Gemini API error {e.code}: {e.message}") from e
            meta = resp.usage_metadata
            usage = Usage(
                model=resp.model_version or self.model,
                input_tokens=(meta.prompt_token_count or 0) if meta else 0,
                output_tokens=((meta.candidates_token_count or 0) + (meta.thoughts_token_count or 0))
                if meta
                else 0,
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
            if resp.prompt_feedback and resp.prompt_feedback.block_reason:
                raise LLMError(f"Gemini blocked the prompt: {resp.prompt_feedback.block_reason}")
            return resp, usage
        raise LLMError("Gemini API: retries exhausted")

    def generate_json(self, system, prompt, schema, images=None, effort=None):
        resp, usage = self._call(
            system, prompt, images, effort,
            response_mime_type="application/json", response_schema=schema,
        )
        text = resp.text or ""
        try:
            return schema.model_validate_json(text), usage
        except ValueError as e:
            raise LLMError(f"Model returned invalid JSON for {schema.__name__}: {e}") from e

    def generate_text(self, system, prompt, images=None, effort=None):
        resp, usage = self._call(system, prompt, images, effort)
        return (resp.text or "").strip(), usage


# ------------------------------------------------------------------------ Anthropic


class AnthropicProvider:
    """Claude via the official SDK (alternative provider; selected with COPILOT_LLM_PROVIDER)."""

    name = "anthropic"

    def __init__(self, api_key: str, model: str, max_output_tokens: int):
        import anthropic

        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=api_key, max_retries=3, timeout=180.0)
        self.model = model
        self.max_output_tokens = max_output_tokens

    def _call(self, system: str, prompt: str, images: list[bytes] | None, effort: str | None = None,
              **extra):
        import base64

        output_config = extra.pop("output_config", {})
        if effort:
            output_config["effort"] = "low" if effort == "minimal" else effort
        if output_config:
            extra["output_config"] = output_config

        content: list[dict] = [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png",
                           "data": base64.standard_b64encode(img).decode()},
            }
            for img in images or []
        ]
        content.append({"type": "text", "text": prompt})
        started = time.perf_counter()
        try:
            resp = self.client.beta.messages.create(
                model=self.model,
                max_tokens=self.max_output_tokens,
                system=system,
                messages=[{"role": "user", "content": content}],
                betas=["server-side-fallback-2026-07-01"],
                extra_body={"fallbacks": "default"},
                **extra,
            )
        except self._anthropic.APIStatusError as e:
            raise LLMError(f"Claude API error {e.status_code}: {e.message}") from e
        except self._anthropic.APIConnectionError as e:
            raise LLMError(f"Cannot reach Claude API: {e}") from e
        if resp.stop_reason == "refusal":
            raise LLMError("The model declined this request.")
        text = "".join(b.text for b in resp.content if b.type == "text")
        usage = Usage(resp.model, resp.usage.input_tokens, resp.usage.output_tokens,
                      int((time.perf_counter() - started) * 1000))
        return text, usage

    def generate_json(self, system, prompt, schema, images=None, effort=None):
        text, usage = self._call(
            system, prompt, images, effort,
            output_config={"format": {"type": "json_schema", "schema": _strict_schema(schema)}},
        )
        try:
            return schema.model_validate_json(text), usage
        except ValueError as e:
            raise LLMError(f"Model returned invalid JSON for {schema.__name__}: {e}") from e

    def generate_text(self, system, prompt, images=None, effort=None):
        return self._call(system, prompt, images, effort)


def _strict_schema(schema: type[BaseModel]) -> dict:
    js = schema.model_json_schema()

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object" or "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node.get("properties", {}).keys())
            node.pop("default", None)
            node.pop("title", None)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(js)
    return js


# ----------------------------------------------------------------------------- cache


class CachedProvider:
    """Disk cache for deterministic batch work (eval runs, gap analysis re-runs).

    Keyed by provider, model, effort, schema and the full prompt, so any change to the
    prompt or retrieved context is a cache miss. Never used for live chat.
    """

    def __init__(self, inner: LLMProvider, directory):
        self.inner, self.name, self.model = inner, inner.name, inner.model
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _key(*parts: str) -> str:
        import hashlib

        return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()

    def generate_json(self, system, prompt, schema, images=None, effort=None):
        import json

        if images:
            return self.inner.generate_json(system, prompt, schema, images, effort)
        f = self.dir / f"{self._key(self.name, self.model, str(effort), schema.__name__, system, prompt)}.json"
        if f.exists():
            data = json.loads(f.read_text(encoding="utf-8"))
            return schema.model_validate(data["output"]), Usage(model=data["model"] + " (cached)")
        out, usage = self.inner.generate_json(system, prompt, schema, images, effort)
        f.write_text(json.dumps({"model": usage.model, "output": out.model_dump()}, ensure_ascii=False),
                     encoding="utf-8")
        return out, usage

    def generate_text(self, system, prompt, images=None, effort=None):
        return self.inner.generate_text(system, prompt, images, effort)


# --------------------------------------------------------------------------- factory

_providers: dict[str, LLMProvider] = {}


def available() -> bool:
    s = get_settings()
    return bool(s.gemini_api_key if s.llm_provider == "gemini" else s.anthropic_api_key)


def get_provider(purpose: str = "chat") -> LLMProvider:
    """``chat`` serves live users; ``batch`` (gap analysis, eval) may use a different model
    with its own quota and is disk-cached."""
    if purpose in _providers:
        return _providers[purpose]
    s = get_settings()
    if s.llm_provider == "gemini":
        if not s.gemini_api_key:
            raise LLMError("COPILOT_GEMINI_API_KEY is not set - LLM features are disabled.")
        model = s.gemini_batch_model if purpose == "batch" and s.gemini_batch_model else s.gemini_model
        provider: LLMProvider = GeminiProvider(s.gemini_api_key, model, s.llm_max_tokens)
    elif s.llm_provider == "anthropic":
        if not s.anthropic_api_key:
            raise LLMError("COPILOT_ANTHROPIC_API_KEY is not set - LLM features are disabled.")
        provider = AnthropicProvider(s.anthropic_api_key, s.anthropic_model, s.llm_max_tokens)
    else:
        raise LLMError(f"Unknown LLM provider: {s.llm_provider}")
    if purpose == "batch" and s.llm_cache:
        provider = CachedProvider(provider, s.processed_dir / "llm_cache")
    _providers[purpose] = provider
    return provider


def set_provider(provider: LLMProvider | None, purpose: str | None = None) -> None:
    """Inject a provider (tests use a scripted fake). ``purpose=None`` sets every purpose."""
    for p in [purpose] if purpose else ["chat", "batch"]:
        if provider is None:
            _providers.pop(p, None)
        else:
            _providers[p] = provider


OCR_PROMPT = (
    "Transcribe all text on this scanned page of a Thai regulatory document exactly as "
    "written, preserving line breaks and numbering (e.g. 'ข้อ 5', '5.1', '(1)'). Keep Thai "
    "digits as they appear. Do not summarize, translate, correct or add anything. Render "
    "tables as plain text rows separated by ' | '. Mark illegible text as [อ่านไม่ออก]. "
    "Output only the transcription."
)


def ocr_image(png: bytes) -> tuple[str, Usage]:
    return get_provider().generate_text("You are a meticulous OCR engine.", OCR_PROMPT, [png], effort="low")
