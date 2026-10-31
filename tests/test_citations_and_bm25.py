from compliance_copilot.generation.citations import ground, verify_quote
from compliance_copilot.retrieval.bm25 import CorpusStats, score

SRC = {
    "S1": "มาตรา 37 (4) แจ้งเหตุการละเมิดข้อมูลส่วนบุคคลแก่สำนักงานโดยไม่ชักช้าภายในเจ็ดสิบสองชั่วโมงนับแต่ทราบเหตุ",
    "S2": "ข้อ 8 DPO ต้องแจ้งเหตุต่อสำนักงานภายใน 7 วันนับแต่ทราบเหตุ",
}


def test_exact_and_whitespace_tolerant_quotes_verify():
    assert verify_quote("ภายในเจ็ดสิบสองชั่วโมงนับแต่ทราบเหตุ", SRC["S1"])[0]
    assert verify_quote("ภายใน  7 วัน\nนับแต่ทราบเหตุ", SRC["S2"])[0]
    assert verify_quote("ภายใน ๗ วันนับแต่ทราบเหตุ", SRC["S2"])[0]  # Thai digits normalised


def test_fabricated_quote_is_rejected():
    ok, ratio, _ = verify_quote("ภายในสามสิบวันนับแต่ได้รับคำขอ", SRC["S1"])
    assert not ok and ratio < 0.85


def test_quote_attributed_to_wrong_source_is_rejected():
    rep = ground("ต้องแจ้งภายใน 72 ชั่วโมง [S2]", [("S2", "ภายในเจ็ดสิบสองชั่วโมงนับแต่ทราบเหตุ")], SRC)
    assert rep.verified_sources == set()
    assert rep.unsupported_markers == ["S2"]


def test_markers_to_unknown_sources_are_removed():
    rep = ground("ต้องแจ้งภายใน 72 ชั่วโมง [S1][S9]", [("S1", "ภายในเจ็ดสิบสองชั่วโมง")], SRC)
    assert "[S9]" not in rep.answer
    assert rep.markers_total == 1 and rep.support_rate == 1.0


def test_bm25_prefers_rare_terms():
    stats = CorpusStats(n_docs=100, avg_len=50, df={"ข้อมูล": 90, "ชีวภาพ": 2}, version="t")
    common = score(["ข้อมูล", "ชีวภาพ"], ["ข้อมูล"] * 5 + ["อื่น"] * 45, stats)
    rare = score(["ข้อมูล", "ชีวภาพ"], ["ชีวภาพ"] + ["อื่น"] * 49, stats)
    assert rare > common
