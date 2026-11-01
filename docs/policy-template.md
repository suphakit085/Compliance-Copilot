---
# ===== Governance (required - `copilot add-policy` refuses the file without these) =====
id: pol-example-001                  # lowercase, digits, hyphens; the file must be named <id>.md
title: ชื่อเต็มของนโยบาย
short_title: ชื่อย่อที่แสดงในการอ้างอิง (POL-EXAMPLE)
doc_type: policy                     # policy | procedure | manual
owner: ชื่อหน่วยงานเจ้าของนโยบาย       # the unit accountable for keeping it correct
approved_by: ชื่อคณะกรรมการ/ผู้มีอำนาจอนุมัติ
approved_on: 2026-01-15              # date of approval (not in the future)
review_due: 2027-01-15               # next review; the app warns 30 days before and after
status: approved                     # draft = not indexed | approved = searchable | withdrawn = removed

# ===== Applicability =====
issuer: ชื่อธนาคาร/บริษัท
classification: internal             # public | internal | confidential | restricted
# departments: [compliance]          # optional: only these departments may read it (omit = everyone with clearance)
topics: [example]
sectors: [banking, securities]
version: "1.0"
published_on: 2026-01-20
effective_from: 2026-02-01           # required for approved policies
# effective_to: 2027-02-01           # set when a newer version replaces it (keeps "as of" questions working)
# supersedes: pol-example-000        # the previous version's id
---

# ชื่อนโยบาย

ข้อ 1 นโยบายนี้มีวัตถุประสงค์เพื่อกำหนดหลักเกณฑ์ ... (ใส่ข้อความเต็มของข้อ)

ข้อ 2 นโยบายนี้ใช้บังคับกับพนักงานและผู้บริหารของ ... (ใส่ข้อความเต็มของข้อ)

<!--
Format rules that make citations precise:
- one numbered clause per paragraph, starting with "ข้อ N" (N = 1, 2, 3 ... in order; "ข้อ 4/1" for insertions)
- sub-items as (1), (2) or (ก), (ข) inside the clause
- section headings with "## หมวด 1 ..." are allowed
- do not paste tables as images; keep policy text as text
Check before adding:  uv run copilot add-policy path/to/pol-example-001.md --dry-run
-->
