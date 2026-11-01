"""Close the loop from users to the evaluation set.

Users rate answers with 👍/👎 (stored against the audit record). ``report`` lists the 👎 with what
the system did; ``draft_question`` turns one into a *draft* evaluation item in ``eval/inbox/``.
The draft deliberately leaves the expected answer empty: the system's own answer is not the gold
(that would be circular), a compliance expert fills in the correct behaviour and evidence, and only
then does it move into a question set and into the review ledger.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select

from .config import ROOT
from .db import AuditLog, Feedback, User, session

INBOX = ROOT / "eval" / "inbox"


def report(days: int = 30, include_positive: bool = False) -> list[dict[str, Any]]:
    since = datetime.now(UTC) - timedelta(days=days)
    with session() as db:
        q = (select(Feedback, AuditLog, User.username)
             .join(AuditLog, AuditLog.id == Feedback.audit_id)
             .join(User, User.id == Feedback.user_id)
             .where(Feedback.ts >= since).order_by(Feedback.ts.desc()))
        if not include_positive:
            q = q.where(Feedback.rating < 0)
        rows = db.execute(q).all()
        out = []
        for fb, audit, username in rows:
            p = audit.payload or {}
            g = p.get("grounding") or {}
            out.append({
                "audit_id": audit.id, "ts": fb.ts.isoformat(timespec="seconds"), "rating": fb.rating,
                "user": username, "role": audit.role, "status": p.get("status"),
                "question": p.get("question_masked"), "as_of": p.get("as_of"),
                "support_rate": g.get("support_rate"), "comment": fb.comment,
                "retrieved": [r["chunk_id"] for r in p.get("retrieved", [])],
            })
        return out


def draft_question(audit_id: int, out_dir: Path | None = None) -> Path:
    """Write eval/inbox/<id>.yaml for an expert to complete. Returns the file path."""
    with session() as db:
        audit = db.get(AuditLog, audit_id)
        if not audit or audit.event != "chat":
            raise ValueError(f"audit record {audit_id} is not a chat answer")
        p = audit.payload or {}
        fb = db.execute(select(Feedback).where(Feedback.audit_id == audit_id)).scalars().first()
        username = audit.username or "somchai"
    draft = {
        "id": f"fb-{audit_id}",
        "category": "regulation",  # expert: regulation | policy | conflict | versioning | rbac | explicit_ref | ...
        "user": username,
        **({"as_of": p["as_of"]} if p.get("as_of") and p["as_of"] != str(datetime.now(UTC).date()) else {}),
        "question": p.get("standalone_question") or p.get("question_masked"),
        "expect": None,  # EXPERT: answer | abstain | block
        "evidence": [],  # EXPERT: [{doc: <id>, text: <exact words from the source>}]
        "key_facts": [],  # EXPERT: [[acceptable wording, ...], ...]
        "_context": {  # what happened - for the expert only; remove when completing the item
            "system_status": p.get("status"),
            "user_rating": fb.rating if fb else None,
            "user_comment": fb.comment if fb else None,
            "retrieved_chunks": [r["chunk_id"] for r in p.get("retrieved", [])],
            "note": "The system's answer is NOT the expected answer. Decide the correct behaviour from the sources.",
        },
    }
    path = (out_dir or INBOX) / f"fb-{audit_id}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# DRAFT - incomplete until an expert fills expect / evidence / key_facts.\n"
                    + yaml.safe_dump({"items": [draft]}, allow_unicode=True, sort_keys=False),
                    encoding="utf-8", newline="\n")
    return path
