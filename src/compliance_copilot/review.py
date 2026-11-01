"""Expert review of evaluation questions.

A question set written by engineers measures the system against the engineers' reading of the
law. The people who can say whether an expected answer is *right* are the compliance staff, so
this module gets the questions to them and records their verdicts:

* ``export_xlsx`` writes a workbook (question, expected behaviour, the quoted evidence, the facts
  an answer must contain) with a verdict column;
* ``import_xlsx`` records the verdicts in ``eval/review/ledger.yaml``, keyed by a fingerprint of
  the item, so editing a question after review makes its review *stale* instead of silently
  keeping the approval;
* the evaluation can then be restricted to reviewed questions, and every report says how much of
  the set an expert has actually checked.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from .config import ROOT

LEDGER = ROOT / "eval" / "review" / "ledger.yaml"
VERDICTS = ("ok", "fix", "reject")
EXPECT_TH = {"answer": "ต้องตอบได้", "abstain": "ต้องปฏิเสธ (ไม่มีหลักฐานพอ)", "block": "ต้องถูกบล็อก (prompt injection)"}


def fingerprint(item: dict[str, Any]) -> str:
    """Hash of everything a reviewer judges; changing any of it invalidates the review."""
    keys = ("question", "user", "as_of", "expect", "evidence", "key_facts", "forbidden_docs")
    body = json.dumps({k: item.get(k) for k in keys}, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def load_ledger(path: Path | None = None) -> dict[str, dict[str, Any]]:
    p = path or LEDGER
    if not p.exists():
        return {}
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("reviews", {})


def save_ledger(reviews: dict[str, dict[str, Any]], path: Path | None = None) -> None:
    p = path or LEDGER
    p.parent.mkdir(parents=True, exist_ok=True)
    header = ("# Expert verdicts on evaluation questions. Written by `copilot eval-review import`.\n"
              "# ok = expected answer confirmed | fix = needs correction (see note) | reject = remove from metrics.\n"
              "# `fp` fingerprints the question as reviewed; if it is edited the review becomes stale.\n")
    body = yaml.safe_dump({"reviews": dict(sorted(reviews.items()))}, allow_unicode=True, sort_keys=False)
    p.write_text(header + body, encoding="utf-8", newline="\n")


def status(item: dict[str, Any], ledger: dict[str, dict[str, Any]]) -> str:
    """draft | reviewed | stale | needs_fix | rejected"""
    r = ledger.get(item["id"])
    if not r:
        return "draft"
    if r.get("fp") != fingerprint(item):
        return "stale"
    return {"ok": "reviewed", "fix": "needs_fix", "reject": "rejected"}[r["verdict"]]


def apply(items: list[dict[str, Any]], only_reviewed: bool = False,
          ledger: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Rejected questions never count; optionally keep only expert-confirmed ones."""
    ledger = load_ledger() if ledger is None else ledger
    out = []
    for it in items:
        st = status(it, ledger)
        if st == "rejected" or (only_reviewed and st != "reviewed"):
            continue
        out.append(it)
    return out


def summary(items: list[dict[str, Any]], ledger: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    ledger = load_ledger() if ledger is None else ledger
    c = Counter(status(it, ledger) for it in items)
    n = len(items)
    return {"total": n, **{k: c.get(k, 0) for k in ("reviewed", "draft", "stale", "needs_fix", "rejected")},
            "reviewed_share": round(c.get("reviewed", 0) / n, 3) if n else 0.0}


# ------------------------------------------------------------------------------ spreadsheet

_HEADERS = ["id", "หมวด", "ผู้ถาม", "ณ วันที่", "คำถาม", "พฤติกรรมที่ระบบควรทำ", "หลักฐานที่ถูกต้อง (เอกสาร: ข้อความ)",
            "คำตอบต้องมีสาระดังนี้", "สถานะ", "ผลตรวจ (ok / fix / reject)", "ความเห็นผู้ตรวจ"]


def export_xlsx(items: list[dict[str, Any]], path: Path, only_pending: bool = False,
                ledger: dict[str, dict[str, Any]] | None = None) -> int:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation

    ledger = load_ledger() if ledger is None else ledger
    wb = Workbook()
    ws = wb.active
    ws.title = "ตรวจเฉลย"
    ws.append(_HEADERS)
    n = 0
    for it in items:
        st = status(it, ledger)
        if only_pending and st in ("reviewed", "rejected"):
            continue
        ev = "\n".join(f"{e['doc']}: {e['text']}" for e in it.get("evidence", [])) or "-"
        facts = "\n".join(" หรือ ".join(alts) for alts in it.get("key_facts", [])) or "-"
        ws.append([it["id"], it["category"], it["user"], str(it.get("as_of") or ""), it["question"],
                   EXPECT_TH[it["expect"]], ev, facts, st, "", ""])
        n += 1
    for cell in ws[1]:
        cell.font, cell.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1F3A5F")
    widths = [16, 14, 12, 12, 60, 24, 70, 40, 12, 22, 40]
    for col, w in zip("ABCDEFGHIJK", widths, strict=True):
        ws.column_dimensions[col].width = w
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    dv = DataValidation(type="list", formula1='"ok,fix,reject"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(f"J2:J{max(n + 1, 2)}")
    ws.freeze_panes = "E2"
    guide = wb.create_sheet("วิธีตรวจ")
    for line in [
        "ตรวจทีละแถวว่า 'พฤติกรรมที่ระบบควรทำ' และ 'หลักฐานที่ถูกต้อง' ถูกต้องตามกฎหมายและนโยบายปัจจุบันหรือไม่",
        "ok = ถูกต้อง  |  fix = ต้องแก้ (ระบุในความเห็น)  |  reject = ไม่ควรใช้วัดผล (เช่น คำถามกำกวม หรือเฉลยผิด)",
        "ถ้าไม่ได้ตรวจแถวไหน ให้เว้นช่อง 'ผลตรวจ' ไว้ จะไม่ถูกนับว่าตรวจแล้ว",
        "ห้ามแก้คอลัมน์ id",
    ]:
        guide.append([line])
    guide.column_dimensions["A"].width = 120
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return n


def import_xlsx(path: Path, items: list[dict[str, Any]], reviewer: str,
                ledger: dict[str, dict[str, Any]] | None = None) -> dict[str, int]:
    """Record the verdicts found in a returned workbook. Raises ValueError listing every bad row."""
    from openpyxl import load_workbook

    by_id = {it["id"]: it for it in items}
    ledger = dict(load_ledger() if ledger is None else ledger)
    ws = load_workbook(path, read_only=True, data_only=True)["ตรวจเฉลย"]
    rows = list(ws.iter_rows(values_only=True))
    head = [str(h or "").strip() for h in rows[0]]
    i_id, i_verdict, i_note = head.index("id"), head.index(_HEADERS[9]), head.index(_HEADERS[10])
    problems, counts = [], Counter()
    for n, row in enumerate(rows[1:], start=2):
        qid, verdict = row[i_id], str(row[i_verdict] or "").strip().lower()
        if not verdict:
            continue
        if qid not in by_id:
            problems.append(f"row {n}: unknown id {qid!r}")
        elif verdict not in VERDICTS:
            problems.append(f"row {n} ({qid}): verdict must be ok, fix or reject, got {verdict!r}")
        elif verdict == "fix" and not str(row[i_note] or "").strip():
            problems.append(f"row {n} ({qid}): 'fix' needs a comment saying what to correct")
        else:
            ledger[qid] = {"verdict": verdict, "reviewer": reviewer, "date": date.today().isoformat(),
                           "fp": fingerprint(by_id[qid]), "note": str(row[i_note] or "").strip()}
            counts[verdict] += 1
    if problems:
        raise ValueError("review file not imported:\n  - " + "\n  - ".join(problems))
    save_ledger(ledger)
    return dict(counts)
