import pytest

from compliance_copilot.ingestion.thai_text import (
    fix_broken_sara_am,
    map_pua,
    normalize_text,
    repair_thai,
    swap_aa_am,
    to_arabic_digits,
)


@pytest.mark.parametrize(
    ("broken", "fixed"),
    [
        ("ก าหนด", "กำหนด"),
        ("ส านักงาน", "สำนักงาน"),
        ("ซ้ ากับ", "ซ้ำกับ"),
        ("ต ่าสุด", "ต่ำสุด"),
        ("ค ้าประกัน", "ค้ำประกัน"),
        ("ผู้ด ารงต าแหน่งส าคัญ", "ผู้ดำรงตำแหน่งสำคัญ"),
        ("ควํ่าบาตร", "คว่ำบาตร"),  # decomposed NIKHAHIT + tone + SARA AA
    ],
)
def test_pattern_a_broken_sara_am(broken, fixed):
    assert repair_thai(broken) == fixed


@pytest.mark.parametrize(
    ("broken", "fixed"),
    [
        ("อ ำนำจตำมกฎหมำย", "อำนาจตามกฎหมาย"),  # has the " ำ" tell-tale
        ("5.1 ค ำจ ำกัดควำม", "5.1 คำจำกัดความ"),
        ("หลักกำร", "หลักการ"),  # no tell-tale: decided by the dictionary
        ("ประกำศฉบับนี้ให้ใช้บังคับกับผู้ให้บริกำร", "ประกาศฉบับนี้ให้ใช้บังคับกับผู้ให้บริการ"),
    ],
)
def test_pattern_b_swapped_aa_am(broken, fixed):
    assert repair_thai(broken) == fixed


@pytest.mark.parametrize("ok", ["กำหนด", "สำนักงาน", "คำนำ", "จำนำ", "ทำงาน กำลัง", "ค้ำประกัน"])
def test_valid_text_is_untouched(ok):
    assert repair_thai(ok) == ok


def test_space_before_aa_is_not_a_word_start():
    # a lone " า" never starts a Thai word, so the regex is safe on normal prose
    assert fix_broken_sara_am("ข้อมูล การ") == "ข้อมูล การ"


def test_swap_is_an_involution_on_marked_text():
    assert swap_aa_am("อ ำนำจ") == "อำนาจ"


def test_pua_and_digits():
    assert map_pua("") == "่"
    assert map_pua("") == "12"
    assert to_arabic_digits("มาตรา ๒๖ วรรค ๑") == "มาตรา 26 วรรค 1"


def test_normalize_collapses_space_and_quotes():
    assert normalize_text("“ลูกค้า”   หมายความว่า") == '"ลูกค้า" หมายความว่า'
