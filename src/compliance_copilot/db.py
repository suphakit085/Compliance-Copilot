"""Database schema (PostgreSQL + pgvector).

One database holds the documents, their chunks and vectors, users, and the audit
trail. Keeping vectors next to relational metadata means the access-control and
effective-date filters are part of the *same SQL query* as the similarity search -
there is no second system whose filters could drift out of sync.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from functools import lru_cache

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Computed,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    create_engine,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from .config import get_settings

CLEARANCE = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}


class Base(DeclarativeBase):
    type_annotation_map = {dict: JSONB, list: JSONB}


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    short_title: Mapped[str] = mapped_column(Text)
    doc_type: Mapped[str] = mapped_column(String(40))  # act | notification | circular | policy ...
    source_kind: Mapped[str] = mapped_column(String(20))  # regulation | internal
    issuer: Mapped[str | None] = mapped_column(Text)
    regulator: Mapped[str | None] = mapped_column(Text)
    classification: Mapped[str] = mapped_column(String(20), default="public")
    classification_level: Mapped[int] = mapped_column(Integer, default=0)
    departments: Mapped[list] = mapped_column(JSONB, default=list)  # empty = all departments
    topics: Mapped[list] = mapped_column(JSONB, default=list)
    sectors: Mapped[list] = mapped_column(JSONB, default=list)
    aliases: Mapped[list] = mapped_column(JSONB, default=list)
    version: Mapped[str | None] = mapped_column(String(20))
    published_on: Mapped[date | None] = mapped_column(Date)
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    supersedes: Mapped[str | None] = mapped_column(String(80))
    superseded_by: Mapped[str | None] = mapped_column(String(80))
    amended_by: Mapped[list] = mapped_column(JSONB, default=list)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_name: Mapped[str | None] = mapped_column(Text)
    official_ref: Mapped[str | None] = mapped_column(Text)
    official_url: Mapped[str | None] = mapped_column(Text)
    sha256: Mapped[str | None] = mapped_column(String(64))
    synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    page_count: Mapped[int | None] = mapped_column(Integer)
    quality: Mapped[dict] = mapped_column(JSONB, default=dict)
    # internal documents: owner, approver, approval date, review due date, status
    governance: Mapped[dict] = mapped_column(JSONB, default=dict)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    strategy: Mapped[str] = mapped_column(String(20), index=True)  # structured | naive
    ordinal: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(Text)
    path: Mapped[list] = mapped_column(JSONB, default=list)
    title: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    embed_text: Mapped[str] = mapped_column(Text)
    tokens_text: Mapped[str] = mapped_column(Text)
    lexical = mapped_column(TSVECTOR, Computed("to_tsvector('simple', tokens_text)", persisted=True))
    embedding = mapped_column(Vector(get_settings().embedding_dim))
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[list] = mapped_column(JSONB, default=list)
    extraction: Mapped[str] = mapped_column(String(10), default="text")  # text | ocr | markdown

    __table_args__ = (
        Index("ix_chunks_lexical", "lexical", postgresql_using="gin"),
        Index(
            "ix_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(60), unique=True)
    display_name: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(30))  # employee | compliance_officer | auditor | admin
    department: Mapped[str] = mapped_column(String(40))
    clearance: Mapped[int] = mapped_column(Integer)
    password_hash: Mapped[str] = mapped_column(Text)  # "!" for SSO-only accounts
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # "<issuer>|<sub>" for users provisioned from the identity provider
    external_id: Mapped[str | None] = mapped_column(Text, unique=True, nullable=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    terms_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    terms_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    """Append-only, hash-chained record of every question, answer and admin action.

    Each row stores ``hash = sha256(prev_hash || canonical_json(row))`` so editing or
    deleting any historical row breaks the chain from that point on
    (``GET /audit/verify``).
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    user_id: Mapped[int | None] = mapped_column(Integer)
    username: Mapped[str | None] = mapped_column(String(60))
    role: Mapped[str | None] = mapped_column(String(30))
    event: Mapped[str] = mapped_column(String(30))  # chat | gap_analysis | login | ...
    payload: Mapped[dict] = mapped_column(JSONB)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    audit_id: Mapped[int] = mapped_column(ForeignKey("audit_log.id"))
    user_id: Mapped[int] = mapped_column(Integer)
    rating: Mapped[int] = mapped_column(Integer)  # +1 / -1
    comment: Mapped[str | None] = mapped_column(Text)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # problem reports (rating < 0): what kind, who is handling it, how it ended
    category: Mapped[str | None] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | resolved | dismissed
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(60))
    resolution: Mapped[str | None] = mapped_column(Text)


class Conversation(Base):
    """A user's own chat thread. Deliberately separate from the audit log: users may delete
    their history (PDPA rights), while the audit trail stays append-only for oversight."""

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(10))  # user | assistant
    content: Mapped[str] = mapped_column(Text)  # PII-masked question, or the answer text
    response: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # full ChatResponse
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    name: Mapped[str] = mapped_column(Text)
    config: Mapped[dict] = mapped_column(JSONB)
    metrics: Mapped[dict] = mapped_column(JSONB)
    score: Mapped[float | None] = mapped_column(Float)


@lru_cache
def engine():
    return create_engine(get_settings().database_url, pool_pre_ping=True, future=True)


@lru_cache
def _session_factory():
    return sessionmaker(engine(), expire_on_commit=False)


@contextmanager
def session() -> Iterator[Session]:
    s = _session_factory()()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


READER_ROLE = "copilot_reader"

# Second access-control layer, enforced by Postgres itself. Queries that read documents on
# behalf of a user switch to READER_ROLE for the transaction (``as_reader``); for that role
# only rows the user may see exist, so a query that forgets the ACL filter in its WHERE
# clause still cannot return restricted text. Unset settings deny everything.
# Ingestion, audit and admin tasks keep the owner role, which RLS does not apply to.
_RLS = f"""
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{READER_ROLE}') THEN
    CREATE ROLE {READER_ROLE} NOLOGIN;
  END IF;
END $$;
GRANT {READER_ROLE} TO CURRENT_USER;
GRANT USAGE ON SCHEMA public TO {READER_ROLE};
GRANT SELECT ON documents, chunks TO {READER_ROLE};
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE chunks ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS document_visibility ON documents;
CREATE POLICY document_visibility ON documents FOR SELECT TO {READER_ROLE} USING (
  classification_level <= coalesce(nullif(current_setting('app.clearance', true), ''), '-1')::int
  AND (jsonb_array_length(departments) = 0
       OR departments ? coalesce(current_setting('app.department', true), ''))
);
DROP POLICY IF EXISTS chunk_visibility ON chunks;
CREATE POLICY chunk_visibility ON chunks FOR SELECT TO {READER_ROLE} USING (
  EXISTS (SELECT 1 FROM documents d WHERE d.id = chunks.document_id)
);
"""


def as_reader(conn, user) -> None:
    """Run the rest of the current transaction as ``user`` under row-level security."""
    conn.execute(text(f"SET LOCAL ROLE {READER_ROLE}"))
    conn.execute(
        text("SELECT set_config('app.clearance', :c, true), set_config('app.department', :d, true)"),
        {"c": str(user.clearance), "d": user.department},
    )


def init_db() -> None:
    with engine().begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine())
    with engine().begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS external_id text UNIQUE"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS failed_logins integer NOT NULL DEFAULT 0"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS locked_until timestamptz"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS terms_version varchar(40)"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS terms_accepted_at timestamptz"))
        for ddl in (
            "category varchar(30)", "status varchar(20) NOT NULL DEFAULT 'open'", "resolved_at timestamptz",
            "resolved_by varchar(60)", "resolution text",
        ):
            conn.execute(text(f"ALTER TABLE feedback ADD COLUMN IF NOT EXISTS {ddl}"))
        conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS governance jsonb NOT NULL DEFAULT '{}'"))
        conn.execute(text(_RLS))


__all__ = [
    "JSON", "CLEARANCE", "AuditLog", "Base", "Chunk", "Conversation", "ConversationMessage",
    "Document", "EvalRun", "Feedback", "READER_ROLE", "User",
    "as_reader", "engine", "init_db", "session",
]
