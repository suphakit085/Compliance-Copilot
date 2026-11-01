"""Document governance: who owns, who approved, when it must be reviewed.

An answer is only as trustworthy as the policy behind it, so an internal document may not
enter the index without a named owner and approver, an approval date and a review date, and
only documents whose status is ``approved`` are searchable. Drafts and withdrawn documents
stay out of the index (and are removed from it if they were indexed earlier). A policy that
was replaced by a newer version stays ``approved``: its ``effective_to`` date retires it, so
questions "as of" an earlier date still find it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from .db import CLEARANCE

REQUIRED = ("owner", "approved_by", "approved_on", "review_due", "status")
STATUSES = ("draft", "approved", "withdrawn")
_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class GovernanceError(ValueError):
    """One or more documents fail the intake rules; the message lists every problem."""


def as_date(v: Any) -> date | None:
    if v is None or isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v))
    except ValueError:
        return None


def problems(meta: dict[str, Any], today: date | None = None) -> list[str]:
    """Everything wrong with an internal document's front matter (empty list = acceptable)."""
    today = today or date.today()
    out: list[str] = []
    for key in ("id", "title", "short_title", "doc_type", *REQUIRED):
        if not meta.get(key):
            out.append(f"missing '{key}'")
    if meta.get("id") and not _ID.match(str(meta["id"])):
        out.append("id must be lowercase letters, digits and hyphens (e.g. pol-gift-2568)")
    if meta.get("status") and meta["status"] not in STATUSES:
        out.append(f"status must be one of {', '.join(STATUSES)}")
    if meta.get("classification", "internal") not in CLEARANCE:
        out.append(f"classification must be one of {', '.join(CLEARANCE)}")
    approved, review = as_date(meta.get("approved_on")), as_date(meta.get("review_due"))
    for key, parsed in (("approved_on", approved), ("review_due", review)):
        if meta.get(key) and parsed is None:
            out.append(f"'{key}' must be a date (YYYY-MM-DD)")
    if approved and review and review <= approved:
        out.append("review_due must be after approved_on")
    if approved and approved > today and meta.get("status") == "approved":
        out.append("approved_on is in the future")
    eff, end = as_date(meta.get("effective_from")), as_date(meta.get("effective_to"))
    if meta.get("status") == "approved" and not eff:
        out.append("an approved policy needs effective_from")
    if eff and end and end <= eff:
        out.append("effective_to must be after effective_from")
    return out


def validate(specs: list[Any], today: date | None = None) -> None:
    """Raise GovernanceError listing every problem across the internal documents."""
    found = []
    for spec in specs:
        if spec.source_kind != "internal":
            continue
        found += [f"{spec.id}: {p}" for p in problems(spec.meta, today)]
        if spec.path.stem != spec.id:
            found.append(f"{spec.id}: file name {spec.path.name} must match the id")
    if found:
        raise GovernanceError("document governance check failed:\n  - " + "\n  - ".join(found))


@dataclass(frozen=True)
class Review:
    state: str  # ok | due_soon | overdue
    days_left: int | None


def review_state(meta: dict[str, Any], today: date | None = None, warn_days: int = 30) -> Review:
    today = today or date.today()
    due, end = as_date(meta.get("review_due")), as_date(meta.get("effective_to"))
    if due is None or (end and end <= today):  # superseded documents need no review
        return Review("ok", None)
    left = (due - today).days
    return Review("overdue" if left < 0 else "due_soon" if left <= warn_days else "ok", left)


def to_record(meta: dict[str, Any]) -> dict[str, Any]:
    """What is stored with the document (JSON-safe)."""
    keys = ("owner", "approved_by", "approved_on", "review_due", "status")
    return {k: str(meta[k]) for k in keys if meta.get(k)}
