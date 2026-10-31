# Evaluation report

Generated 2026-10-31T21:56:49+00:00 · golden set: 51 questions (`eval/golden_set.yaml`)

## Retrieval ablation (top-6 context, answerable questions)

| config | hit@1 | hit@3 | hit@6 | recall@6 | mrr | leakage | latency_ms |
|---|---|---|---|---|---|---|---|
| A. Fixed-size chunks + vector only (baseline) | 0.35 | 0.5 | 0.575 | 0.537 | 0.434 | 0 | 535 |
| B. Structure-aware chunks + vector only | 0.625 | 0.85 | 0.9 | 0.887 | 0.742 | 0 | 73 |
| C. Structure-aware chunks + BM25 only | 0.5 | 0.725 | 0.825 | 0.787 | 0.622 | 0 | 29 |
| D. Hybrid (vector + BM25 + references, RRF) | 0.625 | 0.85 | 0.9 | 0.887 | 0.74 | 0 | 109 |
| E. Hybrid + cross-encoder rerank | 0.85 | 0.9 | 0.975 | 0.963 | 0.891 | 0 | 680 |
| F. E + domain glossary expansion (production) | 0.85 | 0.925 | 1.0 | 0.988 | 0.9 | 0 | 523 |

### Abstention threshold calibration

- current threshold 0.15 → decision accuracy 1.0
- best on this set 0.15 → 1.0
- lowest score of an answerable question: 0.2424; highest score of an out-of-corpus question: 0.0077

## End-to-end (model: gemini-3.5-flash)

> Stopped early: Gemini daily quota exhausted for gemini-3.5-flash: You exceeded your current quota, please check your plan and billing details. For more information on this error, head to: https://ai.google.dev/gemin

| metric | value |
|---|---|
| behaviour_accuracy | 0.909 |
| key_fact_accuracy | 1.0 |
| citation_precision | 0.65 |
| citation_recall | 0.909 |
| quote_verification_rate | 1.0 |
| leakage_count | 0 |
| pii_masking_recall | None |
| latency_p50_ms | 10071 |
| latency_p95_ms | 14755 |
| n_evaluated | 11 |

| category | n | behaviour | key facts | citation recall |
|---|---|---|---|---|
| regulation | 11 | 0.909 | 1.0 | 0.909 |

Notes: `citation_precision` counts a cited source as correct only if it contains a gold
evidence string, so legitimate extra citations (e.g. the internal policy cited next to the
law it implements) lower it; `quote_verification_rate` is the faithfulness measure - the
share of cited quotes found verbatim in the cited source.

### Failures to review

- **pdpa-03** expected answer, got insufficient_evidence (key facts: True, leak: False)
