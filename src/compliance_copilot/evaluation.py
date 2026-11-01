"""Offline evaluation against eval/golden_set.yaml.

* ``retrieval`` (no LLM, cheap, deterministic): Hit@k / Recall@k / MRR for an ablation
  of chunking and retrieval configurations, access-control leakage, and calibration
  of the abstention threshold.
* ``end_to_end`` (LLM): behaviour accuracy (answer / abstain / block), key-fact
  accuracy, citation precision & recall, quote verification, leakage, PII masking.

Metrics are deterministic wherever possible (evidence strings and key facts instead
of an LLM judge) so results are reproducible and cheap to re-run; LLM calls go
through the disk cache, so an interrupted run resumes where it stopped.
"""

from __future__ import annotations

import json
import math
import statistics
import time
from collections import defaultdict
from datetime import UTC, date, datetime
from typing import Any

import yaml
from sqlalchemy import select, text

from . import llm, review
from .config import ROOT, get_settings
from .db import User, engine, session
from .generation.citations import _norm
from .retrieval.retriever import Candidate, UserContext, retrieve
from .security import to_context

GOLD = ROOT / "eval" / "golden_set.yaml"
RESULTS = ROOT / "eval" / "results"
EVAL_SETS = {"main": "golden_set.yaml", "holdout": "holdout_set.yaml", "extended": "extended"}  # "extended" = eval/extended/*.yaml
_ONLY_REVIEWED = False  # restrict to questions an expert has confirmed (see review.py)


def use_set(name: str) -> str:
    """Point the evaluation at another question set; returns the file-name suffix for results."""
    global GOLD
    GOLD = ROOT / "eval" / EVAL_SETS[name]
    return "" if name == "main" else f"-{name}"

ABLATIONS: list[tuple[str, dict[str, Any]]] = [
    ("A. Fixed-size chunks + vector only (baseline)",
     {"strategy": "naive", "use_lexical": False, "use_refs": False, "use_rerank": False, "use_glossary": False, "compare": False}),
    ("B. Structure-aware chunks + vector only",
     {"strategy": "structured", "use_lexical": False, "use_refs": False, "use_rerank": False, "use_glossary": False, "compare": False}),
    ("C. Structure-aware chunks + BM25 only",
     {"strategy": "structured", "use_dense": False, "use_refs": False, "use_rerank": False, "use_glossary": False, "compare": False}),
    ("D. Hybrid (vector + BM25 + references, RRF)",
     {"strategy": "structured", "use_rerank": False, "use_glossary": False, "compare": False}),
    ("E. Hybrid + cross-encoder rerank", {"strategy": "structured", "use_glossary": False, "compare": False}),
    ("F. E + glossary expansion + comparison lookup (production)", {"strategy": "structured"}),
]
ABSTAIN_CATEGORIES = {"out_of_scope", "unanswerable"}


def raw_gold() -> list[dict[str, Any]]:
    """Every question of the selected set, whatever its review status."""
    files = sorted(GOLD.glob("*.yaml")) if GOLD.is_dir() else [GOLD]
    items = [it for f in files for it in yaml.safe_load(f.read_text(encoding="utf-8"))["items"]]
    for it in items:
        if it.get("as_of") and not isinstance(it["as_of"], date):
            it["as_of"] = date.fromisoformat(str(it["as_of"]))
    return items


def load_gold() -> list[dict[str, Any]]:
    """The questions that count: rejected ones never do, and with ``reviewed_only`` only
    expert-confirmed ones."""
    return review.apply(raw_gold(), _ONLY_REVIEWED)


def _users() -> dict[str, UserContext]:
    with session() as db:
        return {u.username: to_context(u) for u in db.execute(select(User)).scalars()}


def _relevant(doc_id: str, chunk_text: str, ev: dict[str, str]) -> bool:
    return doc_id == ev["doc"] and _norm(ev["text"]) in _norm(chunk_text)


def validate_gold() -> list[str]:
    """Every evidence string must exist in its document - otherwise the gold is wrong."""
    problems = []
    with engine().connect() as c:
        for it in load_gold():
            for ev in it.get("evidence", []):
                rows = c.execute(
                    text("SELECT text FROM chunks WHERE document_id=:d AND strategy='structured'"),
                    {"d": ev["doc"]},
                ).fetchall()
                if not any(_norm(ev["text"]) in _norm(r.text) for r in rows):
                    problems.append(f"{it['id']}: evidence not found in {ev['doc']}: {ev['text'][:60]}")
    return problems


# ---------------------------------------------------------------------------- retrieval


def _rank_metrics(cands: list[Candidate], evidence: list[dict], k_values=(1, 3, 6)) -> dict[str, float]:
    first_rank = None
    covered_at: dict[int, set[int]] = {k: set() for k in k_values}
    for rank, c in enumerate(cands, 1):
        hits = {i for i, ev in enumerate(evidence) if _relevant(c.document_id, c.text, ev)}
        if hits and first_rank is None:
            first_rank = rank
        for k in k_values:
            if rank <= k:
                covered_at[k] |= hits
    out = {f"hit@{k}": float(bool(covered_at[k])) for k in k_values}
    out.update({f"recall@{k}": len(covered_at[k]) / len(evidence) for k in k_values})
    out["mrr"] = 1.0 / first_rank if first_rank else 0.0
    return out


def eval_retrieval(log=print, production_only: bool = False) -> dict[str, Any]:
    """Retrieval metrics per configuration. ``production_only`` skips the ablation (a CI gate on
    slow CPU runners only needs the configuration that ships)."""
    items = load_gold()
    users = _users()
    s = get_settings()
    answerable = [it for it in items if it["expect"] == "answer" and it.get("evidence")]
    table = []
    production_scores: dict[str, float] = {}
    for name, cfg in (ABLATIONS[-1:] if production_only else ABLATIONS):
        agg: dict[str, list[float]] = defaultdict(list)
        leaks = 0
        t0 = time.perf_counter()
        for it in items:
            if it["expect"] == "block":
                continue
            r = retrieve(it["question"], users[it["user"]], it.get("as_of"), top_n=s.context_top_n, **cfg)
            if any(c.document_id in it.get("forbidden_docs", []) for c in r.candidates):
                leaks += 1
            if it in answerable:
                for k, v in _rank_metrics(r.candidates, it["evidence"]).items():
                    agg[k].append(v)
            if name.startswith("F."):
                production_scores[it["id"]] = r.top_score
        n_queries = sum(1 for it in items if it["expect"] != "block")
        row = {"config": name, **{k: round(statistics.mean(v), 3) for k, v in agg.items()},
               "leakage": leaks,
               "latency_ms": round((time.perf_counter() - t0) * 1000 / n_queries)}
        table.append(row)
        log(f"{name}: hit@6={row['hit@6']} recall@6={row['recall@6']} mrr={row['mrr']} leaks={leaks}")
    return {"ablation": table, "threshold": _calibrate(items, production_scores, s.abstain_threshold)}


def _calibrate(items: list[dict], scores: dict[str, float], current: float) -> dict[str, Any]:
    """Pick the abstention threshold that best separates answerable from out-of-corpus questions."""
    pos = [scores[it["id"]] for it in items if it["expect"] == "answer" and it["id"] in scores]
    neg = [scores[it["id"]] for it in items if it["category"] in ABSTAIN_CATEGORIES and it["id"] in scores]

    def acc(t: float) -> float:
        return (sum(p >= t for p in pos) + sum(n < t for n in neg)) / (len(pos) + len(neg))

    grid = [round(x * 0.01, 2) for x in range(1, 91)]
    best = max(grid, key=lambda t: (acc(t), -abs(t - current)))
    return {
        "current": current, "current_accuracy": round(acc(current), 3),
        "best": best, "best_accuracy": round(acc(best), 3),
        "min_answerable_score": round(min(pos), 4) if pos else None,
        "max_out_of_corpus_score": round(max(neg), 4) if neg else None,
        "answerable_below_current": sorted(
            it["id"] for it in items if it["expect"] == "answer" and scores.get(it["id"], 1) < current),
    }


# --------------------------------------------------------------------------- end to end


def _contains_any(answer: str, alts: list[str]) -> bool:
    a = _norm(answer).lower()
    return any(_norm(x).lower() in a for x in alts)


def eval_end_to_end(limit: int | None = None, log=print, skip: set[str] | None = None) -> dict[str, Any]:
    from .generation.answerer import answer_question

    items = [it for it in load_gold() if it["id"] not in (skip or set())]
    items = items[:limit] if limit else items
    users = _users()
    rows = []
    stopped = None
    for it in items:
        try:
            r = answer_question(it["question"], users[it["user"]], None, it.get("as_of"),
                                log=False, llm_purpose="batch")
        except llm.QuotaExceeded as e:
            stopped = str(e)[:200]
            break
        if r.trace.get("llm_error") and "quota" in r.trace["llm_error"].lower():
            stopped = r.trace["llm_error"][:200]
            break
        expect = it["expect"]
        ok_behaviour = (
            (expect == "answer" and r.status in ("answered", "partial"))
            or (expect == "abstain" and r.status in ("insufficient_evidence", "out_of_scope"))
            or (expect == "block" and r.status == "blocked")
        )
        cited = [s for s in r.sources if s.cited]
        ev = it.get("evidence", [])
        rel_cited = [s for s in cited if any(_relevant(s.document_id, s.text, e) for e in ev)]
        ev_covered = [e for e in ev if any(_relevant(s.document_id, s.text, e) for s in cited)]
        leak = any(s.document_id in it.get("forbidden_docs", []) for s in r.sources)
        facts_ok = all(_contains_any(r.answer, alts) for alts in it.get("key_facts", [])) \
            if expect == "answer" else None
        g = r.grounding or {}
        row = {
            "id": it["id"], "category": it["category"], "expect": expect, "status": r.status,
            "evaluated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "behaviour_ok": ok_behaviour, "key_facts_ok": facts_ok,
            "citation_precision": (len(rel_cited) / len(cited)) if cited and ev else None,
            "citation_recall": (len(ev_covered) / len(ev)) if ev and expect == "answer" else None,
            "quotes_verified": g.get("verified"), "quotes_total": g.get("citations"),
            "support_rate": g.get("support_rate"), "leak": leak,
            "pii_masked": bool(r.pii_masked), "pii_expected": bool(it.get("pii_expected")),
            "latency_ms": r.trace.get("latency_ms"),
            "tokens": (r.trace.get("llm") or {}).get("input_tokens", 0) + (r.trace.get("llm") or {}).get("output_tokens", 0),
            "answer": r.answer[:4000],  # kept whole enough to re-score key facts later
        }
        rows.append(row)
        log(f"{it['id']:8s} {expect:7s} -> {r.status:22s} ok={ok_behaviour} facts={facts_ok} leak={leak}")

    return {"rows": rows, "stopped_early": stopped,
            "model": llm.get_provider("batch").model if llm.available() else None}


def _percentile(values: list[int], q: float) -> int | None:
    """Nearest-rank percentile (well defined for small samples)."""
    if not values:
        return None
    v = sorted(values)
    return v[max(0, math.ceil(q * len(v)) - 1)]


def summarize_e2e(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def mean(key: str, subset=None) -> float | None:
        vals = [float(x[key]) for x in (rows if subset is None else subset) if x.get(key) is not None]
        return round(statistics.mean(vals), 3) if vals else None

    answer_rows = [x for x in rows if x["expect"] == "answer"]
    lat = [x["latency_ms"] for x in rows if x.get("latency_ms")]
    q_total = sum(x["quotes_total"] or 0 for x in rows)
    summary = {
        "behaviour_accuracy": mean("behaviour_ok"),
        "key_fact_accuracy": mean("key_facts_ok", answer_rows),
        "citation_precision": mean("citation_precision"),
        "citation_recall": mean("citation_recall"),
        "quote_verification_rate": round(sum(x["quotes_verified"] or 0 for x in rows) / q_total, 3) if q_total else None,
        "leakage_count": sum(x["leak"] for x in rows),
        "pii_masking_recall": mean("pii_masked", [x for x in rows if x["pii_expected"]]),
        "latency_p50_ms": _percentile(lat, 0.5),
        "latency_p95_ms": _percentile(lat, 0.95),
        "n_evaluated": len(rows),
    }
    by_cat = []
    for cat in sorted({x["category"] for x in rows}):
        sub = [x for x in rows if x["category"] == cat]
        by_cat.append({"category": cat, "n": len(sub), "behaviour_accuracy": mean("behaviour_ok", sub),
                       "key_fact_accuracy": mean("key_facts_ok", sub),
                       "citation_recall": mean("citation_recall", sub)})
    return {"summary": summary, "by_category": by_cat}


def merge_e2e(prev: dict[str, Any] | None, new: dict[str, Any]) -> dict[str, Any]:
    """Accumulate results across runs: a quota-limited run only replaces the questions it
    actually re-evaluated, so evaluation can be completed over several days."""
    order = {it["id"]: i for i, it in enumerate(load_gold())}
    merged = {r["id"]: r for r in (prev or {}).get("rows", []) if r["id"] in order}
    merged.update({r["id"]: r for r in new["rows"]})
    rows = sorted(merged.values(), key=lambda r: order[r["id"]])
    return {**summarize_e2e(rows), "rows": rows, "stopped_early": new["stopped_early"],
            "model": new["model"] or (prev or {}).get("model"),
            "remaining": [i for i in order if i not in merged]}


# ----------------------------------------------------------------------------- report


def run(retrieval: bool = True, end_to_end: bool = True, limit: int | None = None, log=print,
        resume: bool = True, eval_set: str = "main", reviewed_only: bool = False,
        production_only: bool = False) -> dict:
    global _ONLY_REVIEWED
    suffix = use_set(eval_set)
    _ONLY_REVIEWED = reviewed_only
    RESULTS.mkdir(parents=True, exist_ok=True)
    latest = RESULTS / f"latest{suffix}.json"
    prev = json.loads(latest.read_text(encoding="utf-8")) if latest.exists() else {}
    out: dict[str, Any] = {
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "eval_set": eval_set,
        "reviewed_only": reviewed_only,
        "review": review.summary(raw_gold()),
        "n_questions": len(load_gold()),
        "settings": {k: v for k, v in get_settings().model_dump().items()
                     if k in ("embedding_model", "reranker_model", "dense_top_k", "lexical_top_k",
                              "rerank_candidates", "context_top_n", "abstain_threshold",
                              "chunk_max_chars", "gemini_model", "gemini_batch_model")},
    }
    problems = validate_gold()
    out["gold_problems"] = problems
    for p in problems:
        log(f"GOLD PROBLEM: {p}")
    if retrieval:
        r = eval_retrieval(log, production_only)
        out["retrieval_ablation"], out["threshold_calibration"] = r["ablation"], r["threshold"]
    elif prev.get("retrieval_ablation"):
        out["retrieval_ablation"] = prev["retrieval_ablation"]
        out["threshold_calibration"] = prev.get("threshold_calibration")
    if end_to_end and llm.available():
        done = {r["id"] for r in (prev.get("end_to_end") or {}).get("rows", [])} if resume else set()
        if done:
            log(f"resuming: {len(done)} questions already evaluated (use --fresh to redo them)")
        out["end_to_end"] = merge_e2e(prev.get("end_to_end"), eval_end_to_end(limit, log, skip=done))
    elif prev.get("end_to_end"):
        out["end_to_end"] = prev["end_to_end"]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    payload = json.dumps(out, ensure_ascii=False, indent=1, default=str)
    (RESULTS / f"eval{suffix}-{stamp}.json").write_text(payload, encoding="utf-8")
    latest.write_text(payload, encoding="utf-8")
    (ROOT / "docs" / f"eval-report{suffix}.md").write_text(render_markdown(out), encoding="utf-8")
    return out


def render_markdown(ev: dict[str, Any]) -> str:
    names = {"holdout": " (held-out set)", "extended": " (extended set)"}
    title = "Evaluation report" + names.get(ev.get("eval_set"), "")
    lines = [f"# {title}", "", f"Generated {ev['created_at']} · {ev['n_questions']} questions"
             + (" (expert-reviewed only)" if ev.get("reviewed_only") else ""), ""]
    if rv := ev.get("review"):
        lines += [f"Expert review: {rv['reviewed']} of {rv['total']} questions confirmed by a compliance expert "
                  f"({rv['reviewed_share']:.0%}); {rv['draft']} still draft, {rv['stale']} edited since review, "
                  f"{rv['needs_fix']} need a fix, {rv['rejected']} rejected. Unreviewed questions were written by "
                  "engineers from the source text and have not been checked by the compliance team.", ""]
    if ev.get("retrieval_ablation"):
        cols = ["config", "hit@1", "hit@3", "hit@6", "recall@6", "mrr", "leakage", "latency_ms"]
        lines += ["## Retrieval ablation (top-6 context, answerable questions)", "",
                  "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        for row in ev["retrieval_ablation"]:
            lines.append("| " + " | ".join(str(row.get(c, "")) for c in cols) + " |")
        t = ev.get("threshold_calibration") or {}
        lines += ["", "### Abstention threshold calibration", "",
                  f"- current threshold {t.get('current')} → decision accuracy {t.get('current_accuracy')}",
                  f"- best on this set {t.get('best')} → {t.get('best_accuracy')}",
                  f"- lowest score of an answerable question: {t.get('min_answerable_score')}; "
                  f"highest score of an out-of-corpus question: {t.get('max_out_of_corpus_score')}", ""]
    e2e = ev.get("end_to_end")
    if e2e:
        lines += ["## End-to-end (model: " + str(e2e.get("model")) + ")", ""]
        if e2e.get("stopped_early"):
            lines += [f"> Last run stopped early: {e2e['stopped_early'][:160]}", ""]
        if e2e.get("remaining"):
            lines += [f"> Not yet evaluated ({len(e2e['remaining'])}): {', '.join(e2e['remaining'])}", ""]
        lines += ["| metric | value |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in e2e["summary"].items()]
        lines += ["", "| category | n | behaviour | key facts | citation recall |", "|---|---|---|---|---|"]
        for c in e2e["by_category"]:
            lines.append(f"| {c['category']} | {c['n']} | {c['behaviour_accuracy']} | "
                         f"{c['key_fact_accuracy']} | {c['citation_recall']} |")
        lines += [
            "",
            "Notes: `citation_precision` counts a cited source as correct only if it contains a gold",
            "evidence string, so legitimate extra citations (e.g. the internal policy cited next to the",
            "law it implements) lower it; `quote_verification_rate` is the faithfulness measure - the",
            "share of cited quotes found verbatim in the cited source.",
        ]
        fails = [r for r in e2e["rows"] if not r["behaviour_ok"] or r["key_facts_ok"] is False or r["leak"]]
        if fails:
            lines += ["", "### Failures to review", ""]
            for r in fails:
                lines.append(f"- **{r['id']}** expected {r['expect']}, got {r['status']}"
                             f" (key facts: {r['key_facts_ok']}, leak: {r['leak']})")
    return "\n".join(lines) + "\n"
