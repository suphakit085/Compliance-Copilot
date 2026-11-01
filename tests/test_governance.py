"""Corpus governance: intake rules, review dates, update detection, glossary ownership."""

from datetime import date
from pathlib import Path

import httpx
import pytest
import yaml

from compliance_copilot import governance
from compliance_copilot.config import get_settings
from compliance_copilot.ingestion import updates
from compliance_copilot.ingestion.loaders import load_manifest

GOOD = {
    "id": "pol-test-001", "title": "นโยบายทดสอบ", "short_title": "ทดสอบ", "doc_type": "policy",
    "owner": "ฝ่ายกำกับ", "approved_by": "คณะกรรมการ", "approved_on": date(2026, 1, 5),
    "review_due": date(2027, 1, 5), "status": "approved", "effective_from": date(2026, 2, 1),
    "classification": "internal",
}
TODAY = date(2026, 11, 1)


def test_complete_front_matter_is_accepted():
    assert governance.problems(GOOD, TODAY) == []


@pytest.mark.parametrize("field", governance.REQUIRED)
def test_each_governance_field_is_required(field):
    assert any(field in p for p in governance.problems({**GOOD, field: None}, TODAY))


def test_bad_values_are_explained():
    assert governance.problems({**GOOD, "status": "final"}, TODAY)
    assert governance.problems({**GOOD, "review_due": date(2025, 1, 1)}, TODAY)  # before approval
    assert governance.problems({**GOOD, "approved_on": date(2027, 1, 1), "review_due": date(2028, 1, 1)}, TODAY)
    assert governance.problems({**GOOD, "effective_from": None}, TODAY)
    assert governance.problems({**GOOD, "id": "Policy_1"}, TODAY)
    assert governance.problems({**GOOD, "classification": "secret"}, TODAY)
    assert governance.problems({**GOOD, "approved_on": "not-a-date"}, TODAY)


def test_review_reminders():
    assert governance.review_state({"review_due": date(2026, 10, 1)}, TODAY).state == "overdue"
    assert governance.review_state({"review_due": date(2026, 11, 20)}, TODAY).state == "due_soon"
    assert governance.review_state({"review_due": date(2027, 6, 1)}, TODAY).state == "ok"
    # a superseded policy is not nagged about
    assert governance.review_state({"review_due": date(2024, 1, 1), "effective_to": date(2025, 7, 1)}, TODAY).state == "ok"


def test_every_internal_document_in_the_repo_passes_the_rules():
    governance.validate(load_manifest())


def test_only_approved_documents_are_indexed_and_drafts_are_flagged():
    specs = [s for s in load_manifest() if s.source_kind == "internal"]
    assert specs and all(s.meta["status"] in governance.STATUSES for s in specs)
    # an old, superseded version must stay searchable for "as of" questions
    old = next(s for s in specs if s.id == "pol-gift-2566")
    assert old.meta["status"] == "approved" and old.meta["effective_to"]


def test_validation_lists_every_problem_at_once():
    class Spec:
        source_kind, id, path = "internal", "pol-bad", Path("wrong-name.md")
        meta = {"id": "pol-bad"}

    with pytest.raises(governance.GovernanceError) as e:
        governance.validate([Spec()])
    msg = str(e.value)
    assert "owner" in msg and "approved_by" in msg and "file name" in msg


def test_glossary_terms_point_at_real_documents():
    data = get_settings().data_dir
    g = yaml.safe_load((data / "glossary.yaml").read_text(encoding="utf-8"))
    ids = {d["id"] for d in yaml.safe_load((data / "sources.yaml").read_text(encoding="utf-8"))["documents"]}
    ids |= {p.stem for p in (data / "internal").glob("*.md")}  # a term may point at an internal policy
    assert g["terms"] and all(t["source"] in ids for t in g["terms"])


@pytest.fixture
def lock_dir(tmp_path, monkeypatch):
    s = get_settings()
    (tmp_path / "raw").mkdir()
    monkeypatch.setattr(s, "data_dir", tmp_path)
    import hashlib
    docs = [{"id": "a", "url": "https://x.test/a.pdf"}, {"id": "b", "url": "https://x.test/b.pdf"},
            {"id": "c", "url": "https://x.test/c.pdf"}, {"id": "d", "url": "https://x.test/d.pdf"}]
    (tmp_path / "sources.yaml").write_text(yaml.safe_dump({"documents": docs}), encoding="utf-8")
    sha = lambda b: hashlib.sha256(b).hexdigest()  # noqa: E731
    lock = {k: {"url": "u", "sha256": sha(b"%PDF-old-" + k.encode()), "retrieved_at": "2026-01-01T00:00:00+00:00"} for k in "abcd"}
    updates.lock_path().write_text(__import__("json").dumps(lock), encoding="utf-8")
    return tmp_path


def test_update_check_reports_changes_without_touching_stored_files(lock_dir):
    def handler(req):
        name = req.url.path.strip("/").split(".")[0]
        return {
            "a": httpx.Response(200, content=b"%PDF-old-a"),          # same
            "b": httpx.Response(200, content=b"%PDF-new-b"),          # revised by the publisher
            "c": httpx.Response(403),                                 # blocked
            "d": httpx.Response(200, content=b"<html>login</html>"),  # not a PDF
        }[name]

    client = httpx.Client(transport=httpx.MockTransport(handler))
    got = {r.doc_id: r.status for r in updates.check_updates(log=lambda _: None, client=client)}
    assert got == {"a": "unchanged", "b": "changed", "c": "unreachable", "d": "not_pdf"}
    lock = updates.read_lock()
    assert "checked_at" in lock["a"] and "checked_at" not in lock["b"]  # only verified sources are stamped
    assert lock["b"]["sha256"].startswith(__import__("hashlib").sha256(b"%PDF-old-b").hexdigest()[:10])
    assert set(updates.stale_sources(date(2026, 11, 1))) >= {"b", "c", "d"}


TEMPLATE = Path(__file__).resolve().parents[1] / "docs" / "policy-template.md"


def test_template_is_a_valid_policy_and_comments_are_not_indexed(tmp_path):
    f = tmp_path / "pol-example-001.md"
    f.write_text(TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
    logs: list[str] = []
    assert updates.add_policy(f, dry_run=True, log=logs.append) == "pol-example-001"
    assert "ข้อ 1, ข้อ 2" in logs[0] and not any("WARNING" in m for m in logs)  # short policies still parse


def test_intake_rejects_bad_files(tmp_path):
    text = TEMPLATE.read_text(encoding="utf-8")
    bad = tmp_path / "pol-example-001.md"
    bad.write_text(text.replace("approved_by:", "# approved_by:"), encoding="utf-8")
    with pytest.raises(governance.GovernanceError, match="approved_by"):
        updates.add_policy(bad, dry_run=True)
    wrong_name = tmp_path / "other.md"
    wrong_name.write_text(text, encoding="utf-8")
    with pytest.raises(governance.GovernanceError, match="file name"):
        updates.add_policy(wrong_name, dry_run=True)
    existing = Path(get_settings().data_dir / "internal" / "pol-gift-2568.md")
    dup = tmp_path / "pol-gift-2568.md"
    dup.write_text(existing.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(governance.GovernanceError, match="already exists"):
        updates.add_policy(dup, dry_run=True)


@pytest.mark.integration
def test_only_approved_policies_are_searchable(corpus):
    from sqlalchemy import text

    from compliance_copilot.db import engine
    from compliance_copilot.ingestion.pipeline import ingest

    doc_id = "pol-zz-gate-test"
    f = get_settings().data_dir / "internal" / f"{doc_id}.md"
    body = TEMPLATE.read_text(encoding="utf-8").replace("pol-example-001", doc_id)

    def indexed() -> int:
        with engine().connect() as c:
            return c.execute(text("SELECT count(*) FROM documents WHERE id = :i"), {"i": doc_id}).scalar_one()

    try:
        f.write_text(body.replace("status: approved ", "status: draft    "), encoding="utf-8")
        ingest(doc_ids=[doc_id], log=lambda _: None)
        assert indexed() == 0  # a draft never reaches the index

        f.write_text(body, encoding="utf-8")
        ingest(doc_ids=[doc_id], log=lambda _: None)
        assert indexed() == 1

        f.write_text(body.replace("status: approved ", "status: withdrawn"), encoding="utf-8")
        ingest(doc_ids=[doc_id], log=lambda _: None)
        assert indexed() == 0  # withdrawing a policy removes it from answers
    finally:
        f.unlink(missing_ok=True)
        with engine().begin() as c:
            c.execute(text("DELETE FROM documents WHERE id = :i"), {"i": doc_id})


@pytest.mark.integration
def test_api_lists_governance_and_does_not_nag_about_superseded_policies(corpus):
    from fastapi.testclient import TestClient

    from compliance_copilot.api.main import app
    from compliance_copilot.security import seed_users

    seed_users()
    with TestClient(app) as client:
        tok = client.post("/auth/login", json={"username": "nida", "password": "demo-compliance"}).json()["access_token"]
        docs = {d["id"]: d for d in client.get("/documents", headers={"Authorization": f"Bearer {tok}"}).json()}
    assert docs["pol-lending-001"]["governance"]["review_state"] == "overdue"  # planted sample
    assert docs["pol-gift-2566"]["governance"]["review_state"] == "ok"  # superseded in 2025
    assert docs["pol-gift-2568"]["governance"]["approved_by"]
    assert docs["pdpa-2562"]["governance"] == {} and docs["pdpa-2562"]["source_checked_at"]
