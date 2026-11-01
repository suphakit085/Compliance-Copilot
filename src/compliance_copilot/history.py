"""Per-user chat history.

Design rules (see docs/architecture.md):
* Questions are stored PII-masked - history must not become a store of customer data.
* Only the owner can list, open, rename or delete a conversation; others get 404.
* Permissions are re-checked when history is opened: a source the user can no longer
  access is removed, and an answer that cited it is withheld.
* History is never used as a knowledge source - only the last turns are passed to the
  question-rewriting step so follow-ups make sense.
* Conversations older than the retention period are purged.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select

from .config import get_settings
from .db import Conversation, ConversationMessage, Document, session
from .retrieval.retriever import UserContext

WITHHELD = (
    "คำตอบนี้ถูกซ่อน เนื่องจากอ้างอิงเอกสารที่คุณไม่มีสิทธิ์เข้าถึงแล้วในขณะนี้ "
    "หากต้องการข้อมูล กรุณาติดต่อฝ่ายกำกับการปฏิบัติงาน"
)


def enabled() -> bool:
    return get_settings().chat_retention_days > 0


def _title(question: str) -> str:
    q = " ".join(question.split())
    return q if len(q) <= 60 else q[:57] + "…"


def get_or_create(user: UserContext, conversation_id: str | None, first_question: str) -> str:
    with session() as db:
        if conversation_id:
            conv = db.get(Conversation, conversation_id)
            if conv and conv.user_id == user.id:
                return conv.id
        conv = Conversation(id=str(uuid.uuid4()), user_id=user.id, title=_title(first_question))
        db.add(conv)
        return conv.id


def recent_turns(user: UserContext, conversation_id: str, limit: int = 6) -> list[dict[str, str]]:
    with session() as db:
        conv = db.get(Conversation, conversation_id)
        if not conv or conv.user_id != user.id:
            return []
        rows = db.execute(
            select(ConversationMessage).where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.id.desc()).limit(limit)
        ).scalars().all()
        return [{"role": m.role, "content": m.content} for m in reversed(rows)]


def append(conversation_id: str, question_masked: str, response: dict[str, Any]) -> None:
    with session() as db:
        db.add(ConversationMessage(conversation_id=conversation_id, role="user", content=question_masked))
        db.add(ConversationMessage(
            conversation_id=conversation_id, role="assistant", content=response["answer"], response=response,
        ))
        conv = db.get(Conversation, conversation_id)
        if conv:
            conv.updated_at = datetime.now(UTC)


def list_for(user: UserContext, limit: int = 100) -> list[dict[str, Any]]:
    with session() as db:
        counts = (
            select(ConversationMessage.conversation_id, func.count().label("n"))
            .group_by(ConversationMessage.conversation_id).subquery()
        )
        rows = db.execute(
            select(Conversation, counts.c.n)
            .join(counts, counts.c.conversation_id == Conversation.id, isouter=True)
            .where(Conversation.user_id == user.id)
            .order_by(Conversation.updated_at.desc()).limit(limit)
        ).all()
        return [
            {"id": c.id, "title": c.title, "updated_at": c.updated_at, "messages": n or 0}
            for c, n in rows
        ]


def _allowed_docs(user: UserContext, doc_ids: set[str]) -> set[str]:
    if not doc_ids:
        return set()
    with session() as db:
        rows = db.execute(select(Document).where(Document.id.in_(doc_ids))).scalars()
        return {
            d.id for d in rows
            if d.classification_level <= user.clearance
            and (not d.departments or user.department in d.departments)
        }


def load(user: UserContext, conversation_id: str) -> dict[str, Any] | None:
    with session() as db:
        conv = db.get(Conversation, conversation_id)
        if not conv or conv.user_id != user.id:
            return None
        msgs = db.execute(
            select(ConversationMessage).where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.id)
        ).scalars().all()
        title, updated = conv.title, conv.updated_at

    doc_ids = {s["document_id"] for m in msgs if m.response for s in m.response.get("sources", [])}
    allowed = _allowed_docs(user, doc_ids)
    out = []
    for m in msgs:
        item: dict[str, Any] = {"role": m.role, "content": m.content}
        if m.response:
            resp = dict(m.response)
            sources = resp.get("sources", [])
            kept = [s for s in sources if s["document_id"] in allowed]
            lost_cited = any(s.get("cited") and s["document_id"] not in allowed for s in sources)
            if len(kept) != len(sources):
                resp["sources"] = kept
                resp["notices"] = [*resp.get("notices", []), "บางแหล่งอ้างอิงถูกซ่อนตามสิทธิ์การเข้าถึงปัจจุบันของคุณ"]
            if lost_cited:
                resp["answer"] = WITHHELD
                resp["follow_up_questions"] = []
                item["content"] = WITHHELD
            item["response"] = resp
        out.append(item)
    return {"id": conversation_id, "title": title, "updated_at": updated, "messages": out}


def rename(user: UserContext, conversation_id: str, title: str) -> bool:
    with session() as db:
        conv = db.get(Conversation, conversation_id)
        if not conv or conv.user_id != user.id:
            return False
        conv.title = _title(title)
        return True


def remove(user: UserContext, conversation_id: str) -> bool:
    with session() as db:
        conv = db.get(Conversation, conversation_id)
        if not conv or conv.user_id != user.id:
            return False
        db.delete(conv)
        return True


def purge_expired() -> int:
    days = get_settings().chat_retention_days
    if days <= 0:
        return 0
    cutoff = datetime.now(UTC) - timedelta(days=days)
    with session() as db:
        return db.execute(delete(Conversation).where(Conversation.updated_at < cutoff)).rowcount or 0
