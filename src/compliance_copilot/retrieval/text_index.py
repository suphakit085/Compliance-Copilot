"""Thai-aware lexical indexing.

PostgreSQL full-text search splits on whitespace, but Thai is written without
spaces between words. We therefore segment Thai with PyThaiNLP (dictionary-based
``newmm``) *before* the text reaches Postgres and index the space-joined tokens with
the ``simple`` configuration. Queries go through the same tokenizer, so both sides
agree on word boundaries.
"""

from __future__ import annotations

import re
from functools import lru_cache

from ..ingestion.thai_text import normalize_text

_KEEP = re.compile(r"[ก-๛A-Za-z0-9]")
_REF = re.compile(r"(มาตรา|ข้อ)\s*(\d{1,3}(?:/\d{1,2})?(?:\.\d{1,2}){0,2})")


@lru_cache(maxsize=1)
def _stopwords() -> frozenset[str]:
    from pythainlp.corpus import thai_stopwords

    return frozenset(thai_stopwords()) | {"ไหม", "อะไร", "อย่างไร", "ยังไง", "เท่าไร", "เท่าไหร่", "ครับ", "ค่ะ", "คะ", "บ้าง", "หรือไม่"}


def tokenize(text: str) -> list[str]:
    from pythainlp.tokenize import word_tokenize

    text = normalize_text(text).lower()
    return [t for t in word_tokenize(text, engine="newmm", keep_whitespace=False) if _KEEP.search(t)]


def tokens_for_index(text: str) -> str:
    return " ".join(tokenize(text))


def query_terms(query: str) -> list[str]:
    seen: list[str] = []
    for t in tokenize(query):
        if t not in _stopwords() and t not in seen:
            seen.append(t)
    return seen


def explicit_references(query: str) -> list[tuple[str, str]]:
    """References such as "มาตรา 37" or "ข้อ 2.3.2" typed by the user."""
    return [(m.group(1), m.group(2)) for m in _REF.finditer(normalize_text(query))]
