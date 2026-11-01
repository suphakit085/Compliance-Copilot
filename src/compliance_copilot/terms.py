"""Acceptable-use terms: one versioned text, shown in the UI, accepted per user, audited.

The text lives in ``config/terms.th.md`` (front matter ``version``). Bumping the version makes every
user accept again. With ``COPILOT_TERMS_REQUIRED=true`` the API refuses to answer questions until the
signed-in user has accepted the current version - the UI gate is a convenience, this is the control.
"""

from __future__ import annotations

from functools import lru_cache

import yaml

from .config import ROOT, get_settings

PATH = ROOT / "config" / "terms.th.md"


@lru_cache
def load() -> tuple[str, str]:
    """(version, markdown body)"""
    text = PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
    _, front, body = text.split("---", 2)
    return str(yaml.safe_load(front)["version"]), body.strip()


def current_version() -> str:
    return load()[0]


def accepted(user_version: str | None) -> bool:
    """True if no terms are required, or the user accepted the current version."""
    return not get_settings().terms_required or user_version == current_version()
