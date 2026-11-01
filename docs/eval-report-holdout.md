# Evaluation report (held-out set)

Generated 2026-11-01T10:28:12+00:00 · golden set: 21 questions (`eval/golden_set.yaml`)

## Retrieval ablation (top-6 context, answerable questions)

| config | hit@1 | hit@3 | hit@6 | recall@6 | mrr | leakage | latency_ms |
|---|---|---|---|---|---|---|---|
| A. Fixed-size chunks + vector only (baseline) | 0.412 | 0.529 | 0.647 | 0.618 | 0.485 | 0 | 1014 |
| B. Structure-aware chunks + vector only | 0.529 | 0.647 | 0.765 | 0.735 | 0.618 | 0 | 70 |
| C. Structure-aware chunks + BM25 only | 0.529 | 0.588 | 0.588 | 0.588 | 0.559 | 0 | 22 |
| D. Hybrid (vector + BM25 + references, RRF) | 0.529 | 0.647 | 0.706 | 0.706 | 0.603 | 0 | 96 |
| E. Hybrid + cross-encoder rerank | 0.647 | 0.882 | 0.882 | 0.882 | 0.755 | 0 | 844 |
| F. E + glossary expansion + comparison lookup (production) | 0.706 | 0.941 | 1.0 | 1.0 | 0.824 | 0 | 806 |

### Abstention threshold calibration

- current threshold 0.02 → decision accuracy 0.947
- best on this set 0.02 → 0.947
- lowest score of an answerable question: 0.0395; highest score of an out-of-corpus question: 0.1713

## End-to-end (model: gemini-3.1-flash-lite)

| metric | value |
|---|---|
| behaviour_accuracy | 1.0 |
| key_fact_accuracy | 1.0 |
| citation_precision | 0.515 |
| citation_recall | 1.0 |
| quote_verification_rate | 0.98 |
| leakage_count | 0 |
| pii_masking_recall | 1.0 |
| latency_p50_ms | 631 |
| latency_p95_ms | 7210 |
| n_evaluated | 21 |

| category | n | behaviour | key facts | citation recall |
|---|---|---|---|---|
| conflict | 1 | 1.0 | 1.0 | 1.0 |
| explicit_ref | 1 | 1.0 | 1.0 | 1.0 |
| injection | 1 | 1.0 | None | None |
| out_of_scope | 1 | 1.0 | None | None |
| pii | 1 | 1.0 | 1.0 | 1.0 |
| policy | 2 | 1.0 | 1.0 | 1.0 |
| rbac | 1 | 1.0 | None | None |
| regulation | 10 | 1.0 | 1.0 | 1.0 |
| unanswerable | 1 | 1.0 | None | None |
| versioning | 2 | 1.0 | 1.0 | 1.0 |

Notes: `citation_precision` counts a cited source as correct only if it contains a gold
evidence string, so legitimate extra citations (e.g. the internal policy cited next to the
law it implements) lower it; `quote_verification_rate` is the faithfulness measure - the
share of cited quotes found verbatim in the cited source.
