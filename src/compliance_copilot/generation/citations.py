"""Citation verification - we never take the model's word for where a fact came from.

For each citation the model must supply a verbatim quote. A quote is *verified* only
if it is found in the text of the source it claims (exact match after normalising
whitespace/digits, or a contiguous near-exact match covering >= 85% of the quote).
Unverified citations are dropped; answer markers that end up without any verified
citation are reported so the UI can flag the sentence as unsupported.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from ..ingestion.thai_text import to_arabic_digits

_MARKER = re.compile(r"\[S(\d+)\]")
_WS = re.compile(r"\s+")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFC", to_arabic_digits(s))
    s = s.replace("“", '"').replace("”", '"').replace("’", "'")
    return _WS.sub(" ", s).strip().strip('"').strip()


@dataclass
class VerifiedCitation:
    source_id: str
    quote: str
    verified: bool
    match_ratio: float
    start: int | None = None  # char offset in normalised source text


def verify_quote(quote: str, source_text: str) -> tuple[bool, float, int | None]:
    q, src = _norm(quote), _norm(source_text)
    if len(q) < 6:
        return False, 0.0, None
    idx = src.find(q)
    if idx >= 0:
        return True, 1.0, idx
    # Thai has no word spacing, so spaces/line breaks the model adds or drops are not real
    # differences: compare with all whitespace removed.
    q_ns, src_ns = q.replace(" ", ""), src.replace(" ", "")
    if q_ns and q_ns in src_ns:
        return True, 1.0, None
    m = SequenceMatcher(None, src, q, autojunk=False).find_longest_match(0, len(src), 0, len(q))
    ratio = m.size / len(q)
    return ratio >= 0.85, round(ratio, 3), m.a if ratio >= 0.85 else None


@dataclass
class GroundingReport:
    citations: list[VerifiedCitation]
    answer: str
    markers_total: int
    markers_supported: int
    unsupported_markers: list[str] = field(default_factory=list)
    invalid_sources: list[str] = field(default_factory=list)

    @property
    def verified_sources(self) -> set[str]:
        return {c.source_id for c in self.citations if c.verified}

    @property
    def support_rate(self) -> float:
        return self.markers_supported / self.markers_total if self.markers_total else 0.0


def ground(answer: str, citations: list[tuple[str, str]], sources: dict[str, str]) -> GroundingReport:
    """``citations`` = [(source_id, quote)], ``sources`` = {source_id: text}."""
    checked: list[VerifiedCitation] = []
    invalid: list[str] = []
    for sid, quote in citations:
        sid = sid.strip().strip("[]").upper()
        if sid not in sources:
            invalid.append(sid)
            continue
        ok, ratio, start = verify_quote(quote, sources[sid])
        checked.append(VerifiedCitation(sid, quote, ok, ratio, start))

    verified = {c.source_id for c in checked if c.verified}

    # Drop markers that point at sources we never provided.
    def fix(m: re.Match) -> str:
        return m.group(0) if f"S{m.group(1)}" in sources else ""

    answer = _MARKER.sub(fix, answer)
    markers = [f"S{n}" for n in _MARKER.findall(answer)]
    unsupported = sorted({m for m in markers if m not in verified})
    supported = sum(1 for m in markers if m in verified)
    return GroundingReport(checked, answer, len(markers), supported, unsupported, invalid)
