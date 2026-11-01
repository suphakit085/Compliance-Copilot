# Evaluation report

Generated 2026-11-01T10:00:34+00:00 · golden set: 51 questions (`eval/golden_set.yaml`)

## Retrieval ablation (top-6 context, answerable questions)

| config | hit@1 | hit@3 | hit@6 | recall@6 | mrr | leakage | latency_ms |
|---|---|---|---|---|---|---|---|
| A. Fixed-size chunks + vector only (baseline) | 0.35 | 0.5 | 0.575 | 0.537 | 0.434 | 0 | 513 |
| B. Structure-aware chunks + vector only | 0.625 | 0.85 | 0.9 | 0.887 | 0.742 | 0 | 75 |
| C. Structure-aware chunks + BM25 only | 0.5 | 0.725 | 0.825 | 0.787 | 0.622 | 0 | 29 |
| D. Hybrid (vector + BM25 + references, RRF) | 0.625 | 0.85 | 0.9 | 0.887 | 0.74 | 0 | 111 |
| E. Hybrid + cross-encoder rerank | 0.85 | 0.9 | 0.975 | 0.963 | 0.891 | 0 | 697 |
| F. E + glossary expansion + comparison lookup (production) | 0.85 | 0.925 | 1.0 | 1.0 | 0.9 | 0 | 572 |

### Abstention threshold calibration

- current threshold 0.15 → decision accuracy 1.0
- best on this set 0.15 → 1.0
- lowest score of an answerable question: 0.2424; highest score of an out-of-corpus question: 0.0077

## End-to-end (model: gemini-3.1-flash-lite)

| metric | value |
|---|---|
| behaviour_accuracy | 1.0 |
| key_fact_accuracy | 1.0 |
| citation_precision | 0.631 |
| citation_recall | 0.988 |
| quote_verification_rate | 0.974 |
| leakage_count | 0 |
| pii_masking_recall | 1.0 |
| latency_p50_ms | 3497 |
| latency_p95_ms | 8765 |
| n_evaluated | 51 |

| category | n | behaviour | key facts | citation recall |
|---|---|---|---|---|
| conflict | 3 | 1.0 | 1.0 | 0.833 |
| explicit_ref | 3 | 1.0 | 1.0 | 1.0 |
| injection | 3 | 1.0 | None | None |
| ocr | 1 | 1.0 | 1.0 | 1.0 |
| out_of_scope | 2 | 1.0 | None | None |
| pii | 1 | 1.0 | 1.0 | 1.0 |
| policy | 4 | 1.0 | 1.0 | 1.0 |
| rbac | 4 | 1.0 | 1.0 | 1.0 |
| regulation | 25 | 1.0 | 1.0 | 1.0 |
| unanswerable | 3 | 1.0 | None | None |
| versioning | 2 | 1.0 | 1.0 | 1.0 |

Notes: `citation_precision` counts a cited source as correct only if it contains a gold
evidence string, so legitimate extra citations (e.g. the internal policy cited next to the
law it implements) lower it; `quote_verification_rate` is the faithfulness measure - the
share of cited quotes found verbatim in the cited source.
