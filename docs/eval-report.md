# Evaluation report

Generated 2026-10-31T21:23:30+00:00 · golden set: 51 questions (`eval/golden_set.yaml`)

## Retrieval ablation (top-6 context, answerable questions)

| config | hit@1 | hit@3 | hit@6 | recall@6 | mrr | leakage | latency_ms |
|---|---|---|---|---|---|---|---|
| A. Fixed-size chunks + vector only (baseline) | 0.35 | 0.5 | 0.575 | 0.537 | 0.434 | 0 | 611 |
| B. Structure-aware chunks + vector only | 0.625 | 0.85 | 0.9 | 0.887 | 0.742 | 0 | 72 |
| C. Structure-aware chunks + BM25 only | 0.5 | 0.725 | 0.825 | 0.787 | 0.622 | 0 | 28 |
| D. Hybrid (vector + BM25 + references, RRF) | 0.625 | 0.85 | 0.9 | 0.887 | 0.74 | 0 | 113 |
| E. Hybrid + cross-encoder rerank (production) | 0.85 | 0.9 | 0.975 | 0.963 | 0.891 | 0 | 795 |

### Abstention threshold calibration

- current threshold 0.15 → decision accuracy 1.0
- best on this set 0.15 → 1.0
- lowest score of an answerable question: 0.2424; highest score of an out-of-corpus question: 0.0077

