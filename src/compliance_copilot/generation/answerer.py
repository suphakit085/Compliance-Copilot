"""Question -> guarded, grounded, audited answer.

    screen injection ─ mask PII ─ condense follow-up ─ retrieve (ACL + as-of)
        ─ abstain if evidence weak ─ generate with quotes ─ verify quotes ─ audit log

Failure modes degrade safely: no LLM key or an LLM error returns the best source
passages (retrieval-only mode) instead of an unsupported answer.
"""

from __future__ import annotations

import time
from collections.abc import Generator
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel

from .. import audit, llm, observability
from ..config import get_settings
from ..guardrails import input_guard
from ..guardrails.pii import mask_pii
from ..retrieval.retriever import Candidate, RetrievalResult, UserContext, retrieve
from . import prompts
from .citations import ground
from .streaming import AnswerStream

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
    """Blocking form: runs the event stream to the end and returns the final response."""
    final: ChatResponse | None = None
    for ev in stream_answer(question, user, history, as_of, log=log,
                            retrieval_overrides=retrieval_overrides, llm_purpose=llm_purpose, stream=False):
        if ev["type"] == "final":
            final = ev["response"]
    assert final is not None
    return final


def _generate(
    standalone: str, sources: list[SourceOut], notices: list[str], as_of: str, purpose: str,
    stream: bool, delivered: list[str],
) -> Generator[dict[str, Any], None, tuple[prompts.GroundedAnswer, llm.Usage]]:
    """Run the answer model. With ``stream`` the answer text is emitted as ``delta`` events
    while it is written (an *unverified draft*); the caller replaces it with the verified
    answer. Returns the parsed model output and token usage."""
    s = get_settings()
    provider = llm.get_provider(purpose)
    prompt = prompts.answer_prompt(standalone, _prompt_sources(sources), notices, as_of)
    if not stream:
        return provider.generate_json(prompts.ANSWER_SYSTEM, prompt, prompts.GroundedAnswer, effort=s.answer_effort)
    extractor, parts, usage = AnswerStream(), [], llm.Usage(model="")
    for item in llm.stream_json(provider, prompts.ANSWER_SYSTEM, prompt, prompts.GroundedAnswer, s.answer_effort):
        if isinstance(item, llm.Usage):
            usage = item
            continue
        if isinstance(item, llm.StreamReset):  # the provider restarted: forget the partial draft
            parts.clear()
            observability.STREAM_RESETS.inc()
            extractor = AnswerStream()
            delivered.append("\n[--- stream restarted ---]\n")
            yield {"type": "reset"}
            continue
        parts.append(item)
        if piece := extractor.feed(item):
            delivered.append(piece)
            yield {"type": "delta", "text": piece}
    try:
        return prompts.GroundedAnswer.model_validate_json("".join(parts)), usage
    except ValueError as e:
        raise llm.LLMError(f"Model returned invalid JSON for GroundedAnswer: {e}") from e


def stream_answer(
    question: str,
    user: UserContext,
    history: list[dict[str, str]] | None = None,
    as_of: date | None = None,
    *,
    log: bool = True,
    retrieval_overrides: dict[str, Any] | None = None,
    llm_purpose: str = "chat",
    stream: bool = True,
) -> Generator[dict[str, Any], None, None]:
    """The answer pipeline as a stream of events:

    ``stage`` (guard | condense | retrieve | generate | verify), ``sources`` (retrieved, already
    permission-filtered), ``delta`` (draft answer text, unverified) and finally ``final`` with
    the verified ChatResponse. Only the final response is trustworthy; deltas are a preview.
    """
    s = get_settings()
    started = time.perf_counter()
    as_of = as_of or date.today()
    trace: dict[str, Any] = {}
    stream = stream and llm_purpose == "chat"

    # 1. Guardrails on raw input
    yield {"type": "stage", "stage": "guard"}
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
        observability.record_chat(resp, time.perf_counter() - started)
        yield {"type": "final", "response": resp}
        return

    # 2. Follow-up questions are rewritten into standalone ones (on masked text only)
    standalone = q
    usage_total = llm.Usage(model="")
    if history and llm.available():
        yield {"type": "stage", "stage": "condense"}
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
    yield {"type": "stage", "stage": "retrieve"}
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
        yield {"type": "final", "response": _finish(resp, q, retrieval, None, started, user, log)}
        return

    # The passages are already permission-filtered, so they can be shown while the answer is written.
    yield {"type": "sources", "sources": [src.model_dump() for src in sources], "notices": retrieval.notices}

    # 5. Generation
    if not llm.available():
        resp = ChatResponse(
            status="retrieval_only",
            answer=_retrieval_only_answer(sources, "ระบบอยู่ในโหมดค้นคืนเท่านั้น (ยังไม่ได้ตั้งค่า LLM)"),
            **base, trace=trace,
        )
        yield {"type": "final", "response": _finish(resp, q, retrieval, None, started, user, log)}
        return

    yield {"type": "stage", "stage": "generate"}
    delivered: list[str] = []
    try:
        gen, u = yield from _generate(standalone, sources, retrieval.notices, as_of.isoformat(),
                                      llm_purpose, stream, delivered)
        usage_total = _add(usage_total, u)
    except GeneratorExit:
        # The reader went away mid-answer. Text it already received must not be unaccounted for.
        if delivered:
            observability.INTERRUPTED.inc()
        if log and delivered:
            audit.log_event("chat_interrupted", {
                "question_masked": q, "standalone_question": standalone, "as_of": as_of.isoformat(),
                "draft_delivered_unverified": "".join(delivered),
                "retrieved": [x.chunk_id for x in sources],
            }, user)
        raise
    except llm.QuotaExceeded:
        if llm_purpose == "batch":
            raise
        resp = ChatResponse(
            status="retrieval_only",
            answer=_retrieval_only_answer(sources, "โควตา LLM ของวันนี้หมดแล้ว ระบบจึงแสดงเฉพาะข้อความต้นฉบับ"),
            **base, trace={**trace, "llm_error": "quota exceeded"},
        )
        yield {"type": "final", "response": _finish(resp, q, retrieval, None, started, user, log)}
        return
    except llm.LLMError as e:
        resp = ChatResponse(
            status="retrieval_only",
            answer=_retrieval_only_answer(sources, "ไม่สามารถสร้างคำตอบได้ในขณะนี้"),
            **base, trace={**trace, "llm_error": str(e)},
        )
        yield {"type": "final", "response": _finish(resp, q, retrieval, None, started, user, log)}
        return

    # 6. Verify every quote against the source text
    yield {"type": "stage", "stage": "verify"}
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
    yield {"type": "final", "response": _finish(resp, q, retrieval, usage_total, started, user, log)}


def _add(a: llm.Usage, b: llm.Usage) -> llm.Usage:
    return llm.Usage(b.model or a.model, a.input_tokens + b.input_tokens,
                     a.output_tokens + b.output_tokens, a.latency_ms + b.latency_ms)


def _finish(resp: ChatResponse, q: str, retrieval: RetrievalResult | None, usage: llm.Usage | None,
            started: float, user: UserContext, log: bool) -> ChatResponse:
    latency = int((time.perf_counter() - started) * 1000)
    resp.trace["latency_ms"] = latency
    observability.record_chat(resp, latency / 1000)
    if log:
        resp.audit_id = audit.log_event("chat", _audit_payload(resp, q, retrieval, usage, latency), user)
    return resp
