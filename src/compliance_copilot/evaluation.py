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
import statistics
import time
from collections import defaultdict
from datetime import UTC, date, datetime
from typing import Any

import yaml
from sqlalchemy import select, text

from . import llm
from .config import ROOT, get_settings
from .db import User, engine, session
from .generation.citations import _norm
from .retrieval.retriever import Candidate, UserContext, retrieve
from .security import to_context

GOLD = ROOT / "eval" / "golden_set.yaml"
RESULTS = ROOT / "eval" / "results"

ABLATIONS: list[tuple[str, dict[str, Any]]] = [
    ("A. Fixed-size chunks + vector only (baseline)",
     {"strategy": "naive", "use_lexical": False, "use_refs": False, "use_rerank": False}),
    ("B. Structure-aware chunks + vector only",
     {"strategy": "structured", "use_lexical": False, "use_refs": False, "use_rerank": False}),
    ("C. Structure-aware chunks + BM25 only",
     {"strategy": "structured", "use_dense": False, "use_refs": False, "use_rerank": False}),
    ("D. Hybrid (vector + BM25 + references, RRF)",
     {"strategy": "structured", "use_rerank": False}),
    ("E. Hybrid + cross-encoder rerank (production)", {"strategy": "structured"}),
]
ABSTAIN_CATEGORIES = {"out_of_scope", "unanswerable"}


def load_gold() -> list[dict[str, Any]]:
    items = yaml.safe_load(GOLD.read_text(encoding="utf-8"))["items"]
    for it in items:
        if it.get("as_of") and not isinstance(it["as_of"], date):
            it["as_of"] = date.fromisoformat(str(it["as_of"]))
    return items


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


def eval_retrieval(log=print) -> dict[str, Any]:
    items = load_gold()
    users = _users()
    s = get_settings()
    answerable = [it for it in items if it["expect"] == "answer" and it.get("evidence")]
    table = []
    production_scores: dict[str, float] = {}
    for name, cfg in ABLATIONS:
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
            if name.startswith("E."):
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


def eval_end_to_end(limit: int | None = None, log=print) -> dict[str, Any]:
    from .generation.answerer import answer_question

    items = load_gold()[:limit] if limit else load_gold()
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
            "behaviour_ok": ok_behaviour, "key_facts_ok": facts_ok,
            "citation_precision": (len(rel_cited) / len(cited)) if cited and ev else None,
            "citation_recall": (len(ev_covered) / len(ev)) if ev and expect == "answer" else None,
            "quotes_verified": g.get("verified"), "quotes_total": g.get("citations"),
            "support_rate": g.get("support_rate"), "leak": leak,
            "pii_masked": bool(r.pii_masked), "pii_expected": bool(it.get("pii_expected")),
            "latency_ms": r.trace.get("latency_ms"),
            "tokens": (r.trace.get("llm") or {}).get("input_tokens", 0) + (r.trace.get("llm") or {}).get("output_tokens", 0),
            "answer": r.answer[:600],
        }
        rows.append(row)
        log(f"{it['id']:8s} {expect:7s} -> {r.status:22s} ok={ok_behaviour} facts={facts_ok} leak={leak}")

    def mean(key: str, subset=None) -> float | None:
        vals = [x[key] for x in (subset or rows) if x.get(key) is not None]
        vals = [float(v) for v in vals]
        return round(statistics.mean(vals), 3) if vals else None

    answer_rows = [x for x in rows if x["expect"] == "answer"]
    lat = sorted(x["latency_ms"] for x in rows if x["latency_ms"])
    q_total = sum(x["quotes_total"] or 0 for x in rows)
    summary = {
        "behaviour_accuracy": mean("behaviour_ok"),
        "key_fact_accuracy": mean("key_facts_ok", answer_rows),
        "citation_precision": mean("citation_precision"),
        "citation_recall": mean("citation_recall"),
        "quote_verification_rate": round(sum(x["quotes_verified"] or 0 for x in rows) / q_total, 3) if q_total else None,
        "leakage_count": sum(x["leak"] for x in rows),
        "pii_masking_recall": mean("pii_masked", [x for x in rows if x["pii_expected"]]),
        "latency_p50_ms": lat[len(lat) // 2] if lat else None,
        "latency_p95_ms": lat[int(len(lat) * 0.95) - 1] if lat else None,
        "n_evaluated": len(rows),
    }
    by_cat = []
    for cat in sorted({x["category"] for x in rows}):
        sub = [x for x in rows if x["category"] == cat]
        by_cat.append({"category": cat, "n": len(sub), "behaviour_accuracy": mean("behaviour_ok", sub),
                       "key_fact_accuracy": mean("key_facts_ok", sub),
                       "citation_recall": mean("citation_recall", sub)})
    return {"summary": summary, "by_category": by_cat, "rows": rows, "stopped_early": stopped,
            "model": llm.get_provider("batch").model if llm.available() else None}


# ----------------------------------------------------------------------------- report


def run(retrieval: bool = True, end_to_end: bool = True, limit: int | None = None, log=print) -> dict:
    RESULTS.mkdir(parents=True, exist_ok=True)
    latest = RESULTS / "latest.json"
    prev = json.loads(latest.read_text(encoding="utf-8")) if latest.exists() else {}
    out: dict[str, Any] = {
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
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
        r = eval_retrieval(log)
        out["retrieval_ablation"], out["threshold_calibration"] = r["ablation"], r["threshold"]
    elif prev.get("retrieval_ablation"):
        out["retrieval_ablation"] = prev["retrieval_ablation"]
        out["threshold_calibration"] = prev.get("threshold_calibration")
    if end_to_end and llm.available():
        out["end_to_end"] = eval_end_to_end(limit, log)
    elif prev.get("end_to_end"):
        out["end_to_end"] = prev["end_to_end"]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    payload = json.dumps(out, ensure_ascii=False, indent=1, default=str)
    (RESULTS / f"eval-{stamp}.json").write_text(payload, encoding="utf-8")
    latest.write_text(payload, encoding="utf-8")
    (ROOT / "docs" / "eval-report.md").write_text(render_markdown(out), encoding="utf-8")
    return out


def render_markdown(ev: dict[str, Any]) -> str:
    lines = ["# Evaluation report", "", f"Generated {ev['created_at']} · golden set: {ev['n_questions']} questions "
             "(`eval/golden_set.yaml`)", ""]
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
            lines += [f"> Stopped early: {e2e['stopped_early']}", ""]
        lines += ["| metric | value |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in e2e["summary"].items()]
        lines += ["", "| category | n | behaviour | key facts | citation recall |", "|---|---|---|---|---|"]
        for c in e2e["by_category"]:
            lines.append(f"| {c['category']} | {c['n']} | {c['behaviour_accuracy']} | "
                         f"{c['key_fact_accuracy']} | {c['citation_recall']} |")
        fails = [r for r in e2e["rows"] if not r["behaviour_ok"] or r["key_facts_ok"] is False or r["leak"]]
        if fails:
            lines += ["", "### Failures to review", ""]
            for r in fails:
                lines.append(f"- **{r['id']}** expected {r['expect']}, got {r['status']}"
                             f" (key facts: {r['key_facts_ok']}, leak: {r['leak']})")
    return "\n".join(lines) + "\n"
