"""Ingestion pipeline: source file -> repaired text -> structure -> chunks -> vectors -> Postgres.

Idempotent: a document is re-processed only when its file hash or the pipeline
version changes (or ``force=True``), so re-running after adding one policy is cheap.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import yaml
from sqlalchemy import delete

from .. import governance
from ..config import get_settings
from ..db import CLEARANCE, Chunk, Document, init_db, session
from ..retrieval import models
from ..retrieval.text_index import tokens_for_index
from .chunker import ChunkData, naive_chunks, structured_chunks
from .loaders import SourceSpec, load_document, load_manifest

PIPELINE_VERSION = "4"
_UA = "Mozilla/5.0 (compliance-copilot corpus fetcher; +https://github.com/)"


def fetch_sources(force: bool = False, log: Callable[[str], None] = print) -> None:
    """Download the public regulation PDFs listed in data/sources.yaml and pin their hashes."""
    s = get_settings()
    s.raw_dir.mkdir(parents=True, exist_ok=True)
    lock_path = s.raw_dir / "manifest.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8")) if lock_path.exists() else {}
    manifest = yaml.safe_load((s.data_dir / "sources.yaml").read_text(encoding="utf-8"))
    with httpx.Client(follow_redirects=True, timeout=120, headers={"User-Agent": _UA}) as client:
        for d in manifest["documents"]:
            target = s.raw_dir / f"{d['id']}.pdf"
            if target.exists() and not force:
                log(f"skip {d['id']} (already downloaded)")
            else:
                r = client.get(d["url"])
                r.raise_for_status()
                if not r.content.startswith(b"%PDF"):
                    raise RuntimeError(f"{d['id']}: response is not a PDF ({r.headers.get('content-type')})")
                target.write_bytes(r.content)
                log(f"downloaded {d['id']} ({len(r.content) / 1e6:.1f} MB)")
            sha = hashlib.sha256(target.read_bytes()).hexdigest()
            prev = lock.get(d["id"], {})
            if prev.get("sha256") and prev["sha256"] != sha:
                log(f"WARNING {d['id']}: content changed since last fetch - review before re-ingesting")
            lock[d["id"]] = {
                **prev,  # keep fields written by other tools (checked_at from check-updates)
                "url": d["url"],
                "sha256": sha,
                "bytes": target.stat().st_size,
                "retrieved_at": prev.get("retrieved_at") if prev.get("sha256") == sha
                else datetime.now(UTC).isoformat(timespec="seconds"),
            }
    lock_path.write_text(json.dumps(lock, ensure_ascii=False, indent=2), encoding="utf-8")


def _document_row(spec: SourceSpec, sha: str, page_count: int, quality: dict) -> Document:
    m = spec.meta
    classification = m.get("classification", "public")
    return Document(
        id=spec.id, title=spec.title, short_title=spec.short_title, doc_type=spec.doc_type,
        source_kind=spec.source_kind, issuer=m.get("issuer"),
        regulator=m.get("regulator") or m.get("owner"),
        classification=classification, classification_level=CLEARANCE[classification],
        departments=m.get("departments", []), topics=m.get("topics", []),
        sectors=m.get("sectors", []), aliases=m.get("aliases", []),
        version=str(m["version"]) if m.get("version") else None,
        published_on=m.get("published_on"), effective_from=m.get("effective_from"),
        effective_to=m.get("effective_to"), supersedes=m.get("supersedes"),
        superseded_by=m.get("superseded_by"),
        amended_by=[{**a, "effective_from": str(a.get("effective_from"))} for a in m.get("amended_by", [])],
        source_url=m.get("url"), source_name=m.get("source_name"),
        official_ref=m.get("official_ref") or m.get("consolidated_through"),
        official_url=m.get("official_url"), sha256=sha, synthetic=bool(m.get("synthetic")),
        page_count=page_count,
        governance=governance.to_record(m) if spec.source_kind == "internal" else {},
        quality={**quality, "pipeline": PIPELINE_VERSION,
                 "consolidated_through": m.get("consolidated_through")},
    )


def ingest(
    doc_ids: list[str] | None = None,
    force: bool = False,
    use_ocr: bool = True,
    log: Callable[[str], None] = print,
) -> dict[str, int]:
    init_db()
    s = get_settings()
    stats: dict[str, int] = {}
    specs = load_manifest()
    governance.validate(specs)  # every internal document needs an owner, an approver and a review date
    for spec in specs:
        if doc_ids and spec.id not in doc_ids:
            continue
        if spec.source_kind == "internal" and spec.meta.get("status") != "approved":
            with session() as db:  # drafts and retired documents must not be searchable
                if db.get(Document, spec.id):
                    db.delete(db.get(Document, spec.id))
                    log(f"removed {spec.id} from the index (status: {spec.meta.get('status')})")
                else:
                    log(f"skip {spec.id} (status: {spec.meta.get('status')} - not approved)")
            continue
        if not spec.path.exists():
            log(f"MISSING {spec.id}: {spec.path} (run `copilot fetch`)")
            continue
        sha = spec.sha256
        with session() as db:
            existing = db.get(Document, spec.id)
            if (
                existing and not force and existing.sha256 == sha
                and existing.quality.get("pipeline") == PIPELINE_VERSION
                and not (use_ocr and existing.quality.get("pages_without_text"))
            ):
                log(f"up to date: {spec.id}")
                continue

        loaded = load_document(spec, use_ocr=use_ocr)
        chunks: list[ChunkData] = structured_chunks(spec, loaded, s.chunk_max_chars)
        chunks += naive_chunks(spec, loaded)
        vectors = models.embed([c.embed_text for c in chunks], batch_size=16)

        with session() as db:
            db.execute(delete(Chunk).where(Chunk.document_id == spec.id))
            db.merge(_document_row(spec, sha, loaded.page_count, loaded.quality))
            db.flush()
            for c, v in zip(chunks, vectors, strict=True):
                db.add(
                    Chunk(
                        id=c.id, document_id=c.document_id, strategy=c.strategy, ordinal=c.ordinal,
                        label=c.label, path=c.path, title=c.title, text=c.text,
                        embed_text=c.embed_text,
                        tokens_text=tokens_for_index(f"{spec.short_title} {c.label} {c.title or ''} {c.text}"),
                        embedding=v, page_start=c.page_start, page_end=c.page_end, notes=c.notes,
                        extraction=c.extraction,
                    )
                )
        n_struct = sum(c.strategy == "structured" for c in chunks)
        stats[spec.id] = n_struct
        warn = f" | pages without text: {loaded.missing_pages}" if loaded.missing_pages else ""
        log(f"ingested {spec.id}: {n_struct} structured + {len(chunks) - n_struct} naive chunks"
            f" | OCR pages: {loaded.ocr_pages or '-'}{warn}")
    return stats
