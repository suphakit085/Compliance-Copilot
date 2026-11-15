"""Whole-document summaries: every shown point is tied to a verified quote, the summary follows
the document's access rules and version, and chat points to it instead of pretending that six
retrieved units are the whole document."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from compliance_copilot.db import engine
from compliance_copilot.features import doc_summary as ds
from compliance_copilot.retrieval.retriever import UserContext

DOC = "pdpc-breach-2565"  # public regulation, 18 units
EMPLOYEE = UserContext(id=None, username="t", role="employee", department="retail", clearance=1)

UNITS = [
    {"id": "U1", "chunk_id": "d#1", "label": "ข้อ 1", "path": [], "notes": [],
     "text": "ผู้ควบคุมข้อมูลต้องแจ้งเหตุภายในเจ็ดสิบสองชั่วโมงนับแต่ทราบเหตุ"},
    {"id": "U2", "chunk_id": "d#2", "label": "ข้อ 2", "path": [], "notes": [],
     "text": "ผู้ใดฝ่าฝืนต้องระวางโทษปรับทางปกครองไม่เกินห้าล้านบาท"},
]


def _pt(section, body, unit, quote):
    return ds.PointOut(section=section, text=body, citations=[ds.UnitQuote(unit_id=unit, quote=quote)])


def test_only_points_with_a_quote_found_in_the_named_unit_survive():
    points = [
        _pt("penalties", "โทษปรับไม่เกิน 5 ล้านบาท", "U2", "ต้องระวางโทษปรับทางปกครองไม่เกินห้าล้านบาท"),
        _pt("deadlines", "แจ้งภายใน 72 ชั่วโมง", "[u1]", "แจ้งเหตุภายในเจ็ดสิบสองชั่วโมง"),
        _pt("deadlines", "quote from the wrong unit", "U1", "ต้องระวางโทษปรับทางปกครองไม่เกินห้าล้านบาท"),
        _pt("obligations", "unit that does not exist", "U9", "แจ้งเหตุภายในเจ็ดสิบสองชั่วโมง"),
        _pt("obligations", "invented quote", "U1", "ต้องจัดอบรมพนักงานทุกปีโดยไม่มีข้อยกเว้น"),
    ]
    kept, dropped = ds.verify_points(points, UNITS)
    assert [p["text"] for p in kept] == ["แจ้งภายใน 72 ชั่วโมง", "โทษปรับไม่เกิน 5 ล้านบาท"]  # section order
    assert kept[0]["citations"][0]["chunk_id"] == "d#1" and kept[0]["citations"][0]["label"] == "ข้อ 1"
    assert dropped == {"dropped_points": 3, "dropped_citations": 3}


def test_long_documents_are_read_in_consecutive_parts_without_losing_a_unit():
    units = [{"id": f"U{i}", "text": "ก" * 1000} for i in range(1, 60)]
    parts = ds.split_parts(units, max_chars=24_000)
    assert len(parts) == 3 and [u for p in parts for u in p] == units
    assert all(sum(len(u["text"]) for u in p) <= 24_000 for p in parts)
    assert ds.split_parts([{"id": "U1", "text": "ข" * 50_000}], 24_000) == [[{"id": "U1", "text": "ข" * 50_000}]]


def test_fingerprint_changes_with_any_unit_text():
    changed = [UNITS[0], {**UNITS[1], "text": UNITS[1]["text"].replace("ห้า", "สาม")}]
    assert ds.fingerprint(UNITS) == ds.fingerprint([dict(u) for u in UNITS])
    assert ds.fingerprint(UNITS) != ds.fingerprint(changed)


def test_summary_markdown_lists_points_with_their_quotes():
    s = {"title": "ตัวอย่าง", "model": "m", "prompt_version": "summary-v1", "stale": True, "reviewed_by": None,
         "stats": {"units": 2, "points": 1, "units_cited": 1},
         "points": [{"section": "deadlines", "text": "แจ้งภายใน 72 ชั่วโมง",
                     "citations": [{"label": "ข้อ 1", "quote": "แจ้งเหตุภายในเจ็ดสิบสองชั่วโมง"}]}]}
    md = ds.to_markdown(s)
    assert "## กรอบเวลาและตัวเลขสำคัญ" in md and "(ข้อ 1)" in md and "เจ็ดสิบสอง" in md
    assert "ต้องสร้างสรุปใหม่" in md and "ยังไม่ผ่านการรับรอง" in md


# --------------------------------------------------------------------------- with the corpus


@pytest.fixture
def client(corpus, fake_llm):
    from compliance_copilot.api.main import app
    from compliance_copilot.security import seed_users

    seed_users()
    with TestClient(app) as cl:
        yield cl
    with engine().begin() as c:  # tests share the dev database
        c.execute(text("DELETE FROM document_summaries WHERE model = 'fake-llm'"))


def _auth(client, user="somchai", pw="demo-employee"):
    tok = client.post("/auth/login", json={"username": user, "password": pw}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture
def no_summary():
    """Hide real summaries of the test document for the duration of a test."""
    with engine().begin() as c:
        saved = c.execute(text("SELECT id FROM document_summaries WHERE document_id = :d"), {"d": DOC}).scalars().all()
        c.execute(text("UPDATE document_summaries SET document_id = 'pol-gift-2566' WHERE id = ANY(:i)"), {"i": saved})
    yield
    with engine().begin() as c:
        c.execute(text("UPDATE document_summaries SET document_id = :d WHERE id = ANY(:i)"), {"d": DOC, "i": saved})


def test_summary_lifecycle_create_share_regenerate_review(client, fake_llm, no_summary):
    emp, officer = _auth(client), _auth(client, "nida", "demo-compliance")
    assert client.get(f"/documents/{DOC}/summary", headers=emp).json() == {"summary": None}

    s = client.post(f"/documents/{DOC}/summary", headers=emp, json={}).json()["summary"]
    assert s["stats"]["units"] == 18 and s["stats"]["dropped_points"] >= 1  # the invented point is gone
    assert s["points"] and all(p["text"] != "ประเด็นที่ไม่มีในต้นฉบับ" for p in s["points"])
    assert not s["stale"] and s["reviewed_by"] is None and s["created_by"] == "somchai"

    calls = fake_llm.calls
    again = client.post(f"/documents/{DOC}/summary", headers=_auth(client, "nida", "demo-compliance"), json={})
    assert again.json()["summary"]["id"] == s["id"] and fake_llm.calls == calls  # shared, not re-paid

    assert client.post(f"/documents/{DOC}/summary", headers=emp, json={"force": True}).status_code == 403
    assert client.post(f"/documents/{DOC}/summary/review", headers=emp, json={}).status_code == 403
    new = client.post(f"/documents/{DOC}/summary", headers=officer, json={"force": True}).json()["summary"]
    assert new["id"] != s["id"]
    ok = client.post(f"/documents/{DOC}/summary/review", headers=officer, json={"note": "ตรวจแล้ว"}).json()["summary"]
    assert ok["reviewed_by"] == "nida" and ok["review_note"] == "ตรวจแล้ว"
    md = client.get(f"/documents/{DOC}/summary/markdown", headers=emp).text
    assert "รับรองโดย nida" in md

    audit = client.get("/audit?event=doc_summary", headers=officer).json()
    assert any(e["payload"]["summary_id"] == s["id"] and e["payload"]["cited_chunks"] for e in audit)


def test_a_summary_of_an_older_text_is_flagged_and_cannot_be_signed_off(client, no_summary):
    officer = _auth(client, "nida", "demo-compliance")
    s = client.post(f"/documents/{DOC}/summary", headers=officer, json={}).json()["summary"]
    with engine().begin() as c:  # as if the document had been re-ingested with different text
        c.execute(text("UPDATE document_summaries SET fingerprint = repeat('0', 64) WHERE id = :i"), {"i": s["id"]})
    assert client.get(f"/documents/{DOC}/summary", headers=officer).json()["summary"]["stale"]
    assert client.post(f"/documents/{DOC}/summary/review", headers=officer, json={}).status_code == 422


def test_summaries_follow_the_documents_access_rules(client):
    emp = _auth(client)
    # PROC-STR-001 is confidential and limited to compliance: for an employee it does not exist
    assert client.get("/documents/proc-str-001/summary", headers=emp).status_code == 404
    assert client.post("/documents/proc-str-001/summary", headers=emp, json={}).status_code == 404
    with engine().begin() as c:  # and row-level security hides the stored summary itself
        c.execute(text("SET LOCAL ROLE copilot_reader"))
        c.execute(text("SELECT set_config('app.clearance', '1', true), set_config('app.department', 'retail', true)"))
        n = c.execute(text("SELECT count(*) FROM document_summaries WHERE document_id = 'proc-str-001'")).scalar_one()
    assert n == 0


@pytest.mark.parametrize(("question", "expected"), [
    ("สรุป PDPA ให้หน่อย", "pdpa-2562"),
    ("ขอใจความสำคัญของ พ.ร.บ.ฟอกเงิน", "amla-2542"),
    ("สาระสำคัญของ ทธ. 35/2556 มีอะไรบ้าง", "sec-tt-35-2556"),
    ("สรุป PDPA มาตรา 26", None),            # one section, not the whole document
    ("PDPA ต้องแจ้งเหตุภายในกี่ชั่วโมง", None),  # a question, not a summary request
    ("สรุปให้หน่อย", None),                   # no document named
    ("สรุป PDPA กับ พ.ร.บ.ฟอกเงิน", None),     # two documents: do not guess
])
def test_whole_document_requests_are_recognised(corpus, question, expected):
    hint = ds.whole_document_request(question, EMPLOYEE)
    assert (hint or {}).get("document_id") == expected


def test_chat_points_to_the_full_summary(client):
    h = _auth(client)
    r = client.post("/chat", headers=h, json={"question": "สรุป PDPA ให้หน่อย"}).json()
    assert r["summary_hint"]["document_id"] == "pdpa-2562" and r["summary_hint"]["units"] > 100
    plain = client.post("/chat", headers=h, json={"question": "PDPA ต้องแจ้งเหตุภายในกี่ชั่วโมง"}).json()
    assert plain["summary_hint"] is None
    for resp in (r, plain):
        if conv := resp.get("conversation_id"):
            client.post(f"/conversations/{conv}/delete", headers=h)
