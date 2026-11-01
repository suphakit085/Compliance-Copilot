# Evaluation report (extended set)

Generated 2026-11-01T16:22:59+00:00 · 146 questions

Expert review: 0 of 146 questions confirmed by a compliance expert (0%); 146 still draft, 0 edited since review, 0 need a fix, 0 rejected. Unreviewed questions were written by engineers from the source text and have not been checked by the compliance team.

## Retrieval ablation (top-6 context, answerable questions)

| config | hit@1 | hit@3 | hit@6 | recall@6 | mrr | leakage | latency_ms |
|---|---|---|---|---|---|---|---|
| A. Fixed-size chunks + vector only (baseline) | 0.336 | 0.445 | 0.516 | 0.512 | 0.401 | 0 | 318 |
| B. Structure-aware chunks + vector only | 0.695 | 0.812 | 0.859 | 0.855 | 0.759 | 0 | 73 |
| C. Structure-aware chunks + BM25 only | 0.477 | 0.688 | 0.758 | 0.754 | 0.584 | 0 | 30 |
| D. Hybrid (vector + BM25 + references, RRF) | 0.633 | 0.812 | 0.852 | 0.852 | 0.722 | 0 | 106 |
| E. Hybrid + cross-encoder rerank | 0.742 | 0.898 | 0.938 | 0.938 | 0.829 | 0 | 564 |
| F. E + glossary expansion + comparison lookup (production) | 0.719 | 0.891 | 0.922 | 0.922 | 0.81 | 0 | 605 |

### Abstention threshold calibration

- current threshold 0.02 → decision accuracy 0.949
- best on this set 0.01 → 0.971
- lowest score of an answerable question: 0.0029; highest score of an out-of-corpus question: 0.3227

