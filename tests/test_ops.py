"""Operations: readiness, metrics, request ids, structured logs, audit watchdog."""

import json
import logging

import pytest
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from compliance_copilot import audit, observability
from compliance_copilot.api import main as api
from compliance_copilot.config import get_settings


def sample(name: str, **labels) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


@pytest.fixture
def client(corpus):
    from compliance_copilot.security import seed_users

    seed_users()
    with TestClient(api.app) as c:
        yield c


def test_readiness_waits_for_the_models(client, monkeypatch):
    monkeypatch.setattr(api, "_models_ready", type(api._models_ready)())  # not ready yet
    r = client.get("/ready")
    assert r.status_code == 503 and r.json()["detail"]["models_ready"] is False
    api._models_ready.set()
    assert client.get("/ready").status_code == 200


def test_metrics_are_off_without_a_token_and_protected_with_one(client, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "metrics_token", None)
    assert client.get("/metrics").status_code == 404
    monkeypatch.setattr(s, "metrics_token", "scrape-secret")
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401
    r = client.get("/metrics", headers={"Authorization": "Bearer scrape-secret"})
    assert r.status_code == 200 and "copilot_chat_total" in r.text and "copilot_audit_chain_valid" in r.text


def test_answers_and_failures_are_counted(client, fake_llm):
    before = sample("copilot_chat_total", status="answered")
    fail = sample("copilot_login_failures_total", reason="wrong_password")
    tok = client.post("/auth/login", json={"username": "somchai", "password": "demo-employee"}).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    cits = sample("copilot_citations_verified_total")
    r = client.post("/chat", headers=h, json={"question": "ต้องเก็บข้อมูล CDD กี่ปีหลังปิดบัญชี"})
    assert r.status_code == 200 and r.json()["status"] == "answered"
    assert sample("copilot_chat_total", status="answered") == before + 1
    assert sample("copilot_citations_verified_total") > cits
    client.post("/auth/login", json={"username": "somchai", "password": "nope"})
    assert sample("copilot_login_failures_total", reason="wrong_password") == fail + 1
    if conv := r.json().get("conversation_id"):
        client.post(f"/conversations/{conv}/delete", headers=h)


def test_request_ids_are_echoed_and_cannot_forge_log_lines(client):
    assert client.get("/health", headers={"X-Request-ID": "abc-123"}).headers["x-request-id"] == "abc-123"
    evil = client.get("/health", headers={"X-Request-ID": "x y\"},{\"level\":\"CRITICAL"}).headers["x-request-id"]
    assert evil != 'x y"},{"level":"CRITICAL' and len(evil) == 32  # replaced by a generated id
    assert client.get("/health").headers["x-request-id"]


def test_json_logs_are_one_parsable_object_per_line_with_the_request_id():
    rec = logging.LogRecord("access", logging.INFO, __file__, 1, "GET /documents 200", None, None)
    rec.fields = {"status": 200, "ms": 12}
    tok = observability.request_id.set("rid-1")
    try:
        out = json.loads(observability.JsonFormatter().format(rec))
    finally:
        observability.request_id.reset(tok)
    assert out["msg"] == "GET /documents 200" and out["request_id"] == "rid-1" and out["status"] == 200


def test_audit_watchdog_publishes_the_chain_state(corpus, monkeypatch):
    api._verify_audit_once()
    assert sample("copilot_audit_chain_valid") == 1 and sample("copilot_audit_chain_rows") > 0
    monkeypatch.setattr(audit, "verify_chain", lambda: {"valid": False, "checked": 3, "broken_at_id": 4})
    api._verify_audit_once()
    assert sample("copilot_audit_chain_valid") == 0  # this is what the alert fires on
