from compliance_copilot.ingestion.chunker import _split_long
from compliance_copilot.ingestion.pdf_extract import Line
from compliance_copilot.ingestion.structure import detect_mode, join_lines, parse_structure


def L(text, indent=0.0, centered=False, page=1):  # noqa: N802 - test helper
    if centered:
        return Line(text, page, 250, 350, 0, 16, False, 600, 0)
    return Line(text, page, 60 + indent, 560, 0, 16, False, 600, 60)


ACT = [
    L("พระราชบัญญัติ", centered=True),
    L("มาตรา 1 พระราชบัญญัตินี้เรียกว่า ทดสอบ", indent=40),
    L("มาตรา 2 พระราชบัญญัตินี้ให้ใช้บังคับตั้งแต่วันถัดจากวันประกาศ เว้นแต่", indent=40),
    L("มาตรา 95 และมาตรา 96 ให้ใช้บังคับเมื่อพ้นหนึ่งปี"),  # wrapped line that merely starts with a reference
    L("หมวด 1", centered=True),
    L("คณะกรรมการ", centered=True),
    L("มาตรา 3 ให้มีคณะกรรมการ", indent=40),
    L("มาตรา 3/1 คณะกรรมการมีอำนาจ", indent=40),
    L("ส่วนที่ 1", centered=True),
    L("บททั่วไป", centered=True),
    L("มาตรา 4 ความในส่วนนี้", indent=40),
    L("(1) ข้อย่อยแรก", indent=40),
    L("ต่อบรรทัด"),
] + [L(f"มาตรา {n} เนื้อหา", indent=40) for n in range(5, 15)]


def test_act_sections_follow_numbering_and_hierarchy():
    secs = parse_structure(ACT)
    labels = [s.label for s in secs if s.kind == "unit"]
    assert labels[:5] == ["มาตรา 1", "มาตรา 2", "มาตรา 3", "มาตรา 3/1", "มาตรา 4"]
    # the wrapped "มาตรา 95 ..." line stays inside มาตรา 2 instead of becoming a heading
    m2 = next(s for s in secs if s.label == "มาตรา 2")
    assert "มาตรา 95 และมาตรา 96" in m2.text
    m4 = next(s for s in secs if s.label == "มาตรา 4")
    assert m4.path == ["หมวด 1 คณะกรรมการ", "ส่วนที่ 1 บททั่วไป"]
    assert "\n(1) ข้อย่อยแรกต่อบรรทัด" in m4.text  # list item starts a paragraph; Thai lines join without space


def test_mode_detection():
    assert detect_mode(ACT) == "section"
    clauses = [L(f"ข้อ {n} เนื้อหา", indent=40) for n in range(1, 8)]
    assert detect_mode(clauses) == "clause"


def test_outline_numbering_with_annex_reset():
    lines = [
        L("1. เหตุผลในการออกประกาศ", indent=0),
        L("เนื้อหาเหตุผลที่ยาวพอสมควรสำหรับทดสอบการแบ่งส่วน"),
        L("2. ขอบเขต"),
        L("2.1 สถาบันการเงิน ทุกแห่งที่อยู่ภายใต้การกำกับ"),
        L("28 ธันวาคม 2566"),  # date - not an outline heading
        L("เอกสารแนบ 1", centered=True),
        L("การโฆษณา", centered=True),
        L("1.1 โฆษณาต้องถูกต้องและชัดเจน เพื่อให้ลูกค้าเข้าใจ"),
        L("1.1.1 ต้องแสดงอัตราดอกเบี้ยที่แท้จริงต่อปี"),
    ]
    secs = parse_structure(lines, mode="outline")
    labels = [s.label for s in secs if s.kind == "unit"]
    assert labels == ["ข้อ 1", "ข้อ 2", "ข้อ 2.1", "เอกสารแนบ 1 ข้อ 1.1", "เอกสารแนบ 1 ข้อ 1.1.1"]
    last = secs[-1]
    assert last.path[0] == "เอกสารแนบ 1 การโฆษณา"
    assert "28 ธันวาคม 2566" in next(s for s in secs if s.label == "ข้อ 2.1").text


def test_join_lines_spacing():
    text = join_lines([L("ภาษาไทย"), L("ต่อกัน"), L("English"), L("words")])
    assert text == "ภาษาไทยต่อกัน English words"


def test_split_long_respects_limit_and_paragraphs():
    text = "\n".join(["ก" * 500, "ข" * 500, "ค" * 500])
    parts = _split_long(text, 1100)
    assert len(parts) == 2 and all(len(p) <= 1100 for p in parts)
    assert _split_long("สั้น", 1100) == ["สั้น"]
