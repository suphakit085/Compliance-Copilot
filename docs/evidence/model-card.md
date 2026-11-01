# Model card and evidence pack - Compliance Copilot

Generated 2026-11-01T20:08:18+00:00 from the running system. Build: git `4787724 (uncommitted changes present)`; application version 0.1.0; Python 3.12.14 on Windows.

> This file is produced by `copilot evidence-pack`. It reports what the system *is configured to do* and what its stored test results *say*; it does not certify either. Section 6 lists what it cannot verify.

## 1. Components and versions

| Component | Value |
|---|---|
| Answer model (chat) | gemini: `gemini-3.1-flash-lite` (reasoning effort `low`) |
| Batch model (gap analysis, evaluation) | `gemini-3.1-flash-lite` |
| Embeddings | `BAAI/bge-m3` (1024 dimensions), runs locally |
| Reranker | `BAAI/bge-reranker-v2-m3`, runs locally |
| Prompt versions | answer `answer-v3`, gap analysis `gap-v3`; ingestion pipeline `4` |
| Retrieval | dense top 40 + lexical top 40, rank fusion, rerank 24, context 6 passages |
| Abstention | below reranker score 0.02 no LLM call is made; the model must also return `insufficient_evidence` when passages do not answer |
| Libraries | fastapi 0.162.0, sqlalchemy 2.1.6, pgvector 0.5.1, sentence-transformers 6.2.0, torch 2.14.1+cu130, google-genai 2.34.0 |

## 2. Knowledge base

| Document | Kind | Version / effective | SHA-256 | Class | Owner / approver / status / review due | Checked vs publisher |
|---|---|---|---|---|---|---|
| `amla-2542` | regulation | - / 1999-08-19 | `ce244bb36546` | public | public source | 2026-11-01 |
| `bot-amlo-sanctions-jps-2567` | regulation | - / 2024-12-27 | `5ba1fada718a` | public | public source | 2026-11-01 |
| `bot-responsible-lending-2566` | regulation | - / 2024-01-01 | `16173531da89` | public | public source | 2026-11-01 |
| `cdd-2563` | regulation | - / 2020-08-12 | `160f91c6920e` | public | public source | 2026-11-01 |
| `pdpa-2562` | regulation | - / 2022-06-01 | `9fd1027c2e5a` | public | public source | 2026-11-01 |
| `pdpc-breach-2565` | regulation | - / 2022-12-15 | `38ae790fba5a` | public | public source | 2026-11-01 |
| `sec-outsourcing-circular-2568` | regulation | - / 2026-04-01 | `4a7812217b9d` | public | public source | 2026-11-01 |
| `sec-tt-35-2556` | regulation | - / 2014-04-01 | `00bf718a1551` | public | public source | 2026-11-01 |
| `pol-aml-001` **(synthetic sample)** | internal | 3.1 / 2024-01-01 | `e38933375bcb` | internal | ฝ่ายกำกับการปฏิบัติงาน - หน่วยงาน AML / คณะกรรมการบริหารความเสี่ยง (ตัวอย่าง) / approved / 2027-03-20 | - |
| `pol-gift-2566` **(synthetic sample)** | internal | 1.0 / 2023-01-01 | `64aab7f52204` | internal | ฝ่ายกำกับการปฏิบัติงาน / คณะกรรมการบริหารความเสี่ยง (ตัวอย่าง) / approved / 2024-06-20 | - |
| `pol-gift-2568` **(synthetic sample)** | internal | 2.0 / 2025-07-01 | `be9f3867ad76` | internal | ฝ่ายกำกับการปฏิบัติงาน / คณะกรรมการบริหารความเสี่ยง (ตัวอย่าง) / approved / 2027-06-20 | - |
| `pol-lending-001` **(synthetic sample)** | internal | 1.2 / 2024-02-15 | `32c1fd515562` | internal | สายงานลูกค้ารายย่อย ร่วมกับฝ่ายกำกับการปฏิบัติงาน / คณะกรรมการบริหารความเสี่ยง (ตัวอย่าง) / approved / 2026-09-30 | - |
| `pol-pdpa-001` **(synthetic sample)** | internal | 2.0 / 2024-04-01 | `c6960fcd2e34` | internal | ฝ่ายกำกับการปฏิบัติงาน (Compliance) และเจ้าหน้าที่คุ้มครองข้อมูลส่วนบุคคล (DPO) / คณะกรรมการบริหารความเสี่ยง (ตัวอย่าง) / approved / 2026-12-15 | - |
| `proc-str-001` **(synthetic sample)** | internal | 1.4 / 2025-02-01 | `2d6b0316bf0e` | confidential | ฝ่ายกำกับการปฏิบัติงาน - หน่วยงาน AML / คณะกรรมการบริหารความเสี่ยง (ตัวอย่าง) / approved / 2027-01-10 | - |

## 3. Evaluation evidence

| Set | Questions | Expert-confirmed | Retrieval Hit@6 (production) | End-to-end behaviour | Key facts | Leakage | Run |
|---|---|---|---|---|---|---|---|
| main | 51 | 0 of 51 | 100.0% | 100.0% | 100.0% | 0 | 2026-11-01 gemini-3.1-flash-lite |
| holdout | 21 | 0 of 21 | 100.0% | 100.0% | 100.0% | 0 | 2026-11-01 gemini-3.1-flash-lite |
| extended | 146 | 0 of 146 | 97.7% | 94.5% | 93.8% | 0 | 2026-11-01 gemini-3.1-flash-lite |

**First runs, before any change in response to them** (the honest estimate for unseen questions):

- held-out set, first (blind) run: retrieval Hit@6 94.1%; end-to-end behaviour 85.7%, key facts 76.5%
- extended set, first (blind) run: retrieval Hit@6 92.2%

The `main` set was used to tune the system, and the held-out and extended results above are after fixes made in response to their first runs, so only the first-run lines are estimates for unseen questions.

Full reports: `docs/evaluation.md`, `docs/eval-report*.md`. Questions were written by engineers; **an expert-confirmed count of 0 means no compliance specialist has validated the expected answers yet.**

## 4. Controls checked against this deployment

| Area | Control | Result | Detail |
|---|---|---|---|
| Access control | Row-level security on documents and chunks (second layer after the SQL filter) | **PASS** | 2 policies; RLS on: documents, chunks |
| Audit | Hash chain of the audit log verifies | **PASS** | 946 records |
| Authentication | Single sign-on configured | **PASS** | issuer http://localhost:8081/realms/copilot |
| Authentication | Password login | **INFO** | enabled |
| Authentication | No active account still has a published demo password | **ATTENTION** | 4 active: nida, kittipong, admin, somchai |
| Authentication | Lockout after 5 failures / 15 min; rate limits chat 20/min, gap 5/10 min | **PASS** | configured |
| Deployment | Environment is production | **ATTENTION** | development |
| Deployment | JWT secret is not the development default | **PASS** | strong secret set |
| Operations | Metrics endpoint protected by a token | **ATTENTION** | disabled (no monitoring) |
| Privacy | Personal data masked before the LLM | **PASS** | on |
| Privacy | Chat history retention | **PASS** | 90 days |
| Use | Users must accept the acceptable-use terms | **ATTENTION** | not enforced |
| Content | No synthetic sample documents in the index | **ATTENTION** | 6 of 14 documents are samples: replace before production |
| Content | Internal policies are within their review date | **ATTENTION** | overdue: pol-lending-001 |
| Content | Public sources verified against the publisher within 90 days | **PASS** | all verified |
| Incidents | No open report of confidential material shown to a user | **PASS** | 0 open |
| Incidents | Open problem reports | **PASS** | 0 open |
| Audit | Records / active users | **INFO** | 946 audit records; 5 active users |

## 5. Findings to resolve before approval

- **ATTENTION** - No active account still has a published demo password: 4 active: nida, kittipong, admin, somchai
- **ATTENTION** - Environment is production: development
- **ATTENTION** - Metrics endpoint protected by a token: disabled (no monitoring)
- **ATTENTION** - Users must accept the acceptable-use terms: not enforced
- **ATTENTION** - No synthetic sample documents in the index: 6 of 14 documents are samples: replace before production
- **ATTENTION** - Internal policies are within their review date: overdue: pol-lending-001

## 6. Not verified by this document

- penetration test or security review by the bank's security team
- integration with the bank's real identity provider (tested against Keycloak and a simulated provider only)
- legal review of the disclaimer and acceptable-use terms (`config/terms.th.md`)
- DPO decisions: retention periods, approval of the external LLM provider and its contract (zero retention, region)
- confirmation of the evaluation questions by compliance experts; behaviour on real user questions
- capacity beyond the measured single-process figures (`docs/deployment.md`); disaster-recovery drill on production data
- accuracy of the corpus against the publishers' latest texts after the last check date in section 2
