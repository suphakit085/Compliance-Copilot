"""Watch the public sources for changes and onboard new internal policies safely.

``check_updates`` re-downloads each pinned source *in memory* and compares its SHA-256 with
the lock file. It never overwrites a stored PDF or touches the index: a changed document
must be reviewed by a person (``copilot fetch --force`` then ``copilot ingest``) because a
regulator's revision can change what an answer should say.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import yaml

from .. import governance
from ..config import get_settings
from . import http
from .chunker import structured_chunks
from .loaders import SourceSpec, _as_date, _split_front_matter, load_document

STALE_AFTER_DAYS = 90


@dataclass
class UpdateResult:
    doc_id: str
    status: str  # unchanged | changed | unreachable | not_pdf
    detail: str = ""


def lock_path() -> Path:
    return get_settings().raw_dir / "manifest.lock.json"


def read_lock() -> dict:
    p = lock_path()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def check_updates(
    log: Callable[[str], None] = print, client: httpx.Client | None = None, record: bool = True
) -> list[UpdateResult]:
    s = get_settings()
    lock = read_lock()
    manifest = yaml.safe_load((s.data_dir / "sources.yaml").read_text(encoding="utf-8"))
    own = client is None
    client = client or http.client()
    results: list[UpdateResult] = []
    try:
        for d in manifest["documents"]:
            entry = lock.get(d["id"], {})
            try:
                r = client.get(d["url"])
                r.raise_for_status()
            except httpx.HTTPError as e:
                results.append(UpdateResult(d["id"], "unreachable", str(e)[:120]))
                continue
            if not r.content.startswith(b"%PDF"):
                results.append(UpdateResult(d["id"], "not_pdf", r.headers.get("content-type", "")))
                continue
            sha = hashlib.sha256(r.content).hexdigest()
            if sha == entry.get("sha256"):
                results.append(UpdateResult(d["id"], "unchanged"))
                if record and d["id"] in lock:
                    lock[d["id"]]["checked_at"] = datetime.now(UTC).isoformat(timespec="seconds")
            else:
                results.append(UpdateResult(d["id"], "changed", f"{entry.get('sha256', '-')[:10]} -> {sha[:10]}"))
    finally:
        if own:
            client.close()
    if record:
        lock_path().write_text(json.dumps(lock, ensure_ascii=False, indent=2), encoding="utf-8")
    for r in results:
        log(f"{r.status:<11} {r.doc_id} {r.detail}")
    return results


def stale_sources(today: date | None = None) -> list[str]:
    """Pinned sources not verified against the publisher for STALE_AFTER_DAYS."""
    today = today or date.today()
    out = []
    for doc_id, e in read_lock().items():
        seen = e.get("checked_at") or e.get("retrieved_at")
        if not seen or (today - datetime.fromisoformat(seen).date()).days > STALE_AFTER_DAYS:
            out.append(doc_id)
    return out


def add_policy(path: Path, replace: bool = False, dry_run: bool = False,
               log: Callable[[str], None] = print) -> str:
    """Validate a policy markdown file against the governance rules and add it to the corpus."""
    s = get_settings()
    front, _ = _split_front_matter(path.read_text(encoding="utf-8"))
    issues = governance.problems(front)
    if issues:
        raise governance.GovernanceError(f"{path.name} cannot be added:\n  - " + "\n  - ".join(issues))
    doc_id = front["id"]
    if path.stem != doc_id:
        raise governance.GovernanceError(f"file name must be {doc_id}.md (it is {path.name})")
    dest = s.data_dir / "internal" / f"{doc_id}.md"
    if dest.exists() and dest.resolve() != path.resolve() and not replace:
        raise governance.GovernanceError(
            f"{doc_id} already exists. A new version of a policy gets a new id with 'supersedes: {doc_id}'; "
            "use --replace only to correct the same version."
        )
    meta = {**front}
    for k in ("published_on", "effective_from", "effective_to"):
        meta[k] = _as_date(meta.get(k))
    spec = SourceSpec(doc_id, front["title"], front["short_title"], front["doc_type"], "internal", path, meta)
    chunks = [c for c in structured_chunks(spec, load_document(spec), s.chunk_max_chars)]
    labels = [c.label for c in chunks]
    log(f"{doc_id}: {len(chunks)} citable units - {', '.join(labels[:8])}{' ...' if len(labels) > 8 else ''}")
    if not chunks:
        raise governance.GovernanceError("no numbered clauses (ข้อ N) were found - check the document format")
    # every "ข้อ N" paragraph in the file should become a citable unit; very short or
    # out-of-sequence ones are dropped by the parser, which would make them uncitable
    body = re.sub(r"<!--.*?-->", "", _split_front_matter(path.read_text(encoding="utf-8"))[1], flags=re.S)
    written = re.findall(r"^\s*ข้อ\s+(\d+(?:/\d+)?)\b", body, flags=re.M)
    indexed = {m.group(1) for lab in labels if (m := re.match(r"ข้อ\s+(\d+(?:/\d+)?)", lab))}
    if missing := [n for n in written if n not in indexed]:
        log(f"WARNING clauses not indexed (too short, duplicated or out of sequence): ข้อ {', '.join(missing)}")
    if dry_run:
        log("dry run: nothing copied or indexed")
        return doc_id
    if dest.resolve() != path.resolve():
        shutil.copyfile(path, dest)
    from .pipeline import ingest

    ingest(doc_ids=[doc_id], log=log)
    return doc_id
