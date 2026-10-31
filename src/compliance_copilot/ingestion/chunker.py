"""Turn parsed sections into retrievable chunks.

``structured`` (default): one chunk per citable unit (มาตรา / ข้อ), split only when a
unit is too long, always carrying its breadcrumb (document > หมวด > ส่วน > label) so
that both the embedding and the reader know where the text sits.

``naive``: fixed-size character windows that ignore structure - kept only as the
baseline for the retrieval ablation in the eval report.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .loaders import LoadedDocument, SourceSpec
from .structure import Section, parse_structure

_MARKER = re.compile(r"\[\^(\d+)\]")


@dataclass
class ChunkData:
    id: str
    document_id: str
    strategy: str
    ordinal: int
    label: str
    path: list[str]
    title: str | None
    text: str
    embed_text: str
    page_start: int
    page_end: int
    notes: list[str] = field(default_factory=list)
    extraction: str = "text"


def _slug(label: str) -> str:
    return re.sub(r"\s+", "_", label.strip())


def _split_long(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    parts: list[str] = []
    buf = ""
    for para in text.split("\n"):
        while len(para) > max_chars:  # a single huge paragraph: cut at a space near the limit
            cut = para.rfind(" ", int(max_chars * 0.6), max_chars)
            cut = cut if cut > 0 else max_chars
            if buf:
                parts.append(buf)
                buf = ""
            parts.append(para[:cut])
            para = para[cut:].lstrip()
        if buf and len(buf) + 1 + len(para) > max_chars:
            parts.append(buf)
            buf = para
        else:
            buf = f"{buf}\n{para}" if buf else para
    if buf:
        parts.append(buf)
    return parts


def _breadcrumb(spec: SourceSpec, path: list[str], label: str, title: str | None) -> str:
    crumbs = [spec.short_title, *path, label + (f" {title}" if title and title not in label else "")]
    return " > ".join(c for c in crumbs if c)


def structured_chunks(spec: SourceSpec, doc: LoadedDocument, max_chars: int) -> list[ChunkData]:
    mode = spec.get("structure")
    sections: list[Section] = parse_structure(doc.lines, mode)
    chunks: list[ChunkData] = []
    seen: dict[str, int] = {}
    for sec in sections:
        raw = sec.text
        notes = [f"[{n}] {doc.footnotes[n]}" for n in _MARKER.findall(raw) if n in doc.footnotes]
        text = _MARKER.sub("", raw).strip()
        body = text
        if sec.kind == "unit" and sec.title:
            body = text.replace(sec.title, "", 1)
        if len(re.sub(r"^(มาตรา|ข้อ)?\s*[\d./]+", "", body).strip()) < 25 and sec.kind == "unit":
            continue  # heading-only unit such as "5. เนื้อหา" - its title lives on in children's paths
        if sec.kind == "preamble" and len(text) < 40:
            continue
        pages_ocr = any(ln.page in doc.ocr_pages for ln in sec.lines)
        parts = _split_long(text, max_chars)
        for i, part in enumerate(parts):
            label = sec.label if len(parts) == 1 else f"{sec.label} (ตอนที่ {i + 1}/{len(parts)})"
            base = f"{spec.id}:{_slug(label)}"
            seen[base] = seen.get(base, 0) + 1
            cid = base if seen[base] == 1 else f"{base}~{seen[base]}"
            crumb = _breadcrumb(spec, sec.path, sec.label, sec.title)
            chunks.append(
                ChunkData(
                    id=cid, document_id=spec.id, strategy="structured", ordinal=len(chunks),
                    label=label, path=sec.path, title=sec.title, text=part,
                    embed_text=f"{crumb}\n{part}", page_start=sec.page_start, page_end=sec.page_end,
                    notes=notes, extraction="ocr" if pages_ocr else doc.extraction.split("+")[0],
                )
            )
    return chunks


def naive_chunks(spec: SourceSpec, doc: LoadedDocument, size: int = 1000, overlap: int = 150) -> list[ChunkData]:
    pieces: list[tuple[int, str]] = [(ln.page, _MARKER.sub("", ln.text)) for ln in doc.lines]
    text = ""
    offsets: list[tuple[int, int]] = []  # (char offset, page)
    for page, t in pieces:
        offsets.append((len(text), page))
        text += t + " "
    chunks: list[ChunkData] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        window = text[start:end].strip()
        page = max((p for off, p in offsets if off <= start), default=1)
        if window:
            label = f"ช่วงข้อความที่ {len(chunks) + 1} (หน้า {page})"
            chunks.append(
                ChunkData(
                    id=f"{spec.id}:naive:{len(chunks):04d}", document_id=spec.id, strategy="naive",
                    ordinal=len(chunks), label=label, path=[], title=None, text=window,
                    embed_text=f"{spec.short_title}\n{window}", page_start=page, page_end=page,
                )
            )
        if end == len(text):
            break
        start = end - overlap
    return chunks
