"""The evaluation question sets are data a decision rests on, so they are tested like code:
structure, references, uniqueness - and the parts of the expected behaviour that need no LLM
(prompt-injection blocking, false-positive guard, PII masking)."""


import pytest
import yaml

from compliance_copilot import review
from compliance_copilot.config import ROOT
from compliance_copilot.guardrails.input_guard import screen
from compliance_copilot.guardrails.pii import mask_pii

SETS = {
    "main": [ROOT / "eval" / "golden_set.yaml"],
    "holdout": [ROOT / "eval" / "holdout_set.yaml"],
    "extended": sorted((ROOT / "eval" / "extended").glob("*.yaml")),
}
CATEGORIES = {"regulation", "policy", "conflict", "versioning", "rbac", "explicit_ref", "ocr",
              "out_of_scope", "unanswerable", "injection", "pii"}
USERS = {u["username"] for u in yaml.safe_load((ROOT / "config" / "users.yaml").read_text(encoding="utf-8"))["users"]}
DOCS = (
    {d["id"] for d in yaml.safe_load((ROOT / "data" / "sources.yaml").read_text(encoding="utf-8"))["documents"]}
    | {p.stem for p in (ROOT / "data" / "internal").glob("*.md")}
)


def items(name: str) -> list[dict]:
    return [it for f in SETS[name] for it in yaml.safe_load(f.read_text(encoding="utf-8"))["items"]]


ALL = [(n, it) for n in SETS for it in items(n)]


def test_ids_are_unique_across_every_set():
    ids = [it["id"] for _, it in ALL]
    assert len(ids) == len(set(ids)) and len(ids) >= 200  # target of the readiness plan


@pytest.mark.parametrize(("name", "it"), ALL, ids=[f"{n}:{it['id']}" for n, it in ALL])
def test_every_question_is_well_formed(name, it):
    assert it["category"] in CATEGORIES and it["user"] in USERS
    assert it["expect"] in ("answer", "abstain", "block") and it["question"].strip()
    for ev in it.get("evidence", []):
        assert ev["doc"] in DOCS and len(ev["text"]) >= 10  # a too-short quote matches anything
    for doc in it.get("forbidden_docs", []):
        assert doc in DOCS
    for alts in it.get("key_facts", []):
        assert isinstance(alts, list) and alts and all(isinstance(a, str) and a for a in alts)
    if it["expect"] == "answer" and it["category"] not in ("pii",):
        assert it.get("evidence"), "an answerable question needs gold evidence"
        assert it.get("key_facts"), "an answerable question needs facts the answer must contain"
    if it["expect"] != "answer":
        assert not it.get("evidence") and not it.get("key_facts")
    if it.get("pii_expected"):
        assert it["expect"] == "answer"


def test_extended_set_covers_every_document_and_every_category():
    covered = {ev["doc"] for it in items("extended") for ev in it.get("evidence", [])}
    assert {"pdpa-2562", "pdpc-breach-2565", "amla-2542", "cdd-2563", "bot-responsible-lending-2566",
            "bot-amlo-sanctions-jps-2567", "sec-tt-35-2556", "sec-outsourcing-circular-2568",
            "pol-aml-001", "pol-gift-2566", "pol-gift-2568", "pol-lending-001", "pol-pdpa-001", "proc-str-001"} <= covered
    assert {it["category"] for it in items("extended")} >= {"regulation", "policy", "conflict", "versioning", "rbac",
                                                           "explicit_ref", "out_of_scope", "unanswerable", "injection", "pii"}


@pytest.mark.parametrize("it", [i for i in items("extended") if i["expect"] == "block"], ids=lambda i: i["id"])
def test_prompt_injection_questions_are_blocked(it):
    assert screen(it["question"]).blocked


@pytest.mark.parametrize("it", [i for n, i in ALL if i["expect"] == "answer"], ids=lambda i: i["id"])
def test_legitimate_questions_are_never_blocked_by_the_guard(it):
    # an over-eager injection filter once refused "กฎกระทรวงยกเลิก..." - this keeps that from returning
    assert not screen(it["question"]).blocked


@pytest.mark.parametrize("it", [i for i in items("extended") if i.get("pii_expected")], ids=lambda i: i["id"])
def test_personal_data_in_questions_is_masked(it):
    masked = mask_pii(it["question"])
    assert masked.found, "the question carries personal data that must be masked"
    for token in ("1-1017-00012-34-4", "081-234-5678", "4111 1111 1111 1111", "somchai.jaidee@example.com",
                  "3-1005-01234-56-3", "123-4-56789-0"):
        assert token not in masked.text


# ----------------------------------------------------------------------------- review ledger


def test_review_status_goes_stale_when_a_question_is_edited():
    it = {"id": "t-1", "question": "q", "user": "nida", "expect": "answer", "evidence": [{"doc": "d", "text": "x" * 20}],
          "key_facts": [["a"]]}
    ledger = {"t-1": {"verdict": "ok", "reviewer": "r", "fp": review.fingerprint(it)}}
    assert review.status(it, ledger) == "reviewed"
    assert review.status({**it, "question": "edited"}, ledger) == "stale"  # approval does not carry over
    assert review.status({**it, "id": "t-2"}, ledger) == "draft"
    assert review.apply([it], only_reviewed=True, ledger=ledger) == [it]
    assert review.apply([{**it, "question": "edited"}], only_reviewed=True, ledger=ledger) == []
    ledger["t-1"]["verdict"] = "reject"
    assert review.apply([it], ledger=ledger) == []  # rejected questions never count


def test_review_workbook_round_trip(tmp_path):
    from openpyxl import load_workbook

    its = items("extended")[:5]
    path = tmp_path / "r.xlsx"
    assert review.export_xlsx(its, path, ledger={}) == 5
    wb = load_workbook(path)
    ws = wb["ตรวจเฉลย"]
    ws["J2"], ws["J3"], ws["K3"], ws["J4"] = "ok", "fix", "ตัวเลขผิด", "reject"
    wb.save(path)
    ledger_path = tmp_path / "ledger.yaml"
    from unittest import mock

    with mock.patch.object(review, "LEDGER", ledger_path):
        counts = review.import_xlsx(path, its, "ผู้ตรวจ ก", ledger={})
        saved = review.load_ledger()
    assert counts == {"ok": 1, "fix": 1, "reject": 1}
    assert saved[its[0]["id"]]["verdict"] == "ok" and saved[its[1]["id"]]["note"] == "ตัวเลขผิด"
    assert review.status(its[0], saved) == "reviewed" and review.status(its[1], saved) == "needs_fix"


def test_review_import_rejects_bad_rows_without_saving_anything(tmp_path):
    from unittest import mock

    from openpyxl import load_workbook

    its = items("extended")[:3]
    path = tmp_path / "bad.xlsx"
    review.export_xlsx(its, path, ledger={})
    wb = load_workbook(path)
    ws = wb["ตรวจเฉลย"]
    ws["J2"] = "ok"
    ws["J3"] = "maybe"
    ws["J4"] = "fix"  # fix without a comment
    wb.save(path)
    ledger_path = tmp_path / "ledger.yaml"
    with mock.patch.object(review, "LEDGER", ledger_path), pytest.raises(ValueError, match="maybe") as e:
        review.import_xlsx(path, its, "x", ledger={})
    assert "needs a comment" in str(e.value)  # every bad row is reported, not just the first
    assert not ledger_path.exists()  # all-or-nothing: the valid first row was not recorded either
