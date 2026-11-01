"""Acceptable-use terms and problem reports: the controls that make 'decision support, not legal
advice' and 'report wrong answers' part of how the system is used, not just words in a document."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from compliance_copilot import terms
from compliance_copilot.config import get_settings
from compliance_copilot.db import engine

Q = {"question": "ต้องเก็บข้อมูล CDD กี่ปีหลังปิดบัญชี"}


@pytest.fixture
def client(corpus, fake_llm):
    from compliance_copilot.api.main import app
    from compliance_copilot.security import seed_users

    seed_users()
    with engine().begin() as c:  # a clean slate for the terms of the users these tests use
        c.execute(text("UPDATE users SET terms_version = NULL, terms_accepted_at = NULL WHERE username IN ('somchai', 'nida')"))
    with TestClient(app) as cl:
        yield cl


def _auth(client, user="somchai", pw="demo-employee"):
    tok = client.post("/auth/login", json={"username": user, "password": pw}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def _cleanup(client, resp, headers, report_ids=()):
    """Tests share the dev database: remove the chats and problem reports they create."""
    if conv := resp.get("conversation_id"):
        client.post(f"/conversations/{conv}/delete", headers=headers)
    for rid in report_ids:
        with engine().begin() as c:
            c.execute(text("DELETE FROM feedback WHERE id = :i"), {"i": rid})


def test_terms_text_is_versioned_and_complete():
    version, body = terms.load()
    assert version and "ไม่ใช่ความเห็นทางกฎหมาย" in body and "รายงานปัญหา" in body and len(body) > 500


def test_questions_are_refused_until_the_current_terms_are_accepted(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "terms_required", True)
    h = _auth(client)
    me = client.get("/me", headers=h).json()
    assert me["terms_required"] and not me["terms_accepted"]
    assert client.post("/chat", headers=h, json=Q).status_code == 403
    assert client.post("/chat/stream", headers=h, json=Q).status_code == 403
    t = client.get("/terms", headers=h).json()
    assert t["version"] == terms.current_version() and not t["accepted"] and t["text"]

    stale = client.post("/me/accept-terms", headers=h, json={"version": "1999-01-01"})
    assert stale.status_code == 409  # the text changed since it was displayed
    ok = client.post("/me/accept-terms", headers=h, json={"version": t["version"]})
    assert ok.status_code == 200 and ok.json()["terms_accepted"]

    r = client.post("/chat", headers=h, json=Q)
    assert r.status_code == 200
    # acceptance survives a new session and is audited with the version
    assert client.get("/me", headers=_auth(client)).json()["terms_accepted"]
    audit = client.get("/audit?event=terms_accepted", headers=_auth(client, "nida", "demo-compliance")).json()
    assert any(e["payload"]["version"] == t["version"] and e["username"] == "somchai" for e in audit)
    _cleanup(client, r.json(), h)


def test_a_new_terms_version_makes_everyone_accept_again(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "terms_required", True)
    h = _auth(client)
    client.post("/me/accept-terms", headers=h, json={"version": terms.current_version()})
    assert client.get("/me", headers=_auth(client)).json()["terms_accepted"]
    monkeypatch.setattr(terms, "current_version", lambda: "2099-01-01")
    assert not client.get("/me", headers=_auth(client)).json()["terms_accepted"]


def test_terms_are_not_enforced_when_not_required(client):
    h = _auth(client)
    assert client.get("/me", headers=h).json()["terms_required"] is False
    r = client.post("/chat", headers=h, json=Q)
    assert r.status_code == 200
    _cleanup(client, r.json(), h)


def test_problem_report_lifecycle(client):
    emp, officer = _auth(client), _auth(client, "nida", "demo-compliance")
    r = client.post("/chat", headers=emp, json=Q).json()
    rep = client.post("/feedback", headers=emp, json={"audit_id": r["audit_id"], "rating": -1,
                                                     "category": "outdated", "comment": "ใช้ฉบับเก่า"}).json()
    rid = rep["report_id"]
    assert rid

    mine = client.get("/feedback/mine", headers=emp).json()
    assert any(m["id"] == rid and m["report_status"] == "open" and m["category"] == "outdated" for m in mine)
    assert client.get("/feedback/reports", headers=emp).status_code == 403  # staff cannot read others' reports

    reports = client.get("/feedback/reports?status=open", headers=officer).json()
    assert any(x["id"] == rid and x["comment"] == "ใช้ฉบับเก่า" for x in reports)
    assert client.post(f"/feedback/{rid}/resolve", headers=emp, json={"note": "x y z"}).status_code == 403
    assert client.post(f"/feedback/{rid}/resolve", headers=officer, json={"note": "x"}).status_code == 422

    done = client.post(f"/feedback/{rid}/resolve", headers=officer, json={"note": "เพิ่มฉบับใหม่ในคลังแล้ว"}).json()
    assert done["status"] == "resolved"
    view = next(m for m in client.get("/feedback/mine", headers=emp).json() if m["id"] == rid)
    assert view["report_status"] == "resolved" and view["resolution"] == "เพิ่มฉบับใหม่ในคลังแล้ว"
    assert not any(x["id"] == rid for x in client.get("/feedback/reports?status=open", headers=officer).json())
    events = client.get("/audit?event=report_resolved", headers=officer).json()
    assert any(e["payload"]["id"] == rid for e in events)
    _cleanup(client, r, emp, [rid])


def test_a_report_of_confidential_material_is_raised_as_an_incident(client):
    emp, officer = _auth(client), _auth(client, "nida", "demo-compliance")
    r = client.post("/chat", headers=emp, json=Q).json()
    rid = client.post("/feedback", headers=emp, json={"audit_id": r["audit_id"], "rating": -1,
                                                     "category": "leak"}).json()["report_id"]
    inc = client.get("/audit?event=incident_reported", headers=officer).json()
    assert any(e["payload"]["feedback_id"] == rid and e["username"] == "somchai" for e in inc)
    up = client.post("/feedback", headers=emp, json={"audit_id": r["audit_id"], "rating": 1}).json()
    assert up["report_id"] is None  # a thumbs-up is not a problem report
    with engine().begin() as c:
        c.execute(text("DELETE FROM feedback WHERE audit_id = :a"), {"a": r["audit_id"]})  # the thumbs-up row too
    _cleanup(client, r, emp, [rid])


def test_resolution_needs_a_note_and_a_valid_status():
    from compliance_copilot import feedback

    with pytest.raises(ValueError, match="note"):
        feedback.resolve(1, "x", "  ")
    with pytest.raises(ValueError, match="status"):
        feedback.resolve(1, "x", "ok", "bogus")


def test_evidence_pack_reports_the_deployment_honestly(corpus, monkeypatch):
    from compliance_copilot import evidence
    from compliance_copilot.security import seed_users

    seed_users()
    s = get_settings()
    monkeypatch.setattr(s, "env", "development")
    monkeypatch.setattr(s, "terms_required", False)
    card = evidence.build()
    for heading in ("## 1. Components and versions", "## 2. Knowledge base", "## 3. Evaluation evidence",
                    "## 4. Controls checked", "## 5. Findings to resolve", "## 6. Not verified"):
        assert heading in card
    assert s.embedding_model in card and "answer-v" in card and "pol-aml-001" in card
    assert "synthetic sample" in card  # the sample policies are labelled in the corpus table
    assert "of 146" in card or "of 51" in card  # expert-confirmed coverage is stated per set
    findings = card.split("## 5. Findings to resolve")[1].split("## 6.")[0]
    assert "acceptable-use terms" in findings and "not enforced" in findings
    assert "demo password" in findings  # the seeded demo accounts are called out

    monkeypatch.setattr(s, "terms_required", True)
    assert "acceptable-use terms" not in evidence.build().split("## 5. Findings to resolve")[1].split("## 6.")[0]


def test_published_demo_passwords_are_detected_and_cleared_when_changed(corpus):
    from compliance_copilot import security

    security.seed_users()
    assert "somchai" in security.demo_accounts_with_published_passwords()
    security.create_user("zz-evidence-user", "t", "employee", "retail", "internal", "a-long-unique-password-1")
    try:
        assert "zz-evidence-user" not in security.demo_accounts_with_published_passwords()
    finally:
        with engine().begin() as c:
            c.execute(text("DELETE FROM users WHERE username = 'zz-evidence-user'"))
