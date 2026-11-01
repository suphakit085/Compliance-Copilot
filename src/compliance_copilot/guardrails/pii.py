"""PII detection and masking for user input (PDPA data minimisation).

Questions are masked *before* they reach the LLM provider, the audit log or any
trace, so customer identifiers typed into the chat never leave the bank or persist.
Only the type and count of what was masked is recorded.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache

from ..ingestion.thai_text import to_arabic_digits

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_THAI_ID = re.compile(r"(?<!\d)(\d)[\s-]?(\d{4})[\s-]?(\d{5})[\s-]?(\d{2})[\s-]?(\d)(?!\d)")
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_ACCOUNT = re.compile(r"(?<!\d)\d{3}-\d-\d{5}-\d(?!\d)|(?<=บัญชี)\s*(?:เลขที่\s*)?\d{10,12}(?!\d)")
_PHONE = re.compile(r"(?<![\d])(?:\+66[\s-]?|0)(?:[689]\d[\s-]?\d{3}[\s-]?\d{4}|[2-7][\s-]?\d{3}[\s-]?\d{4})(?!\d)")
_PERSON = re.compile(r"(นางสาว|นาย|นาง|น\.ส\.|ด\.ช\.|ด\.ญ\.|คุณ)\s?([ก-๙]+)(?:\s+([ก-๙]+))?")
_EN_PERSON = re.compile(r"\b(Mr|Mrs|Ms|Miss)\.?\s+[A-Z][a-z]+(\s+[A-Z][a-z]+)?")


@lru_cache(maxsize=1)
def _thai_words() -> frozenset[str]:
    from pythainlp.corpus import thai_words

    return frozenset(thai_words())


def valid_thai_id(digits: str) -> bool:
    if len(digits) != 13 or not digits.isdigit():
        return False
    s = sum(int(digits[i]) * (13 - i) for i in range(12))
    return (11 - s % 11) % 10 == int(digits[12])


def luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


@dataclass
class MaskResult:
    text: str
    found: Counter = field(default_factory=Counter)

    @property
    def has_pii(self) -> bool:
        return bool(self.found)


def _mask_thai_names(t: str, found: Counter) -> str:
    """Mask "นายสมชาย ใจดี" but not "นายจ้าง", "นายทะเบียน", "นางพยาบาล".

    Thai has no spaces between words, so the text after a title is segmented and the
    first word checked against the dictionary: title+word being a dictionary entry
    (นายจ้าง) means it is an ordinary noun, not a person.
    """
    from pythainlp.tokenize import word_tokenize

    words = _thai_words()
    out, pos = [], 0
    for m in _PERSON.finditer(t):
        title, first, last = m.group(1), m.group(2), m.group(3)
        w1 = word_tokenize(first, engine="newmm")[0]
        if title + w1 in words:
            continue
        # "คุณ" is also the pronoun "you" ("คุณช่วย…"); treat it as a title only when it is
        # followed by a given name and a separate surname (over-masking is the safe failure).
        if title == "คุณ" and (not last or len(first) > 20 or len(last) > 20):
            continue
        out.append(t[pos:m.start()])
        if len(first) > 20:  # given name runs straight into the rest of the sentence
            out.append("[ชื่อบุคคล]" + first[len(w1):] + (f" {last}" if last else ""))
        elif last and len(last) <= 20:  # given name + surname
            out.append("[ชื่อบุคคล]")
        else:
            out.append("[ชื่อบุคคล]" + (f" {last}" if last else ""))
        found["ชื่อบุคคล"] += 1
        pos = m.end()
    out.append(t[pos:])
    return "".join(out)


def mask_pii(text: str) -> MaskResult:
    found: Counter = Counter()
    t = to_arabic_digits(text)

    def sub(pattern: re.Pattern, tag: str, check=None):
        nonlocal t

        def repl(m: re.Match) -> str:
            if check and not check(m):
                return m.group(0)
            found[tag] += 1
            return f"[{tag}]"

        t = pattern.sub(repl, t)

    sub(_EMAIL, "อีเมล")
    # Dash/space-formatted IDs are masked on format alone; bare 13-digit runs need a valid checksum.
    sub(_THAI_ID, "เลขบัตรประชาชน",
        lambda m: bool(re.search(r"[\s-]", m.group(0))) or valid_thai_id("".join(m.groups())))
    sub(_CARD, "เลขบัตร", lambda m: luhn_ok(re.sub(r"\D", "", m.group(0))) and len(re.sub(r"\D", "", m.group(0))) >= 13)
    sub(_ACCOUNT, "เลขบัญชี")
    sub(_PHONE, "เบอร์โทร")

    t = _mask_thai_names(t, found)
    sub(_EN_PERSON, "ชื่อบุคคล")
    return MaskResult(t, found)
