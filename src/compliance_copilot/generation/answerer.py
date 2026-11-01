"""Question -> guarded, grounded, audited answer.

    screen injection ─ mask PII ─ condense follow-up ─ retrieve (ACL + as-of)
        ─ abstain if evidence weak ─ generate with quotes ─ verify quotes ─ audit log

Failure modes degrade safely: no LLM key or an LLM error returns the best source
passages (retrieval-only mode) instead of an unsupported answer.
"""

from __future__ import annotations

import time
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel

from .. import audit, llm
from ..config import get_settings
from ..guardrails import input_guard
from ..guardrails.pii import mask_pii
from ..retrieval.retriever import Candidate, RetrievalResult, UserContext, retrieve
from . import prompts
from .citations import ground

Status = Literal[
    "answered", "partial", "insufficient_evidence", "out_of_scope", "blocked",
    "retrieval_only", "unverified",
]


class SourceOut(BaseModel):
    id: str
    chunk_id: str
    document_id: str
    doc_title: str
    short_title: str
    label: str
    path: list[str]
    text: str
    page_start: int | None
    page_end: int | None
    version: str | None
    effective_from: str | None
    effective_to: str | None
    classification: str
    source_kind: str
    official_url: str | None
    source_url: str | None
    synthetic: bool
    extraction: str
    notes: list[str]
    rerank_score: float | None
    cited: bool = False
    quotes: list[str] = []


class ChatResponse(BaseModel):
    status: Status
    answer: str
    sources: list[SourceOut]
    notices: list[str]
    follow_up_questions: list[str] = []
    standalone_question: str
    as_of: str
    audit_id: int | None = None
    conversation_id: str | None = None
    pii_masked: dict[str, int] = {}
    guard_flags: list[str] = []
    grounding: dict[str, Any] = {}
    trace: dict[str, Any] = {}


NO_EVIDENCE = (
    "ไม่พบข้อมูลที่เพียงพอในเอกสารที่คุณมีสิทธิ์เข้าถึงเพื่อตอบคำถามนี้ "
    "กรุณาปรับคำถามให้เฉพาะเจาะจงขึ้น (เช่น ระบุชื่อกฎหมายหรือหัวข้อ) "
    "หรือติดต่อฝ่ายกำกับการปฏิบัติงาน (Compliance) เพื่อขอคำแนะนำ"
)


def _source_out(i: int, c: Candidate) -> SourceOut:
    d = c.doc
    return SourceOut(
        id=f"S{i}", chunk_id=c.chunk_id, document_id=c.document_id, doc_title=d["title"],
        short_title=d["short_title"], label=c.label, path=c.path, text=c.text,
        page_start=c.page_start, page_end=c.page_end, version=d.get("version"),
        effective_from=d.get("effective_from"), effective_to=d.get("effective_to"),
        classification=d["classification"], source_kind=d["source_kind"],
        official_url=d.get("official_url"), source_url=d.get("source_url"),
        synthetic=bool(d.get("synthetic")), extraction=c.extraction, notes=c.notes,
        rerank_score=round(c.rerank_score, 4) if c.rerank_score is not None else None,
    )


def _prompt_sources(sources: list[SourceOut]) -> list[dict]:
    out = []
    for s in sources:
        eff = s.effective_from or ""
        if s.effective_to:
            eff += f" ถึง {s.effective_to}"
        kind = "นโยบาย/คู่มือภายในบริษัท" if s.source_kind == "internal" else "กฎหมาย/ประกาศของหน่วยงานกำกับ"
        out.append({
            "id": s.id, "doc_title": s.doc_title, "location": " > ".join([*s.path, s.label]),
            "version": s.version, "effective": eff, "kind": kind, "notes": s.notes, "text": s.text,
        })
    return out


def _retrieval_only_answer(sources: list[SourceOut], reason: str) -> str:
    lines = [f"{reason} ข้อความที่เกี่ยวข้องที่สุดจากเอกสารต้นทาง:"]
    for s in sources[:3]:
        snippet = s.text if len(s.text) < 400 else s.text[:400] + "…"
        lines.append(f"\n**{s.short_title} – {s.label}** [{s.id}]\n> {snippet}")
    return "\n".join(lines)


def _audit_payload(resp: ChatResponse, question_masked: str, retrieval: RetrievalResult | None,
                   usage: llm.Usage | None, latency_ms: int) -> dict[str, Any]:
    return {
        "question_masked": question_masked,
        "standalone_question": resp.standalone_question,
        "as_of": resp.as_of,
        "status": resp.status,
        "answer": resp.answer,
        "retrieved": [
            {"chunk_id": s.chunk_id, "score": s.rerank_score, "cited": s.cited} for s in resp.sources
        ],
        "notices": resp.notices,
        "grounding": resp.grounding,
        "pii_masked": resp.pii_masked,
        "guard_flags": resp.guard_flags,
        "model": usage.model if usage else None,
        "tokens": {"in": usage.input_tokens, "out": usage.output_tokens} if usage else None,
        "prompt_version": prompts.ANSWER_PROMPT_VERSION,
        "retrieval_timings_ms": retrieval.timings_ms if retrieval else {},
        "latency_ms": latency_ms,
    }


def answer_question(
    question: str,
    user: UserContext,
    history: list[dict[str, str]] | None = None,
    as_of: date | None = None,
    *,
    log: bool = True,
    retrieval_overrides: dict[str, Any] | None = None,
    llm_purpose: str = "chat",
) -> ChatResponse:
    s = get_settings()
    started = time.perf_counter()
    as_of = as_of or date.today()
    trace: dict[str, Any] = {}

    # 1. Guardrails on raw input
    guard = input_guard.screen(question)
    masked = mask_pii(question) if s.pii_masking else mask_pii("")
    q = masked.text if s.pii_masking else question
    if guard.blocked:
        resp = ChatResponse(
            status="blocked", answer=input_guard.REFUSAL, sources=[], notices=[],
            standalone_question=q, as_of=as_of.isoformat(), pii_masked=dict(masked.found),
            guard_flags=guard.flags,
        )
        if log:
            resp.audit_id = audit.log_event("chat", _audit_payload(resp, q, None, None, 0), user)
        return resp

    # 2. Follow-up questions are rewritten into standalone ones (on masked text only)
    standalone = q
    usage_total = llm.Usage(model="")
    if history and llm.available():
        hist = "\n".join(
            f"{m['role']}: {mask_pii(m['content']).text[:1500]}" for m in history[-6:]
        )
        try:
            out, u = llm.get_provider(llm_purpose).generate_json(
                prompts.CONDENSE_SYSTEM, f"Conversation:\n{hist}\n\nLatest message: {q}",
                prompts.Standalone, effort=s.condense_effort,
            )
            standalone = out.question.strip() or q
            usage_total = _add(usage_total, u)
        except llm.LLMError as e:
            trace["condense_error"] = str(e)

    # 3. Retrieval (ACL + effective-date filtering happen inside the SQL)
    retrieval = retrieve(standalone, user, as_of, **(retrieval_overrides or {}))
    sources = [_source_out(i, c) for i, c in enumerate(retrieval.candidates, 1)]
    trace["retrieval"] = {"timings_ms": retrieval.timings_ms, "top_score": retrieval.top_score,
                          "terms": retrieval.terms,
                          "glossary_expansions": retrieval.expansions}
    base = dict(
        sources=sources, notices=retrieval.notices, standalone_question=standalone,
        as_of=as_of.isoformat(), pii_masked=dict(masked.found), guard_flags=guard.flags,
    )

    # 4. Abstain when the best evidence is weak - no LLM call, nothing to hallucinate from
    if retrieval.top_score < s.abstain_threshold:
        resp = ChatResponse(status="insufficient_evidence", answer=NO_EVIDENCE, **{**base, "sources": []},
                            trace={**trace, "abstained": True})
        return _finish(resp, q, retrieval, None, started, user, log)

    # 5. Generation
    if not llm.available():
        resp = ChatResponse(
            status="retrieval_only",
            answer=_retrieval_only_answer(sources, "ระบบอยู่ในโหมดค้นคืนเท่านั้น (ยังไม่ได้ตั้งค่า LLM)"),
            **base, trace=trace,
        )
        return _finish(resp, q, retrieval, None, started, user, log)

    prompt = prompts.answer_prompt(standalone, _prompt_sources(sources), retrieval.notices, as_of.isoformat())
    try:
        gen, u = llm.get_provider(llm_purpose).generate_json(
            prompts.ANSWER_SYSTEM, prompt, prompts.GroundedAnswer, effort=s.answer_effort
        )
        usage_total = _add(usage_total, u)
    except llm.QuotaExceeded:
        if llm_purpose == "batch":
            raise
        resp = ChatResponse(
            status="retrieval_only",
            answer=_retrieval_only_answer(sources, "โควตา LLM ของวันนี้หมดแล้ว ระบบจึงแสดงเฉพาะข้อความต้นฉบับ"),
            **base, trace={**trace, "llm_error": "quota exceeded"},
        )
        return _finish(resp, q, retrieval, None, started, user, log)
    except llm.LLMError as e:
        resp = ChatResponse(
            status="retrieval_only",
            answer=_retrieval_only_answer(sources, "ไม่สามารถสร้างคำตอบได้ในขณะนี้"),
            **base, trace={**trace, "llm_error": str(e)},
        )
        return _finish(resp, q, retrieval, None, started, user, log)

    # 6. Verify every quote against the source text
    report = ground(gen.answer, [(c.source_id, c.quote) for c in gen.citations],
                    {src.id: src.text for src in sources})
    for src in sources:
        src.quotes = [c.quote for c in report.citations if c.verified and c.source_id == src.id]
        src.cited = bool(src.quotes)
    status: Status = gen.status
    answer = report.answer
    if gen.status in ("answered", "partial") and not report.verified_sources:
        status = "unverified"
        answer = _retrieval_only_answer(
            sources, "ระบบไม่สามารถยืนยันแหล่งอ้างอิงของคำตอบที่สร้างขึ้นได้ จึงแสดงเฉพาะข้อความต้นฉบับ"
        )
    grounding = {
        "citations": len(report.citations),
        "verified": sum(c.verified for c in report.citations),
        "markers": report.markers_total,
        "markers_supported": report.markers_supported,
        "unsupported_markers": report.unsupported_markers,
        "invalid_sources": report.invalid_sources,
        "support_rate": round(report.support_rate, 3),
    }
    resp = ChatResponse(
        status=status, answer=answer, follow_up_questions=gen.follow_up_questions[:3],
        grounding=grounding, trace={**trace, "llm": usage_total.__dict__}, **base,
    )
    return _finish(resp, q, retrieval, usage_total, started, user, log)


def _add(a: llm.Usage, b: llm.Usage) -> llm.Usage:
    return llm.Usage(b.model or a.model, a.input_tokens + b.input_tokens,
                     a.output_tokens + b.output_tokens, a.latency_ms + b.latency_ms)


def _finish(resp: ChatResponse, q: str, retrieval: RetrievalResult | None, usage: llm.Usage | None,
            started: float, user: UserContext, log: bool) -> ChatResponse:
    latency = int((time.perf_counter() - started) * 1000)
    resp.trace["latency_ms"] = latency
    if log:
        resp.audit_id = audit.log_event("chat", _audit_payload(resp, q, retrieval, usage, latency), user)
    return resp
