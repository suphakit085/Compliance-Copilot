"""Document sources: the public regulation manifest and internal policy markdown files."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from ..config import get_settings
from .pdf_extract import ExtractedDocument, Line, extract_pdf, render_page_png
from .thai_text import normalize_text, repair_thai

_STRUCTURAL = re.compile(r"^(มาตรา|ข้อ|หมวด|ส่วนที่|เอกสารแนบ|ภาคผนวก|\(\d+\)|\([ก-ฮ]\)|\d{1,2}(\.\d{1,2})*\.?\s)")


@dataclass
class SourceSpec:
    id: str
    title: str
    short_title: str
    doc_type: str
    source_kind: str  # regulation | internal
    path: Path
    meta: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.meta.get(key, default)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.path.read_bytes()).hexdigest()


def _as_date(v: Any) -> date | None:
    if v is None or isinstance(v, date):
        return v
    return date.fromisoformat(str(v))


def load_manifest() -> list[SourceSpec]:
    s = get_settings()
    specs: list[SourceSpec] = []
    manifest = yaml.safe_load((s.data_dir / "sources.yaml").read_text(encoding="utf-8"))
    for d in manifest["documents"]:
        meta = {**d, "classification": d.get("classification", "public")}
        for k in ("published_on", "effective_from", "effective_to"):
            meta[k] = _as_date(meta.get(k))
        specs.append(
            SourceSpec(d["id"], d["title"], d["short_title"], d["doc_type"], "regulation",
                       s.raw_dir / f"{d['id']}.pdf", meta)
        )
    for md in sorted((s.data_dir / "internal").glob("*.md")):
        front, _ = _split_front_matter(md.read_text(encoding="utf-8"))
        meta = {**front}
        for k in ("published_on", "effective_from", "effective_to"):
            meta[k] = _as_date(meta.get(k))
        meta.setdefault("issuer", front.get("issuer"))
        meta.setdefault("source_name", "เอกสารภายในธนาคาร")
        specs.append(
            SourceSpec(front["id"], front["title"], front["short_title"], front["doc_type"],
                       "internal", md, meta)
        )
    return specs


def _split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    if text.startswith("---"):
        _, fm, body = text.split("---", 2)
        return yaml.safe_load(fm) or {}, body
    return {}, text


def markdown_lines(path: Path) -> list[Line]:
    """Turn a policy markdown file into pseudo-layout lines for the structure parser.

    Markdown headings become centred lines (section titles); every paragraph starts an
    indented line, which is how the parser recognises paragraph boundaries in PDFs.
    """
    _, body = _split_front_matter(path.read_text(encoding="utf-8"))
    lines: list[Line] = []
    for raw in body.splitlines():
        t = raw.strip()
        if not t:
            continue
        if t.startswith("# "):
            continue  # document title is already in metadata
        if t.startswith("#"):
            t = normalize_text(t.lstrip("#").strip())
            lines.append(Line(t, 1, 250, 350, 0, 16, True, 600, 0))
            continue
        lines.append(Line(normalize_text(t), 1, 20, 580, 0, 16, False, 600, 0))
    return lines


def ocr_lines(text: str, page: int) -> list[Line]:
    out: list[Line] = []
    for raw in text.splitlines():
        t = normalize_text(repair_thai(raw))
        if not t or t.startswith("```"):
            continue
        indent = 20 if _STRUCTURAL.match(t) else 0
        out.append(Line(t, page, indent, 560, 0, 16, False, 595, 0))
    return out


@dataclass
class LoadedDocument:
    lines: list[Line]
    footnotes: dict[str, str]
    page_count: int
    extraction: str
    ocr_pages: list[int]
    missing_pages: list[int]
    quality: dict[str, Any]


def load_document(spec: SourceSpec, use_ocr: bool = True) -> LoadedDocument:
    if spec.path.suffix == ".md":
        lines = markdown_lines(spec.path)
        return LoadedDocument(lines, {}, 1, "markdown", [], [], {"chars": sum(len(x.text) for x in lines)})

    doc: ExtractedDocument = extract_pdf(spec.path)
    lines = list(doc.lines)
    ocr_done: list[int] = []
    missing: list[int] = []
    for page in doc.pages_needing_ocr:
        text = _cached_ocr(spec, page) if use_ocr else None
        if text is None:
            missing.append(page)
            continue
        lines.extend(ocr_lines(text, page))
        ocr_done.append(page)
    lines.sort(key=lambda ln: (ln.page, 0))  # stable: keeps in-page order
    from .thai_text import dictionary_coverage

    sample = " ".join(x.text for x in lines[:400])
    quality = {
        "chars": sum(len(x.text) for x in lines),
        "dictionary_coverage": round(dictionary_coverage(sample), 3),
        "footnotes": len(doc.footnotes),
        "ocr_pages": ocr_done,
        "pages_without_text": missing,
    }
    return LoadedDocument(lines, doc.footnotes, doc.page_count,
                          "ocr+text" if ocr_done else "text", ocr_done, missing, quality)


def _cached_ocr(spec: SourceSpec, page: int) -> str | None:
    """OCR a page once and cache the transcription (keyed by file hash)."""
    from .. import llm

    cache = get_settings().processed_dir / "ocr" / spec.id
    cache.mkdir(parents=True, exist_ok=True)
    f = cache / f"p{page:03d}.json"
    sha = spec.sha256
    if f.exists():
        data = json.loads(f.read_text(encoding="utf-8"))
        if data.get("sha256") == sha:
            return data["text"]
    if not llm.available():
        return None
    text, usage = llm.ocr_image(render_page_png(spec.path, page))
    f.write_text(json.dumps({"sha256": sha, "page": page, "model": usage.model, "text": text},
                            ensure_ascii=False, indent=1), encoding="utf-8")
    return text
