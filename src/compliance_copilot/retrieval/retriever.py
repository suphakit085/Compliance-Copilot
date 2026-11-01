"""Hybrid, permission-aware, time-aware retrieval.

    query ─┬─ dense (BGE-M3, pgvector HNSW) ──────┐
           ├─ lexical (Thai-segmented FTS) ───────┼─ RRF fusion ─ cross-encoder rerank ─ top-n
           └─ explicit references ("มาตรา 37") ───┘

Every first-stage query carries the same WHERE clause:

* **access control** - document classification <= user clearance, and department-scoped
  documents only for members of that department. Applied *before* ranking, so a
  restricted passage can never reach the prompt, the answer or the logs.
* **validity in time** - only versions in force on ``as_of`` (default: today), so a
  superseded policy is not mixed with its replacement.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import text

from ..config import get_settings
from ..db import engine
from . import bm25, models
from .text_index import expand_query, explicit_references, query_terms

# Questions asking whether internal policy matches the law.
_COMPARISON = re.compile(r"สอดคล้อง|ขัด(กับ|ต่อ)?|เป็นไปตาม|ตรงตาม|ถูกต้องตามกฎหมาย|ผิดกฎหมาย|ฝ่าฝืน|compl(y|iant|iance)", re.I)


@dataclass
class UserContext:
    id: int | None
    username: str
    role: str
    department: str
    clearance: int
    display_name: str = ""


@dataclass
class Candidate:
    chunk_id: str
    document_id: str
    label: str
    path: list[str]
    title: str | None
    text: str
    embed_text: str
    page_start: int | None
    page_end: int | None
    notes: list[str]
    extraction: str
    doc: dict[str, Any]
    dense_rank: int | None = None
    lexical_rank: int | None = None
    ref_hit: bool = False
    rrf: float = 0.0
    rerank_score: float | None = None

    @property
    def citation_label(self) -> str:
        return f"{self.doc['short_title']} {self.label}"


@dataclass
class RetrievalResult:
    query: str
    as_of: date
    candidates: list[Candidate]
    timings_ms: dict[str, int] = field(default_factory=dict)
    notices: list[str] = field(default_factory=list)
    terms: list[str] = field(default_factory=list)
    expansions: list[str] = field(default_factory=list)

    @property
    def top_score(self) -> float:
        scores = [c.rerank_score for c in self.candidates if c.rerank_score is not None]
        return max(scores) if scores else 0.0


_SELECT = """
SELECT c.id, c.document_id, c.label, c.path, c.title, c.text, c.embed_text, c.page_start,
       c.page_end, c.notes, c.extraction,
       d.short_title, d.title AS doc_title, d.doc_type, d.source_kind, d.version,
       d.effective_from, d.effective_to, d.classification, d.official_url, d.source_url,
       d.official_ref, d.synthetic, d.superseded_by, d.supersedes, d.amended_by, d.issuer
FROM chunks c JOIN documents d ON d.id = c.document_id
"""

_ACL_AND_TIME = """
WHERE c.strategy = :strategy
  AND d.classification_level <= :clearance
  AND (jsonb_array_length(d.departments) = 0 OR d.departments ? :department)
  AND (d.effective_from IS NULL OR d.effective_from <= :as_of)
  AND (d.effective_to IS NULL OR d.effective_to > :as_of)
  {extra}
"""


def _row_to_candidate(r: Any) -> Candidate:
    doc = {
        "id": r.document_id, "short_title": r.short_title, "title": r.doc_title,
        "doc_type": r.doc_type, "source_kind": r.source_kind, "version": r.version,
        "effective_from": r.effective_from.isoformat() if r.effective_from else None,
        "effective_to": r.effective_to.isoformat() if r.effective_to else None,
        "classification": r.classification, "official_url": r.official_url,
        "source_url": r.source_url, "official_ref": r.official_ref, "synthetic": r.synthetic,
        "superseded_by": r.superseded_by, "supersedes": r.supersedes,
        "amended_by": r.amended_by or [], "issuer": r.issuer,
    }
    return Candidate(
        chunk_id=r.id, document_id=r.document_id, label=r.label, path=r.path or [],
        title=r.title, text=r.text, embed_text=r.embed_text, page_start=r.page_start,
        page_end=r.page_end, notes=r.notes or [], extraction=r.extraction, doc=doc,
    )


def _tsquery(terms: list[str]) -> str:
    return " | ".join("'" + t.replace("'", "''").replace("\\", "") + "'" for t in terms)


def _doc_hints(conn, query: str) -> list[str]:
    q = query.lower()
    hits = []
    for doc_id, aliases in conn.execute(text("SELECT id, aliases FROM documents")):
        if any(a.lower() in q for a in aliases or []):
            hits.append(doc_id)
    return hits


def retrieve(
    query: str,
    user: UserContext,
    as_of: date | None = None,
    *,
    strategy: str = "structured",
    use_dense: bool = True,
    use_lexical: bool = True,
    use_refs: bool = True,
    use_rerank: bool = True,
    use_glossary: bool = True,
    compare: bool | None = None,
    top_n: int | None = None,
    source_kind: str | None = None,
    doc_ids: list[str] | None = None,
) -> RetrievalResult:
    s = get_settings()
    as_of = as_of or date.today()
    top_n = top_n or s.context_top_n
    timings: dict[str, int] = {}
    extra = ""
    params: dict[str, Any] = {
        "strategy": strategy, "clearance": user.clearance, "department": user.department,
        "as_of": as_of,
    }
    if source_kind:
        extra += " AND d.source_kind = :source_kind"
        params["source_kind"] = source_kind
    if doc_ids:
        extra += " AND d.id = ANY(:doc_ids)"
        params["doc_ids"] = doc_ids
    where = _ACL_AND_TIME.format(extra=extra)

    pool: dict[str, Candidate] = {}
    ranked_lists: list[list[str]] = []
    search_query, expansions = expand_query(query) if use_glossary else (query, [])
    terms = query_terms(search_query)

    with engine().connect() as conn:
        if use_dense:
            t0 = time.perf_counter()
            qvec = models.embed_query(search_query)
            timings["embed_query"] = int((time.perf_counter() - t0) * 1000)
            t0 = time.perf_counter()
            conn.execute(text("SET LOCAL hnsw.ef_search = 200"))
            rows = conn.execute(
                text(_SELECT + where + " ORDER BY c.embedding <=> CAST(:qvec AS vector) LIMIT :k"),
                {**params, "qvec": str(qvec), "k": s.dense_top_k},
            ).fetchall()
            timings["dense"] = int((time.perf_counter() - t0) * 1000)
            ids = []
            for rank, r in enumerate(rows, 1):
                c = pool.setdefault(r.id, _row_to_candidate(r))
                c.dense_rank = rank
                ids.append(r.id)
            ranked_lists.append(ids)

        if use_lexical and terms:
            # Postgres prefilters (ACL + time + "matches any term"); ranking is real BM25 with
            # corpus-level IDF, which ts_rank lacks - rare legal terms must outweigh common ones.
            t0 = time.perf_counter()
            rows = conn.execute(
                text(_SELECT.replace("SELECT c.id,", "SELECT c.tokens_text, c.id,") + where
                     + " AND c.lexical @@ to_tsquery('simple', :tsq)"),
                {**params, "tsq": _tsquery(terms)},
            ).fetchall()
            stats = bm25.corpus_stats(conn, strategy)
            scored = sorted(
                ((bm25.score(terms, r.tokens_text.split(), stats), r) for r in rows),
                key=lambda x: x[0], reverse=True,
            )[: s.lexical_top_k]
            timings["lexical"] = int((time.perf_counter() - t0) * 1000)
            ids = []
            for rank, (_, r) in enumerate(scored, 1):
                c = pool.setdefault(r.id, _row_to_candidate(r))
                c.lexical_rank = rank
                ids.append(r.id)
            ranked_lists.append(ids)

        refs = explicit_references(query) if use_refs else []
        if refs:
            hinted = _doc_hints(conn, query)
            labels = [f"{kind} {num}" for kind, num in refs]
            clause = " AND (" + " OR ".join(
                f"(c.label = :l{i} OR c.label LIKE :lp{i} OR c.label LIKE :ls{i})" for i in range(len(labels))
            ) + ")"
            ref_params = {**params}
            for i, lab in enumerate(labels):
                ref_params[f"l{i}"] = lab
                ref_params[f"lp{i}"] = f"{lab} (ตอนที่%"
                ref_params[f"ls{i}"] = f"% {lab}"
            if hinted:
                clause += " AND d.id = ANY(:hinted)"
                ref_params["hinted"] = hinted
            elif not any(kind == "มาตรา" for kind, _ in refs):
                clause = None  # "ข้อ 5" without a document name is too ambiguous to look up
            if clause:
                rows = conn.execute(text(_SELECT + where + clause + " LIMIT 12"), ref_params).fetchall()
                ids = []
                for r in rows:
                    c = pool.setdefault(r.id, _row_to_candidate(r))
                    c.ref_hit = True
                    ids.append(r.id)
                ranked_lists.append(ids)

    # Reciprocal Rank Fusion
    for ids in ranked_lists:
        for rank, cid in enumerate(ids, 1):
            pool[cid].rrf += 1.0 / (s.rrf_k + rank)
    fused = sorted(pool.values(), key=lambda c: c.rrf, reverse=True)

    if use_rerank and fused:
        t0 = time.perf_counter()
        head = fused[: s.rerank_candidates]
        scores = models.rerank(search_query, [c.embed_text[:2000] for c in head])
        for c, sc in zip(head, scores, strict=True):
            c.rerank_score = sc
        head.sort(key=lambda c: c.rerank_score or 0.0, reverse=True)
        fused = head
        timings["rerank"] = int((time.perf_counter() - t0) * 1000)

    selected = fused[:top_n]

    # An internal policy never stands alone: if the context is led by a policy clause and holds
    # no regulation, look up the law governing that clause (as gap analysis does) and reserve
    # slots for it - otherwise a wrong policy (e.g. "45 days") can be repeated as the answer.
    # Comparison questions ("does our policy comply?") accept weaker matches than plain ones.
    is_comparison = bool(_COMPARISON.search(query))
    bar = s.abstain_threshold if is_comparison else s.policy_pairing_threshold
    # Count only regulations that are actually relevant: low-scoring ones that merely fill
    # slots (e.g. an unrelated section) must not suppress the lookup.
    relevant_regs = sum(
        c.doc["source_kind"] == "regulation" and (c.rerank_score or 0) >= max(bar, s.policy_pairing_threshold)
        for c in selected
    )
    if (
        compare is not False and source_kind is None
        and selected and selected[0].doc["source_kind"] == "internal" and relevant_regs < 1
    ):
        reg = retrieve(selected[0].text[:800], user, as_of, strategy=strategy,
                       source_kind="regulation", top_n=3, compare=False)
        have = {c.chunk_id for c in selected}
        reg_hits = [c for c in reg.candidates if c.chunk_id not in have and (c.rerank_score or 0) >= bar]
        if reg_hits:
            keep = max(top_n - len(reg_hits), 2)
            selected = selected[:keep] + reg_hits
            timings["policy_law_lookup"] = sum(reg.timings_ms.values())

    return RetrievalResult(
        query=query, as_of=as_of, candidates=selected, timings_ms=timings,
        notices=version_notices(selected, as_of), terms=terms, expansions=expansions,
    )


def version_notices(cands: list[Candidate], as_of: date) -> list[str]:
    """Warnings the answer must surface: pending amendments, upcoming replacements."""
    notes: list[str] = []
    seen: set[str] = set()
    for c in cands:
        d = c.doc
        if d["id"] in seen:
            continue
        seen.add(d["id"])
        for a in d.get("amended_by") or []:
            eff = a.get("effective_from")
            if eff and date.fromisoformat(eff) <= as_of:
                notes.append(
                    f"{d['short_title']} ฉบับที่ใช้ตอบอาจยังไม่รวมการแก้ไขโดย {a['ref']} "
                    f"(มีผล {eff}) - {a.get('note', '')}".strip()
                )
        if d.get("effective_to"):
            notes.append(
                f"{d['short_title']} มีผลถึง {d['effective_to']} และจะถูกแทนที่ด้วยฉบับใหม่"
            )
        if d.get("synthetic"):
            notes.append(f"{d['short_title']} เป็นเอกสารจำลองเพื่อการสาธิต (ไม่ใช่นโยบายจริง)")
    return notes
