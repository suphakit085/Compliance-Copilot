"""Thai text repair and normalization.

Thai government PDFs are a notoriously lossy source. Text extracted from them shows
a handful of systematic defects that silently wreck both keyword search and
embeddings unless they are repaired before indexing:

* **Broken SARA AM (pattern A).** Fonts such as TH SarabunPSK split "ำ" into
  NIKHAHIT + SARA AA, and the NIKHAHIT is lost on extraction, leaving a space:
  "กำหนด" -> "ก าหนด", "ต่ำ" -> "ต ่า".
* **Swapped SARA AA / SARA AM (pattern B).** Some bold fonts carry a broken
  ToUnicode map in which the glyph for "า" maps to "ำ", and the real "ำ" shows
  up as " ำ": "อำนาจตามกฎหมาย" -> "อ ำนำจตำมกฎหมำย".
* **Private Use Area glyphs.** Legacy Thai fonts place shifted tone marks and
  descender-less consonants in U+F700-U+F71A.
* **Decomposed SARA AM.** "ํ" + "า" written as two code points.

Pattern A is unambiguous (a Thai word can never start with "า") so it is repaired
with a regex. Pattern B is ambiguous at the string level, so each candidate
repair is scored by Thai dictionary coverage and the best candidate wins.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

THAI_DIGITS = "๐๑๒๓๔๕๖๗๘๙"
_DIGIT_TABLE = str.maketrans(THAI_DIGITS, "0123456789")

# Legacy Thai PUA glyphs (Microsoft/Apple "Thai shaping" variants) -> canonical code points.
_PUA_MAP = {
    0xF700: "ฐ", 0xF701: "ิ", 0xF702: "ี", 0xF703: "ึ", 0xF704: "ื",
    0xF705: "่", 0xF706: "้", 0xF707: "๊", 0xF708: "๋", 0xF709: "์",
    0xF70A: "่", 0xF70B: "้", 0xF70C: "๊", 0xF70D: "๋", 0xF70E: "์",
    0xF70F: "ญ", 0xF710: "ั", 0xF711: "ํ", 0xF712: "็", 0xF713: "่",
    0xF714: "้", 0xF715: "๊", 0xF716: "๋", 0xF717: "์", 0xF718: "ุ",
    0xF719: "ู", 0xF71A: "ฺ",
    # Symbol-font digits (used by some PDFs for superscripts)
    **{0xF030 + i: str(i) for i in range(10)},
}
_PUA_TABLE = {k: v for k, v in _PUA_MAP.items()}

_CONS = "ก-ฮ"
_TONE = "่-๋"
_UPPER_VOWEL = "ัิ-ื็"

# Pattern A: consonant [+ upper vowel] [+ tone] + space [+ tone] + SARA AA  ->  SARA AM
_BROKEN_AM = re.compile(rf"([{_CONS}][{_UPPER_VOWEL}]?[{_TONE}]?) ([{_TONE}]?)า")
# NIKHAHIT [+ tone] + SARA AA  ->  [tone +] SARA AM
_DECOMPOSED_AM = re.compile(rf"ํ([{_TONE}]?)า")
_ZERO_WIDTH = re.compile("[​‌‍﻿­]")
_THAI_CHAR = re.compile(r"[ก-๛]")
_THAI_RUN = re.compile(r"[ก-๛]+")


def map_pua(text: str) -> str:
    return text.translate(_PUA_TABLE)


def fix_broken_sara_am(text: str) -> str:
    """Repair pattern A ("ก าหนด" -> "กำหนด")."""
    text = _DECOMPOSED_AM.sub(lambda m: m.group(1) + "ำ", text)
    return _BROKEN_AM.sub(lambda m: m.group(1) + m.group(2) + "ำ", text)


def swap_aa_am(text: str) -> str:
    """Repair pattern B ("อ ำนำจ" -> "อำนาจ") - only valid for text from a broken font."""
    placeholder = "\x00"
    text = text.replace(" ำ", placeholder)
    text = text.replace("ำ", "า")
    return text.replace(placeholder, "ำ")


@lru_cache(maxsize=1)
def _thai_dictionary() -> frozenset[str]:
    from pythainlp.corpus import thai_words

    return frozenset(thai_words())


def dictionary_coverage(text: str) -> float:
    """Fraction of Thai characters that fall inside dictionary words (0..1).

    Garbled Thai tokenizes into many short non-words, so coverage drops sharply.
    """
    from pythainlp.tokenize import word_tokenize

    words = _thai_dictionary()
    total = known = 0
    for run in _THAI_RUN.findall(text):
        for tok in word_tokenize(run, engine="newmm", keep_whitespace=False):
            n = len(tok)
            total += n
            if tok in words or n == 1 and tok in "ๆฯ":
                known += n
    return known / total if total else 1.0


def garble_score(text: str) -> int:
    """Count tokens that look like segmentation debris: unknown words or lone consonants."""
    from pythainlp.tokenize import word_tokenize

    words = _thai_dictionary()
    bad = 0
    for run in _THAI_RUN.findall(text):
        for tok in word_tokenize(run, engine="newmm", keep_whitespace=False):
            if tok not in words or (len(tok) == 1 and tok not in "ๆฯ"):
                bad += 1
    return bad


def repair_thai(text: str) -> str:
    """Repair extraction defects in one span/line of Thai text."""
    if not text:
        return text
    text = map_pua(text)
    text = _ZERO_WIDTH.sub("", text)
    if " ำ" in text:
        # " ำ" never occurs in valid Thai: this text came from a pattern-B font.
        return fix_broken_sara_am(swap_aa_am(text))
    fixed = fix_broken_sara_am(text)
    if "ำ" in fixed and "า" not in fixed:
        # Possibly pattern B without a tell-tale " ำ" (e.g. "หลักกำร"): let the dictionary decide.
        alt = swap_aa_am(fixed)
        if garble_score(alt) < garble_score(fixed):
            return alt
    return fixed


def to_arabic_digits(text: str) -> str:
    return text.translate(_DIGIT_TABLE)


def normalize_text(text: str) -> str:
    """Canonical form used for both indexing and display."""
    text = unicodedata.normalize("NFC", text)
    text = to_arabic_digits(text)
    text = text.replace(" ", " ").replace("“", '"').replace("”", '"')
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def has_thai(text: str) -> bool:
    return bool(_THAI_CHAR.search(text))
