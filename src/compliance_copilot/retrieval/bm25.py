"""Okapi BM25 over Thai-segmented tokens, with corpus statistics read from Postgres."""

from __future__ import annotations

import math
import threading
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import text

K1 = 1.2
B = 0.75


@dataclass(frozen=True)
class CorpusStats:
    n_docs: int
    avg_len: float
    df: dict[str, int]
    version: str


_cache: dict[str, CorpusStats] = {}
_lock = threading.Lock()


def corpus_stats(conn, strategy: str) -> CorpusStats:
    """Document frequencies per token; recomputed only when the chunk table changes."""
    version = conn.execute(
        text("SELECT count(*) || ':' || coalesce(max(d.ingested_at)::text, '') FROM chunks c "
             "JOIN documents d ON d.id = c.document_id WHERE c.strategy = :s"),
        {"s": strategy},
    ).scalar_one()
    with _lock:
        cached = _cache.get(strategy)
        if cached and cached.version == version:
            return cached
    df: Counter[str] = Counter()
    total = 0
    n = 0
    for (tokens,) in conn.execute(text("SELECT tokens_text FROM chunks WHERE strategy = :s"), {"s": strategy}):
        toks = tokens.split()
        total += len(toks)
        n += 1
        df.update(set(toks))
    stats = CorpusStats(n_docs=n, avg_len=(total / n) if n else 1.0, df=dict(df), version=version)
    with _lock:
        _cache[strategy] = stats
    return stats


def score(query_terms: list[str], doc_tokens: list[str], stats: CorpusStats) -> float:
    tf = Counter(doc_tokens)
    dl = len(doc_tokens) or 1
    out = 0.0
    for t in query_terms:
        f = tf.get(t, 0)
        if not f:
            continue
        df = stats.df.get(t, 0)
        idf = math.log(1 + (stats.n_docs - df + 0.5) / (df + 0.5))
        out += idf * f * (K1 + 1) / (f + K1 * (1 - B + B * dl / stats.avg_len))
    return out
