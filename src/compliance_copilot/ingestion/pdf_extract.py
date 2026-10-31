"""Layout-aware PDF text extraction for Thai regulatory documents.

Beyond plain text, downstream structure parsing needs to know where a line sits on the
page (indentation marks paragraph starts; centred short lines are headings), and the
compliance answer needs amendment footnotes ("มาตรา 22 แก้ไขเพิ่มเติมโดย ...") kept
apart from the body text rather than spliced into the middle of a sentence.

Steps per page:
1. Read spans with font metadata (PyMuPDF ``dict`` mode) and repair Thai per span.
2. Merge raw lines that share a baseline into visual rows ("มาตรา ๗" and its text are
   separate objects in Royal Gazette PDFs).
3. Drop running headers/footers: rows in the top/bottom margin that are page numbers
   or repeat across many pages.
4. Separate footnotes (smaller font, below the body) and replace superscript
   footnote markers in the body with ``[^N]`` tokens.
5. Flag pages without a text layer for OCR.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from .thai_text import (
    fix_broken_sara_am,
    map_pua,
    normalize_text,
    repair_thai,
    swap_aa_am,
    to_arabic_digits,
)

_MARKER_TEXT = re.compile(r"^[\s0-9๐-๙-]+$")
_PAGE_NUMBER = re.compile(r"^[\s\-–—(]*(หน้า\s*)?[0-9๐-๙]+(\s*/\s*[0-9๐-๙]+)?[\s\-–—)]*$")
_SEPARATOR = re.compile(r"^[\s_\-–—=.]*$")
_THAI_MARKS = re.compile("[ัิ-ฺ็-๎]")  # above/below marks, not SARA AA
_GAZETTE_HEADER = re.compile(r"^(หนา|หน้า)?\s*[0-9๐-๙]+(\s*(เลม|เล่ม).*)?$")


@dataclass
class Line:
    text: str
    page: int
    x0: float
    x1: float
    y0: float
    size: float
    bold: bool
    page_width: float
    margin_left: float = 0.0

    @property
    def indent(self) -> float:
        return self.x0 - self.margin_left

    @property
    def centered(self) -> bool:
        mid = (self.x0 + self.x1) / 2
        return abs(mid - self.page_width / 2) < 40 and self.indent > 60


@dataclass
class ExtractedDocument:
    lines: list[Line]
    footnotes: dict[str, str]
    page_count: int
    pages_needing_ocr: list[int] = field(default_factory=list)
    body_font_size: float = 0.0


@dataclass
class _Span:
    text: str
    size: float
    font: str
    superscript: bool


@dataclass
class _Row:
    spans: list[_Span]
    x0: float
    x1: float
    y0: float
    y1: float

    @property
    def raw_text(self) -> str:
        return "".join(s.text for s in self.spans)

    def dominant_size(self) -> float:
        weights: Counter[float] = Counter()
        for s in self.spans:
            if s.text.strip():
                weights[round(s.size, 1)] += len(s.text.strip())
        return weights.most_common(1)[0][0] if weights else 0.0

    def is_bold(self) -> bool:
        chars = [s for s in self.spans if s.text.strip()]
        return bool(chars) and all("bold" in s.font.lower() for s in chars)


def _page_rows(page: pymupdf.Page) -> list[_Row]:
    raw: list[_Row] = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            spans = [
                _Span(s["text"], s["size"], s["font"], bool(s["flags"] & 1))
                for s in line["spans"]
                if s["text"]
            ]
            if not spans or not "".join(s.text for s in spans).strip():
                continue
            x0, y0, x1, y1 = line["bbox"]
            raw.append(_Row(spans, x0, x1, y0, y1))

    # Merge lines sharing a baseline (vertical overlap > 50% of the shorter line).
    raw.sort(key=lambda r: ((r.y0 + r.y1) / 2, r.x0))
    rows: list[_Row] = []
    for r in raw:
        if rows:
            last = rows[-1]
            overlap = min(last.y1, r.y1) - max(last.y0, r.y0)
            height = min(last.y1 - last.y0, r.y1 - r.y0) or 1
            if overlap / height > 0.5:
                parts = sorted([last, r], key=lambda q: q.x0)
                gap = [_Span(" ", parts[0].spans[-1].size, "", False)]
                rows[-1] = _Row(
                    parts[0].spans + gap + parts[1].spans,
                    min(last.x0, r.x0), max(last.x1, r.x1),
                    min(last.y0, r.y0), max(last.y1, r.y1),
                )
                continue
        rows.append(r)
    return rows


def _is_marker(span: _Span, body: float) -> bool:
    text = to_arabic_digits(repair_thai(span.text)).strip()
    if not text or not _MARKER_TEXT.match(text) or "-" in text:
        return False
    return span.superscript or span.size <= body * 0.75 or span.font.startswith("Symbol")


def _broken_fonts(rows: list[_Row]) -> set[str]:
    """Fonts whose ToUnicode map swaps SARA AA/SARA AM on this page (pattern B).

    A font is diagnosed per page because merged PDFs reuse font names across parts
    that were produced by different tools. Normal Thai prose of any length contains
    "า"; a font that yields " ำ" or many "ำ" but never "า" is mis-mapped.
    """
    stats: dict[str, Counter[str]] = {}
    for row in rows:
        for s in row.spans:
            c = stats.setdefault(s.font, Counter())
            t = map_pua(s.text)
            c["aa"] += t.count("า")
            c["am"] += t.count("ำ")
            c["sp_am"] += t.count(" ำ")
    return {f for f, c in stats.items() if c["aa"] == 0 and (c["sp_am"] >= 1 or c["am"] >= 3)}


def _repair_span(span: _Span, broken: set[str]) -> str:
    if span.font in broken:
        return fix_broken_sara_am(swap_aa_am(map_pua(span.text)))
    return repair_thai(span.text)


def _row_text(
    row: _Row, body: float, footnote: bool, broken: set[str] = frozenset()
) -> tuple[str, str | None]:
    """Return (text, footnote_number). Inline markers become ``[^N]``."""
    out: list[str] = []
    note_no: str | None = None
    for i, span in enumerate(row.spans):
        if _is_marker(span, body):
            number = to_arabic_digits(repair_thai(span.text)).strip()
            if footnote and i == 0 or (footnote and not "".join(out).strip()):
                note_no = number
            else:
                out.append(f"[^{number}]")
            continue
        out.append(_repair_span(span, broken))
    text = fix_broken_sara_am("".join(out))
    return text, note_no


def extract_pdf(path: str | Path) -> ExtractedDocument:
    doc = pymupdf.open(str(path))
    pages = [_page_rows(p) for p in doc]

    # Body font size = char-weighted mode across the document.
    size_hist: Counter[float] = Counter()
    for rows in pages:
        for row in rows:
            for s in row.spans:
                if s.text.strip():
                    size_hist[round(s.size)] += len(s.text)
    body = float(size_hist.most_common(1)[0][0]) if size_hist else 16.0

    # Running headers/footers: texts (digits stripped) recurring in the page margins.
    margin_texts: Counter[str] = Counter()
    for pno, rows in enumerate(pages):
        h = doc[pno].rect.height
        seen = set()
        for row in rows:
            if row.y0 < h * 0.09 or row.y1 > h * 0.93:
                key = re.sub(r"[0-9๐-๙\s]", "", row.raw_text)
                if key and key not in seen:
                    seen.add(key)
                    margin_texts[key] += 1
    repeat_threshold = max(3, int(0.25 * len(pages)))
    running = {k for k, n in margin_texts.items() if n >= repeat_threshold}

    lines: list[Line] = []
    footnotes: dict[str, str] = {}
    needs_ocr: list[int] = []

    for pno, rows in enumerate(pages):
        page = doc[pno]
        w, h = page.rect.width, page.rect.height
        page_chars = sum(len(r.raw_text.strip()) for r in rows)
        if page_chars < 40 and page.get_images():
            needs_ocr.append(pno + 1)
            continue

        broken = _broken_fonts(rows)
        kept: list[_Row] = []
        for row in rows:
            raw = row.raw_text
            in_margin = row.y0 < h * 0.09 or row.y1 > h * 0.93
            key = re.sub(r"[0-9๐-๙\s]", "", raw)
            bare = _THAI_MARKS.sub("", raw).strip()
            if (in_margin and (_PAGE_NUMBER.match(raw) or key in running)) or (
                row.y0 < h * 0.15 and _GAZETTE_HEADER.match(bare)
            ):
                continue
            if key and key in running and len(key) > 12:
                continue  # watermark-like slogans repeated mid-page
            if _SEPARATOR.match(raw):
                continue
            kept.append(row)

        # Footnotes: rows set smaller than body text, below the last body-sized row.
        last_body_y = max(
            (r.y0 for r in kept if r.dominant_size() >= body - 0.6), default=0.0
        )
        current_note: str | None = None
        body_rows: list[_Row] = []
        for row in kept:
            small = 0 < row.dominant_size() <= body - 1.5
            if small and row.y0 > last_body_y:
                text, number = _row_text(row, body, footnote=True, broken=broken)
                text = normalize_text(text)
                if number:
                    current_note = number
                    footnotes[number] = text
                elif current_note:
                    footnotes[current_note] = f"{footnotes[current_note]} {text}".strip()
                continue
            body_rows.append(row)

        texts = [(_row_text(r, body, footnote=False, broken=broken)[0], r) for r in body_rows]
        long_x0 = [r.x0 for t, r in texts if len(t.strip()) > 25]
        margin = min(long_x0) if long_x0 else min((r.x0 for _, r in texts), default=0.0)
        for text, row in texts:
            norm = normalize_text(text)
            if not norm:
                continue
            lines.append(
                Line(
                    text=norm, page=pno + 1, x0=row.x0, x1=row.x1, y0=row.y0,
                    size=row.dominant_size(), bold=row.is_bold(), page_width=w,
                    margin_left=margin,
                )
            )

    return ExtractedDocument(
        lines=lines, footnotes=footnotes, page_count=len(doc),
        pages_needing_ocr=needs_ocr, body_font_size=body,
    )


def render_page_png(path: str | Path, page_number: int, dpi: int = 170) -> bytes:
    doc = pymupdf.open(str(path))
    return doc[page_number - 1].get_pixmap(dpi=dpi).tobytes("png")
