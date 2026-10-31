"""Tamper-evident audit trail (hash chain).

Regulators and internal audit need to reconstruct *who asked what, what the system
retrieved, and what it answered*. Each record's hash covers the previous record's
hash, so any later edit or deletion is detectable by re-walking the chain.
Writers are serialised with a transaction-scoped advisory lock so concurrent
requests cannot fork the chain.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text

from .db import AuditLog, session

GENESIS = "0" * 64
_LOCK_ID = 727_001


def _digest(prev_hash: str, record: dict[str, Any]) -> str:
    body = json.dumps(record, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
    return hashlib.sha256((prev_hash + body).encode("utf-8")).hexdigest()


def _record(row: AuditLog) -> dict[str, Any]:
    return {
        "ts": row.ts.astimezone(UTC).isoformat(timespec="microseconds"),
        "user_id": row.user_id,
        "username": row.username,
        "role": row.role,
        "event": row.event,
        "payload": row.payload,
    }


def log_event(event: str, payload: dict[str, Any], user: Any | None = None) -> int:
    with session() as db:
        db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _LOCK_ID})
        last = db.execute(select(AuditLog.hash).order_by(AuditLog.id.desc()).limit(1)).scalar()
        prev = last or GENESIS
        row = AuditLog(
            ts=datetime.now(UTC),
            user_id=getattr(user, "id", None),
            username=getattr(user, "username", None),
            role=getattr(user, "role", None),
            event=event,
            payload=json.loads(json.dumps(payload, ensure_ascii=False, default=str)),
            prev_hash=prev,
            hash="",
        )
        row.hash = _digest(prev, _record(row))
        db.add(row)
        db.flush()
        return row.id


def verify_chain() -> dict[str, Any]:
    prev = GENESIS
    checked = 0
    with session() as db:
        for row in db.execute(select(AuditLog).order_by(AuditLog.id)).scalars():
            if row.prev_hash != prev or _digest(prev, _record(row)) != row.hash:
                return {"valid": False, "checked": checked, "broken_at_id": row.id}
            prev = row.hash
            checked += 1
    return {"valid": True, "checked": checked, "head": prev}
