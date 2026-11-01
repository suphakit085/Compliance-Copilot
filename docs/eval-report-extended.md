# Evaluation report (extended set)

Generated 2026-11-01T17:29:21+00:00 · 146 questions

Expert review: 0 of 146 questions confirmed by a compliance expert (0%); 146 still draft, 0 edited since review, 0 need a fix, 0 rejected. Unreviewed questions were written by engineers from the source text and have not been checked by the compliance team.

## Retrieval ablation (top-6 context, answerable questions)

| config | hit@1 | hit@3 | hit@6 | recall@6 | mrr | leakage | latency_ms |
|---|---|---|---|---|---|---|---|
| A. Fixed-size chunks + vector only (baseline) | 0.336 | 0.445 | 0.516 | 0.512 | 0.401 | 0 | 251 |
| B. Structure-aware chunks + vector only | 0.695 | 0.812 | 0.867 | 0.859 | 0.761 | 0 | 71 |
| C. Structure-aware chunks + BM25 only | 0.477 | 0.695 | 0.766 | 0.758 | 0.587 | 0 | 31 |
| D. Hybrid (vector + BM25 + references, RRF) | 0.633 | 0.82 | 0.859 | 0.855 | 0.726 | 0 | 111 |
| E. Hybrid + cross-encoder rerank | 0.742 | 0.906 | 0.945 | 0.941 | 0.833 | 0 | 572 |
| F. E + glossary expansion + comparison lookup (production) | 0.758 | 0.945 | 0.977 | 0.973 | 0.857 | 0 | 609 |

### Abstention threshold calibration

- current threshold 0.02 → decision accuracy 0.964
- best on this set 0.01 → 0.978
- lowest score of an answerable question: 0.0052; highest score of an out-of-corpus question: 0.3227

## End-to-end (model: gemini-3.1-flash-lite)

| metric | value |
|---|---|
| behaviour_accuracy | 0.945 |
| key_fact_accuracy | 0.938 |
| citation_precision | 0.676 |
| citation_recall | 0.922 |
| quote_verification_rate | 0.959 |
| leakage_count | 0 |
| pii_masking_recall | 1.0 |
| latency_p50_ms | 611 |
| latency_p95_ms | 6102 |
| n_evaluated | 146 |

| category | n | behaviour | key facts | citation recall |
|---|---|---|---|---|
| conflict | 4 | 1.0 | 1.0 | 0.875 |
| explicit_ref | 5 | 1.0 | 1.0 | 1.0 |
| injection | 5 | 1.0 | None | None |
| out_of_scope | 4 | 1.0 | None | None |
| pii | 4 | 1.0 | 1.0 | 1.0 |
| policy | 14 | 1.0 | 1.0 | 1.0 |
| rbac | 6 | 0.667 | 1.0 | 1.0 |
| regulation | 93 | 0.935 | 0.914 | 0.898 |
| unanswerable | 5 | 1.0 | None | None |
| versioning | 6 | 1.0 | 1.0 | 1.0 |

Notes: `citation_precision` counts a cited source as correct only if it contains a gold
evidence string, so legitimate extra citations (e.g. the internal policy cited next to the
law it implements) lower it; `quote_verification_rate` is the faithfulness measure - the
share of cited quotes found verbatim in the cited source.

### Failures to review

- **x-aml-13** expected answer, got unverified (key facts: False, leak: False)
- **x-aml-21** expected answer, got answered (key facts: False, leak: False)
- **x-brc-01** expected answer, got unverified (key facts: False, leak: False)
- **x-brc-02** expected answer, got answered (key facts: False, leak: False)
- **x-rbac-01** expected abstain, got partial (key facts: None, leak: False)
- **x-rbac-03** expected abstain, got partial (key facts: None, leak: False)
- **x-pdpa-02** expected answer, got insufficient_evidence (key facts: False, leak: False)
- **x-pdpa-04** expected answer, got answered (key facts: False, leak: False)
- **x-pdpa-08** expected answer, got unverified (key facts: True, leak: False)
- **x-pdpa-12** expected answer, got insufficient_evidence (key facts: False, leak: False)
- **x-pdpa-14** expected answer, got unverified (key facts: True, leak: False)
- **x-sec-09** expected answer, got answered (key facts: False, leak: False)
