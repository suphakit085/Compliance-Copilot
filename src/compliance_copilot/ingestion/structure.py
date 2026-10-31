"""Recover the legal structure of a Thai regulatory document.

The citable unit differs by document type:

* Acts (พระราชบัญญัติ)                        -> มาตรา N  (with หมวด / ส่วน as context)
* Ministerial regulations, notifications      -> ข้อ N
* BOT / SEC circulars and annexes             -> outline numbers 5.3.1 (เอกสารแนบ N as context)

Lines that merely *start* with a reference ("มาตรา 95 และมาตรา 96 ให้ใช้บังคับ...",
a wrapped continuation line) are the main false-positive risk, so every heading
candidate must be a valid *successor* of the previous heading number: มาตรา 27 may
follow 26 or 26/1, outline 5.3.2 may follow 5.3.1 or 5.3, and so on.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from .pdf_extract import Line

_CHAPTER = re.compile(r"^หมวด\s*(\d{1,2}(?:/\d{1,2})?)(?:\[\^\d+\])?\s*(.{0,80})$")
_PART = re.compile(r"^ส่วนที่\s*(\d{1,2})\s*(.{0,80})$")
_TRANSITORY = re.compile(r"^บทเฉพาะกาล\s*$")
_ANNEX = re.compile(r"^(เอกสารแนบ|ภาคผนวก|แนบท้าย)\s*([0-9]{1,2}|[ก-ฮ])\s*(.{0,60})$")
_ENDNOTE = re.compile(r"^(หมายเหตุ\s*:?\s*-?|ผู้รับสนองพระบรมราชโองการ)")
_UNIT = {
    "section": re.compile(r"^มาตรา\s*(\d{1,3}(?:/\d{1,2})?)(?:\[\^\d+\])?(?:\s+(.*)|$)"),
    "clause": re.compile(r"^ข้อ\s*(\d{1,3}(?:/\d{1,2})?)(?:\[\^\d+\])?(?:\s+(.*)|$)"),
    "outline": re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,2})\.?(?:\[\^\d+\])?\s+(\S.*)$"),
}
_UNIT_LABEL = {"section": "มาตรา", "clause": "ข้อ", "outline": "ข้อ"}
_ITEM_START = re.compile(r"^(\(\d{1,2}\)|\([ก-ฮ]\)|[-•]\s|\d{1,2}\)\s)")
_MONTH = re.compile(
    r"^(มกราคม|กุมภาพันธ์|มีนาคม|เมษายน|พฤษภาคม|มิถุนายน|กรกฎาคม|สิงหาคม|กันยายน|ตุลาคม|พฤศจิกายน|ธันวาคม|ม\.ค\.|ก\.พ\.|มี\.ค\.|เม\.ย\.|พ\.ค\.|มิ\.ย\.|ก\.ค\.|ส\.ค\.|ก\.ย\.|ต\.ค\.|พ\.ย\.|ธ\.ค\.|บาท|ราย|วัน|ปี|เดือน|%)"
)
_THAI = re.compile(r"[ก-๛]")


@dataclass
class Section:
    kind: str  # preamble | unit | endnote
    label: str  # "มาตรา 26", "ข้อ 5", "เอกสารแนบ 1 ข้อ 1.1.1", "บทนำ"
    number: str | None
    path: list[str]
    title: str | None
    lines: list[Line] = field(default_factory=list)

    @property
    def page_start(self) -> int:
        return self.lines[0].page if self.lines else 0

    @property
    def page_end(self) -> int:
        return self.lines[-1].page if self.lines else 0

    @property
    def text(self) -> str:
        return join_lines(self.lines)


def join_lines(lines: Sequence[Line]) -> str:
    """Join PDF lines into paragraphs. Thai has no inter-word spaces, so wrapped Thai
    lines are concatenated directly; a new paragraph starts at an indented line or a
    list item."""
    out = ""
    prev: Line | None = None
    for line in lines:
        t = line.text
        if prev is None:
            out = t
        elif line.indent > 15 or _ITEM_START.match(t) or prev.centered or line.centered:
            out += "\n" + t
        elif _THAI.match(t[:1]) and _THAI.match(out[-1:]):
            out += t
        else:
            out += " " + t
        prev = line
    return out


def _num_key(num: str) -> tuple[int, int]:
    base, _, sub = num.partition("/")
    return int(base), int(sub or 0)


def _is_unit_successor(prev: str | None, cand: str, reset: bool) -> bool:
    k = _num_key(cand)
    if prev is None or reset:
        return k[0] <= 2 and k[1] == 0
    p = _num_key(prev)
    if k == (p[0] + 1, 0):
        return True
    if k[0] == p[0] and k[1] == p[1] + 1:  # inserted section: 22 -> 22/1 -> 22/2
        return True
    return k[0] == p[0] + 1 and k[1] == 0 or (p[0] + 1 < k[0] <= p[0] + 2 and k[1] == 0)


def _is_outline_successor(prev: tuple[int, ...], cand: tuple[int, ...], reset: bool) -> bool:
    if reset or not prev:
        return cand[-1] == 1 and len(cand) <= 2 or cand == (1,)
    if cand == prev + (1,):  # first child: 5.3 -> 5.3.1
        return True
    # next sibling at any level: 5.3.1 -> 5.3.2 / 5.4 / 6
    return any(cand == prev[:i] + (prev[i] + 1,) for i in range(len(prev)))


def detect_mode(lines: Sequence[Line]) -> str:
    n_section = sum(1 for ln in lines if _UNIT["section"].match(ln.text) and ln.indent > 10)
    n_clause = sum(1 for ln in lines if _UNIT["clause"].match(ln.text) and ln.indent > 10)
    if n_section >= 10 and n_section >= n_clause:
        return "section"
    if n_clause >= 4:
        return "clause"
    return "outline"


def parse_structure(lines: Sequence[Line], mode: str | None = None) -> list[Section]:
    mode = mode or detect_mode(lines)
    unit_re = _UNIT[mode]
    sections: list[Section] = []
    chapter: str | None = None
    part: str | None = None
    annex: str | None = None
    last_chapter = (0, 0)
    last_part = 0
    last_unit: str | None = None
    outline_path: tuple[int, ...] = ()
    outline_titles: dict[tuple[int, ...], str] = {}
    reset = False
    pending: str | None = None  # "chapter" | "part" | "annex" awaiting a title line
    current: Section | None = None

    def context() -> list[str]:
        return [c for c in (annex, chapter, part) if c]

    def start(kind: str, label: str, number: str | None, title: str | None, path: list[str]):
        nonlocal current
        current = Section(kind, label, number, path, title)
        sections.append(current)

    for line in lines:
        t = line.text
        short = len(t) <= 90

        # A heading title on the line after "หมวด 2" / "ส่วนที่ 1" / "เอกสารแนบ 3".
        if pending and short and not unit_re.match(t) and not _CHAPTER.match(t):
            if pending == "chapter":
                chapter = f"{chapter} {t}"
            elif pending == "part":
                part = f"{part} {t}"
            elif pending == "annex":
                annex = f"{annex} {t}"
            pending = None
            continue
        pending = None

        if m := _CHAPTER.match(t):
            n = _num_key(m.group(1))
            ok = n == (last_chapter[0] + 1, 0) or (n[0] == last_chapter[0] and n[1] == last_chapter[1] + 1)
            if ok and (line.centered or len(t) < 70):
                last_chapter, last_part = n, 0
                chapter, part = f"หมวด {m.group(1)}", None
                if m.group(2).strip():
                    chapter += f" {m.group(2).strip()}"
                else:
                    pending = "chapter"
                current = None
                continue
        if m := _PART.match(t):
            n = int(m.group(1))
            if n in (1, last_part + 1) and (line.centered or len(t) < 70):
                last_part = n
                part = f"ส่วนที่ {n}"
                if m.group(2).strip():
                    part += f" {m.group(2).strip()}"
                else:
                    pending = "part"
                current = None
                continue
        if _TRANSITORY.match(t):
            chapter, part, current = "บทเฉพาะกาล", None, None
            continue
        if (m := _ANNEX.match(t)) and (line.centered or line.bold or len(t) < 25):
            annex = f"{m.group(1)} {m.group(2)}"
            if m.group(3).strip():
                annex += f" {m.group(3).strip()}"
            else:
                pending = "annex"
            chapter = part = None
            reset, outline_path, outline_titles = True, (), {}
            current = None
            continue
        if mode == "section" and _ENDNOTE.match(t) and sections:
            start("endnote", "หมายเหตุท้ายประกาศ", None, None, [])
            current.lines.append(line)
            continue

        if (m := unit_re.match(t)) and (current is None or current.kind != "endnote"):
            num = m.group(1)
            rest = (m.group(2) or "").strip()
            accepted = False
            if mode == "outline":
                key = tuple(int(x) for x in num.split("."))
                if not _MONTH.match(rest) and _is_outline_successor(outline_path, key, reset):
                    accepted = True
                    outline_path = key
                    title = rest if len(rest) <= 60 else None
                    if title:
                        outline_titles[key] = title
                    ancestors = [
                        f"ข้อ {'.'.join(map(str, key[:j]))} {outline_titles[key[:j]]}"
                        for j in range(1, len(key))
                        if key[:j] in outline_titles
                    ]
                    prefix = f"{annex.split(' ')[0]} {annex.split(' ')[1]} " if annex else ""
                    start("unit", f"{prefix}ข้อ {num}", num, title, context() + ancestors)
            elif _is_unit_successor(last_unit, num, reset):
                accepted = True
                last_unit = num
                prefix = f"{annex.split(' ')[0]} {annex.split(' ')[1]} " if annex else ""
                start("unit", f"{prefix}{_UNIT_LABEL[mode]} {num}", num, None, context())
            if accepted:
                reset = False
                current.lines.append(line)
                continue

        if current is None:
            label = "บทนำ" if not sections else (annex or chapter or "ข้อความ")
            start("preamble", label, None, None, context())
        current.lines.append(line)

    return [s for s in sections if s.lines]
