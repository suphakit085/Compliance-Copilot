"""REST API. All authorisation decisions live here and in the retrieval SQL - the UI is
an untrusted client."""

from __future__ import annotations

import json
import logging
import threading
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text

from .. import __version__, audit, governance, history, llm, sso
from ..config import ROOT, get_settings
from ..db import AuditLog, Chunk, Document, Feedback, as_reader, engine, init_db, session
from ..features import gap_analysis
from ..generation.answerer import ChatResponse, answer_question, stream_answer
from ..guardrails.pii import mask_pii
from ..ingestion.updates import read_lock
from ..ratelimit import limiter
from ..retrieval import models
from ..retrieval.retriever import UserContext
from ..security import (
    ROLES_AUDIT,
    ROLES_GAP,
    LoginLocked,
    authenticate,
    check_production_ready,
    issue_token,
    user_from_token,
)

_bearer = HTTPBearer(auto_error=False)
_models_ready = threading.Event()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    check_production_ready()
    history.purge_expired()

    def warm() -> None:  # load embedding + reranker models in the background
        models.embed_query("warm up")
        models.rerank("warm up", ["warm up"])
        _models_ready.set()

    threading.Thread(target=warm, daemon=True).start()
    yield


app = FastAPI(
    title="Compliance Copilot API",
    version=__version__,
    description="Grounded, permission-aware Q&A over Thai banking & securities regulation.",
    lifespan=lifespan,
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cache-Control", "no-store")  # answers and documents are per-user data
    if get_settings().env == "production":
        response.headers.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
    return response


if hosts := [h.strip() for h in get_settings().allowed_hosts.split(",") if h.strip()]:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)


def _too_many(scope: str, retry_after: float, user: UserContext | None = None, first: bool = False) -> HTTPException:
    if first:  # one audit record per violation window, so an attacker cannot flood the audit chain
        audit.log_event("rate_limited", {"scope": scope}, user)
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS, "ส่งคำขอถี่เกินไป กรุณารอสักครู่แล้วลองใหม่",
        headers={"Retry-After": str(int(retry_after))},
    )


def client_address(request: Request) -> str:
    if get_settings().trust_proxy and (fwd := request.headers.get("x-forwarded-for")):
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def current_user(
    cred: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> UserContext:
    user = user_from_token(cred.credentials) if cred else None
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token")
    retry, first = limiter.hit(f"user:{user.id}", get_settings().rate_user_per_min, 60)
    if retry:
        raise _too_many("user", retry, user, first)
    return user


def limited(scope: str, limit_attr: str, window_s: float):
    """Stricter per-user limit for expensive endpoints (each call spends LLM quota)."""

    def dep(user: Annotated[UserContext, Depends(current_user)]) -> UserContext:
        retry, first = limiter.hit(f"{scope}:{user.id}", getattr(get_settings(), limit_attr), window_s)
        if retry:
            raise _too_many(scope, retry, user, first)
        return user

    return dep


def require(roles: set[str]):
    def dep(user: Annotated[UserContext, Depends(current_user)]) -> UserContext:
        if user.role not in roles:
            audit.log_event("access_denied", {"required": sorted(roles)}, user)
            raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient role")
        return user

    return dep


# ----------------------------------------------------------------------------- auth


class LoginIn(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: int | None
    username: str
    display_name: str
    role: str
    department: str
    clearance: int


class LoginOut(BaseModel):
    access_token: str
    user: UserOut


def _user_out(u: UserContext) -> UserOut:
    return UserOut(id=u.id, username=u.username, display_name=u.display_name, role=u.role,
                   department=u.department, clearance=u.clearance)


@app.post("/auth/login", response_model=LoginOut, tags=["auth"])
def login(body: LoginIn, request: Request) -> LoginOut:
    s = get_settings()
    if not s.password_login:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "password login is disabled; use SSO")
    retry, first = limiter.hit(f"login-ip:{client_address(request)}", s.rate_login_ip_per_min, 60)
    if retry:
        raise _too_many("login-ip", retry, None, first)
    try:
        user = authenticate(body.username, body.password)
    except LoginLocked as e:
        if e.newly_locked:
            audit.log_event("account_locked", {"username": e.username, "minutes": s.login_lock_minutes})
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"พยายามเข้าสู่ระบบผิดหลายครั้ง กรุณาลองใหม่ในอีก {max(int(e.retry_after // 60), 1)} นาที",
            headers={"Retry-After": str(int(e.retry_after))},
        ) from e
    if not user:
        audit.log_event("login_failed", {"username": body.username})
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    audit.log_event("login", {}, user)
    return LoginOut(access_token=issue_token(user), user=_user_out(user))


class SSOConfig(BaseModel):
    enabled: bool
    label: str = ""


class SSOStart(BaseModel):
    url: str
    state_token: str


class SSOCallback(BaseModel):
    code: str
    state: str
    state_token: str


@app.get("/auth/sso/config", response_model=SSOConfig, tags=["auth"])
def sso_config() -> SSOConfig:
    return SSOConfig(enabled=sso.enabled(), label=get_settings().oidc_label)


@app.get("/auth/sso/start", response_model=SSOStart, tags=["auth"])
def sso_start() -> SSOStart:
    if not sso.enabled():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "SSO is not configured")
    try:
        url, token = sso.begin()
    except sso.SSOError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
    return SSOStart(url=url, state_token=token)


@app.post("/auth/sso/callback", response_model=LoginOut, tags=["auth"])
def sso_callback(body: SSOCallback) -> LoginOut:
    if not sso.enabled():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "SSO is not configured")
    try:
        user = sso.complete(body.code, body.state, body.state_token)
    except sso.SSOError as e:
        audit.log_event("login_failed", {"method": "sso", "reason": str(e)})
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(e)) from e
    audit.log_event("login", {"method": "sso"}, user)
    return LoginOut(access_token=issue_token(user), user=_user_out(user))


@app.get("/me", response_model=UserOut, tags=["auth"])
def me(user: Annotated[UserContext, Depends(current_user)]) -> UserOut:
    return _user_out(user)


# ----------------------------------------------------------------------------- chat


class Turn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(max_length=8000)


class ChatIn(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    history: list[Turn] = []  # used only when there is no saved conversation
    as_of: date | None = None
    conversation_id: str | None = None


def _turns(user: UserContext, body: ChatIn) -> list[dict[str, str]]:
    """Follow-up context: from the server-side record when history is on, never trusted from the client."""
    if not history.enabled():
        return [t.model_dump() for t in body.history[-6:]]
    return history.recent_turns(user, body.conversation_id) if body.conversation_id else []


def _remember(user: UserContext, body: ChatIn, resp: ChatResponse) -> None:
    if history.enabled():
        masked = mask_pii(body.question).text
        conv_id = history.get_or_create(user, body.conversation_id, masked)
        history.append(conv_id, masked, resp.model_dump(mode="json"))
        resp.conversation_id = conv_id


@app.post("/chat", response_model=ChatResponse, tags=["chat"])
def chat(body: ChatIn, user: Annotated[UserContext, Depends(limited("chat", "rate_chat_per_min", 60))]) -> ChatResponse:
    resp = answer_question(body.question, user, _turns(user, body), body.as_of)
    _remember(user, body, resp)
    return resp


@app.post("/chat/stream", tags=["chat"])
def chat_stream(
    body: ChatIn, user: Annotated[UserContext, Depends(limited("chat", "rate_chat_per_min", 60))]
) -> StreamingResponse:
    """Same answer as /chat, delivered as newline-delimited JSON events.

    ``stage`` and ``sources`` show real progress; ``delta`` is the answer text as it is
    written and is an *unverified draft*; the ``final`` event carries the verified response
    (citations checked against the source text) and replaces the draft.
    """
    turns = _turns(user, body)

    def events():
        try:
            for ev in stream_answer(body.question, user, turns, body.as_of):
                if ev["type"] == "final":
                    _remember(user, body, ev["response"])
                    ev = {"type": "final", "response": ev["response"].model_dump(mode="json")}
                yield json.dumps(ev, ensure_ascii=False, default=str) + "\n"
        except Exception:  # headers are already sent: report in-band, never leak details
            logging.getLogger(__name__).exception("chat stream failed")
            yield json.dumps({"type": "error", "message": "เกิดข้อผิดพลาดภายในระบบ กรุณาลองใหม่"}) + "\n"

    return StreamingResponse(
        events(), media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},  # no proxy buffering
    )


# ------------------------------------------------------------------------ history


@app.get("/conversations", tags=["history"])
def conversations(user: Annotated[UserContext, Depends(current_user)]) -> list[dict[str, Any]]:
    return history.list_for(user)


@app.get("/conversations/{conversation_id}", tags=["history"])
def conversation(conversation_id: str, user: Annotated[UserContext, Depends(current_user)]) -> dict[str, Any]:
    data = history.load(user, conversation_id)
    if data is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
    return data


class RenameIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)


@app.post("/conversations/{conversation_id}/rename", tags=["history"])
def rename_conversation(conversation_id: str, body: RenameIn,
                        user: Annotated[UserContext, Depends(current_user)]) -> dict[str, bool]:
    if not history.rename(user, conversation_id, body.title):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
    return {"ok": True}


@app.post("/conversations/{conversation_id}/delete", tags=["history"])
def delete_conversation(conversation_id: str,
                        user: Annotated[UserContext, Depends(current_user)]) -> dict[str, bool]:
    if not history.remove(user, conversation_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
    # The deletion itself is audited; the audit trail keeps its own masked records.
    audit.log_event("conversation_deleted", {"conversation_id": conversation_id}, user)
    return {"ok": True}


class FeedbackIn(BaseModel):
    audit_id: int
    rating: int = Field(ge=-1, le=1)
    comment: str | None = Field(default=None, max_length=1000)


@app.post("/feedback", tags=["chat"])
def feedback(body: FeedbackIn, user: Annotated[UserContext, Depends(current_user)]) -> dict:
    with session() as db:
        row = db.get(AuditLog, body.audit_id)
        if not row or row.user_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "answer not found")
        db.add(Feedback(audit_id=body.audit_id, user_id=user.id, rating=body.rating, comment=body.comment))
    return {"ok": True}


# ------------------------------------------------------------------------ documents


def _visible(user: UserContext):
    return (Document.classification_level <= user.clearance) & (
        (func.jsonb_array_length(Document.departments) == 0)
        | Document.departments.op("?")(user.department)
    )


def _review(d: Document, today: date) -> dict[str, Any]:
    if d.source_kind != "internal" or not d.governance:
        return {}
    r = governance.review_state({**d.governance, "effective_to": d.effective_to}, today)  # expired = no review
    return {"review_state": r.state, "review_days_left": r.days_left}


@app.get("/documents", tags=["documents"])
def documents(user: Annotated[UserContext, Depends(current_user)]) -> list[dict[str, Any]]:
    with session() as db:
        as_reader(db.connection(), user)
        rows = db.execute(
            select(Document, func.count(Chunk.id))
            .join(Chunk, (Chunk.document_id == Document.id) & (Chunk.strategy == "structured"), isouter=True)
            .where(_visible(user)).group_by(Document.id)
            .order_by(Document.source_kind.desc(), Document.id)
        ).all()
        today = date.today()
        lock = read_lock()
        return [
            {
                "governance": {**(d.governance or {}), **_review(d, today)},
                "source_checked_at": (lock.get(d.id) or {}).get("checked_at")
                or (lock.get(d.id) or {}).get("retrieved_at"),
                "id": d.id, "title": d.title, "short_title": d.short_title, "doc_type": d.doc_type,
                "source_kind": d.source_kind, "issuer": d.issuer, "classification": d.classification,
                "version": d.version, "effective_from": d.effective_from, "effective_to": d.effective_to,
                "in_force": (d.effective_from is None or d.effective_from <= today)
                and (d.effective_to is None or d.effective_to > today),
                "supersedes": d.supersedes, "superseded_by": d.superseded_by,
                "amended_by": d.amended_by, "official_ref": d.official_ref,
                "official_url": d.official_url, "source_url": d.source_url,
                "source_name": d.source_name, "sha256": d.sha256, "synthetic": d.synthetic,
                "pages": d.page_count, "chunks": n, "quality": d.quality,
            }
            for d, n in rows
        ]


@app.get("/documents/{doc_id}/sections", tags=["documents"])
def sections(doc_id: str, user: Annotated[UserContext, Depends(current_user)]) -> list[dict[str, Any]]:
    with session() as db:
        as_reader(db.connection(), user)
        doc = db.execute(select(Document).where(Document.id == doc_id, _visible(user))).scalar_one_or_none()
        if not doc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
        rows = db.execute(
            select(Chunk).where(Chunk.document_id == doc_id, Chunk.strategy == "structured")
            .order_by(Chunk.ordinal)
        ).scalars()
        return [
            {"id": c.id, "label": c.label, "path": c.path, "title": c.title, "text": c.text,
             "pages": [c.page_start, c.page_end], "notes": c.notes, "extraction": c.extraction}
            for c in rows
        ]


# ---------------------------------------------------------------------- gap analysis


class GapIn(BaseModel):
    policy_id: str
    as_of: date | None = None


@app.post("/gap-analysis", response_model=gap_analysis.GapReport, tags=["gap analysis"])
def run_gap(
    body: GapIn,
    user: Annotated[UserContext, Depends(require(ROLES_GAP))],
    _: Annotated[UserContext, Depends(limited("gap", "rate_gap_per_10min", 600))],
) -> gap_analysis.GapReport:
    if not llm.available():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "LLM is not configured")
    try:
        return gap_analysis.analyze_policy(body.policy_id, user, body.as_of)
    except PermissionError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


@app.post("/gap-analysis/markdown", response_class=PlainTextResponse, tags=["gap analysis"])
def gap_markdown(report: gap_analysis.GapReport, user: Annotated[UserContext, Depends(require(ROLES_GAP))]) -> str:
    return gap_analysis.report_markdown(report)


# --------------------------------------------------------------------------- audit


@app.get("/audit", tags=["audit"])
def audit_list(
    user: Annotated[UserContext, Depends(require(ROLES_AUDIT))],
    limit: int = Query(50, le=500),
    event: str | None = None,
) -> list[dict[str, Any]]:
    with session() as db:
        q = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
        if event:
            q = q.where(AuditLog.event == event)
        rows = db.execute(q).scalars().all()
        fb = {
            a: r for a, r in db.execute(
                select(Feedback.audit_id, func.sum(Feedback.rating)).group_by(Feedback.audit_id)
            ).all()
        }
        return [
            {"id": r.id, "ts": r.ts, "username": r.username, "role": r.role, "event": r.event,
             "payload": r.payload, "hash": r.hash, "prev_hash": r.prev_hash, "feedback": fb.get(r.id)}
            for r in rows
        ]


@app.get("/audit/verify", tags=["audit"])
def audit_verify(user: Annotated[UserContext, Depends(require(ROLES_AUDIT))]) -> dict[str, Any]:
    return audit.verify_chain()


# ----------------------------------------------------------------------- operations


@app.get("/health", tags=["ops"])
def health() -> dict[str, Any]:
    db_ok = True
    try:
        with engine().connect() as c:
            c.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    s = get_settings()
    return {
        "status": "ok" if db_ok else "degraded", "version": __version__, "database": db_ok,
        "models_ready": _models_ready.is_set(), "llm_configured": llm.available(),
        "llm_provider": s.llm_provider, "llm_model": s.gemini_model if s.llm_provider == "gemini" else s.anthropic_model,
    }


@app.get("/eval/latest", tags=["ops"])
def eval_latest(user: Annotated[UserContext, Depends(current_user)]) -> dict[str, Any]:
    f = ROOT / "eval" / "results" / "latest.json"
    if not f.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no eval results yet - run `copilot eval`")
    return json.loads(Path(f).read_text(encoding="utf-8"))
