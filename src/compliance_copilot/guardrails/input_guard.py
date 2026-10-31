"""Prompt-injection screening for user input.

Defence in depth - this heuristic layer is only the first line:
1. obvious attempts to override instructions are refused before any retrieval;
2. the system prompt tells the model that user and document text are data, not
   instructions;
3. access control is enforced in SQL, so even a successful jailbreak cannot
   surface a document the user is not cleared for - the model never sees it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("override_en", re.compile(r"\b(ignore|disregard|forget)\b.{0,40}\b(instruction|prompt|rule|previous|above)", re.I)),
    ("role_en", re.compile(r"\b(you are now|act as|pretend to be|developer mode|jailbreak|DAN)\b", re.I)),
    ("leak_en", re.compile(r"\b(reveal|show|print|repeat)\b.{0,30}\b(system prompt|instructions|hidden prompt)", re.I)),
    ("override_th", re.compile(r"(ไม่ต้องสนใจ|ละเว้น|ลืม|ยกเลิก|ข้าม).{0,20}(คำสั่ง|กฎ|ข้อกำหนด|ข้อจำกัด|ข้อความก่อนหน้า)")),
    ("role_th", re.compile(r"(ตอนนี้คุณคือ|จากนี้ไปคุณคือ|สวมบทบาท|ทำตัวเป็น|เปลี่ยนบทบาท)")),
    ("leak_th", re.compile(r"(แสดง|บอก|เปิดเผย|พิมพ์).{0,15}(system prompt|พรอมต์|prompt|คำสั่งระบบ|คำสั่งลับ)")),
    ("acl_bypass", re.compile(r"(ข้าม|เลี่ยง|bypass).{0,20}(สิทธิ์|สิทธิ|permission|access control|ระดับชั้นความลับ)", re.I)),
]


@dataclass
class GuardResult:
    blocked: bool
    flags: list[str] = field(default_factory=list)


def screen(text: str) -> GuardResult:
    flags = [name for name, p in _PATTERNS if p.search(text)]
    return GuardResult(blocked=bool(flags), flags=flags)


REFUSAL = (
    "ขออภัย ระบบไม่สามารถดำเนินการตามคำขอนี้ได้ เนื่องจากมีลักษณะเป็นการพยายามเปลี่ยนแปลงคำสั่ง"
    "หรือข้ามข้อจำกัดของระบบ หากต้องการสอบถามเรื่องกฎระเบียบหรือนโยบาย กรุณาพิมพ์คำถามใหม่"
)
