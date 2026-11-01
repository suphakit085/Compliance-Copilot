"""Evidence pack for model-risk and AI-governance approval, generated from the running system.

A hand-written approval document drifts from the system it describes. This module builds the
factual parts - versions, thresholds, corpus, evaluation results, live control checks - by reading
the configuration, the database and the stored evaluation results, so the numbers in a submission are
the numbers of the deployment being approved. It states plainly what it checked, what it did not, and
what it found wanting.
"""

from __future__ import annotations

import json
import platform
import subprocess
from dataclasses import dataclass
from datetime import UTC, date, datetime
from importlib import metadata
from pathlib import Path

import yaml
from sqlalchemy import func, select, text

from . import governance, terms
from .config import ROOT, get_settings
from .db import AuditLog, Document, Feedback, User, engine, session
from .features.gap_analysis import GAP_PROMPT_VERSION
from .generation.prompts import ANSWER_PROMPT_VERSION
from .ingestion.pipeline import PIPELINE_VERSION
from .ingestion.updates import STALE_AFTER_DAYS, read_lock, stale_sources

OK, WARN, FAIL, INFO = "PASS", "ATTENTION", "FAIL", "INFO"


@dataclass
class Check:
    area: str
    what: str
    result: str
    detail: str


def _git() -> str:
    try:
        run = lambda *a: subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip()  # noqa: E731
        head = run("rev-parse", "--short", "HEAD")
        dirty = bool(run("status", "--porcelain", "--untracked-files=no"))
        return f"{head}{' (uncommitted changes present)' if dirty else ''}" if head else "unknown"
    except Exception:  # not a git checkout (e.g. inside a container)
        return "unknown"


def _version(pkg: str) -> str:
    try:
        return metadata.version(pkg)
    except metadata.PackageNotFoundError:
        return "not installed"


def _eval_summary(name: str, filename: str) -> dict | None:
    f = ROOT / "eval" / "results" / filename
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def controls() -> list[Check]:
    """Live checks against the running configuration and database."""
    s, out = get_settings(), []

    with engine().connect() as c:
        rls = c.execute(text("SELECT relname, relrowsecurity FROM pg_class WHERE relname IN ('documents','chunks')")).all()
        pol = c.execute(text("SELECT count(*) FROM pg_policies WHERE tablename IN ('documents','chunks')")).scalar_one()
    ok = len(rls) == 2 and all(r[1] for r in rls) and pol >= 2
    out.append(Check("Access control", "Row-level security on documents and chunks (second layer after the SQL filter)",
                     OK if ok else FAIL, f"{pol} policies; RLS on: {', '.join(r[0] for r in rls if r[1]) or 'none'}"))

    from .audit import verify_chain

    chain = verify_chain()
    out.append(Check("Audit", "Hash chain of the audit log verifies", OK if chain["valid"] else FAIL,
                     f"{chain['checked']} records" + ("" if chain["valid"] else f"; broken at id {chain.get('broken_at_id')}")))

    out.append(Check("Authentication", "Single sign-on configured", OK if s.oidc_issuer else WARN,
                     f"issuer {s.oidc_issuer}" if s.oidc_issuer else "only local passwords - acceptable for a pilot, not for production"))
    out.append(Check("Authentication", "Password login", INFO, "enabled" if s.password_login else "disabled (SSO only)"))
    from .security import demo_accounts_with_published_passwords

    demos = demo_accounts_with_published_passwords()
    out.append(Check("Authentication", "No active account still has a published demo password",
                     OK if not demos else (FAIL if s.env == "production" else WARN),
                     "none" if not demos else f"{len(demos)} active: {', '.join(demos)}"))
    out.append(Check("Authentication", f"Lockout after {s.login_max_failures} failures / {s.login_lock_minutes} min; "
                     f"rate limits chat {s.rate_chat_per_min}/min, gap {s.rate_gap_per_10min}/10 min", OK, "configured"))
    out.append(Check("Deployment", "Environment is production", OK if s.env == "production" else WARN, s.env))
    out.append(Check("Deployment", "JWT secret is not the development default", OK if s.jwt_secret != "dev-only-change-me" and len(s.jwt_secret) >= 32 else FAIL,
                     "strong secret set" if len(s.jwt_secret) >= 32 else "default or short"))
    out.append(Check("Operations", "Metrics endpoint protected by a token", OK if s.metrics_token else WARN,
                     "enabled" if s.metrics_token else "disabled (no monitoring)"))

    out.append(Check("Privacy", "Personal data masked before the LLM", OK if s.pii_masking else FAIL, "on" if s.pii_masking else "OFF"))
    out.append(Check("Privacy", "Chat history retention", OK if s.chat_retention_days > 0 else INFO,
                     f"{s.chat_retention_days} days" if s.chat_retention_days else "history disabled"))
    out.append(Check("Use", "Users must accept the acceptable-use terms", OK if s.terms_required else WARN,
                     f"required, version {terms.current_version()}" if s.terms_required else "not enforced"))

    with session() as db:
        docs = db.execute(select(Document)).scalars().all()
        synth = [d.id for d in docs if d.synthetic]
        overdue = [d.id for d in docs if d.source_kind == "internal" and d.governance
                   and governance.review_state({**d.governance, "effective_to": d.effective_to}).state == "overdue"]
        open_reports = db.execute(select(func.count()).select_from(Feedback).where(Feedback.rating < 0, Feedback.status == "open")).scalar_one()
        open_leaks = db.execute(select(func.count()).select_from(Feedback).where(
            Feedback.rating < 0, Feedback.status == "open", Feedback.category == "leak")).scalar_one()
        n_audit = db.execute(select(func.count()).select_from(AuditLog)).scalar_one()
        active_users = db.execute(select(func.count()).select_from(User).where(User.active.is_(True))).scalar_one()
    out.append(Check("Content", "No synthetic sample documents in the index", OK if not synth else WARN,
                     "none" if not synth else f"{len(synth)} of {len(docs)} documents are samples: replace before production"))
    out.append(Check("Content", "Internal policies are within their review date", OK if not overdue else WARN,
                     "all current" if not overdue else f"overdue: {', '.join(overdue)}"))
    stale = stale_sources()
    out.append(Check("Content", f"Public sources verified against the publisher within {STALE_AFTER_DAYS} days", OK if not stale else WARN,
                     "all verified" if not stale else f"not verified: {', '.join(stale)}"))
    out.append(Check("Incidents", "No open report of confidential material shown to a user", OK if not open_leaks else FAIL,
                     f"{open_leaks} open"))
    out.append(Check("Incidents", "Open problem reports", OK if not open_reports else INFO, f"{open_reports} open"))
    out.append(Check("Audit", "Records / active users", INFO, f"{n_audit} audit records; {active_users} active users"))
    return out


def _fmt(v, pct: bool = False) -> str:
    if v is None:
        return "-"
    return f"{v:.1%}" if pct else str(v)


def _evaluation_section() -> list[str]:
    lines = ["| Set | Questions | Expert-confirmed | Retrieval Hit@6 (production) | End-to-end behaviour | Key facts | Leakage | Run |",
             "|---|---|---|---|---|---|---|---|"]
    for name, fn in (("main", "latest.json"), ("holdout", "latest-holdout.json"), ("extended", "latest-extended.json")):
        d = _eval_summary(name, fn)
        if not d:
            lines.append(f"| {name} | - | - | not run | not run | | | |")
            continue
        prod = (d.get("retrieval_ablation") or [{}])[-1]
        e = (d.get("end_to_end") or {}).get("summary", {})
        rv = d.get("review") or {}
        model = (d.get("end_to_end") or {}).get("model") or ""
        lines.append(
            f"| {name} | {d.get('n_questions')} | {rv.get('reviewed', 0)} of {rv.get('total', d.get('n_questions'))} | "
            f"{_fmt(prod.get('hit@6'), True)} | {_fmt(e.get('behaviour_accuracy'), True)} | {_fmt(e.get('key_fact_accuracy'), True)} | "
            f"{e.get('leakage_count', '-')} | {d.get('created_at', '')[:10]} {model} |")
    blind = []
    for label, fn in (("held-out set, first (blind) run", "holdout-blind-run1.json"), ("extended set, first (blind) run", "extended-blind-run1.json")):
        d = _eval_summary(label, fn)
        if d:
            prod = (d.get("retrieval_ablation") or [{}])[-1]
            e = (d.get("end_to_end") or {}).get("summary", {})
            blind.append(f"- {label}: retrieval Hit@6 {_fmt(prod.get('hit@6'), True)}"
                         + (f"; end-to-end behaviour {_fmt(e.get('behaviour_accuracy'), True)}, key facts {_fmt(e.get('key_fact_accuracy'), True)}" if e else ""))
    return lines + ([""] + ["**First runs, before any change in response to them** (the honest estimate for unseen questions):", ""] + blind if blind else [])


def build() -> str:
    s = get_settings()
    now = datetime.now(UTC)
    with session() as db:
        docs = db.execute(select(Document).order_by(Document.source_kind.desc(), Document.id)).scalars().all()
    lock = read_lock()
    L: list[str] = [
        "# Model card and evidence pack - Compliance Copilot",
        "",
        f"Generated {now.isoformat(timespec='seconds')} from the running system. Build: git `{_git()}`; application version "
        f"{_version('compliance-copilot')}; Python {platform.python_version()} on {platform.system()}.",
        "",
        "> This file is produced by `copilot evidence-pack`. It reports what the system *is configured to do* and what its "
        "stored test results *say*; it does not certify either. Section 6 lists what it cannot verify.",
        "",
        "## 1. Components and versions",
        "",
        "| Component | Value |",
        "|---|---|",
        f"| Answer model (chat) | {s.llm_provider}: `{s.gemini_model if s.llm_provider == 'gemini' else s.anthropic_model}` (reasoning effort `{s.answer_effort}`) |",
        f"| Batch model (gap analysis, evaluation) | `{s.gemini_batch_model or s.gemini_model}` |",
        f"| Embeddings | `{s.embedding_model}` ({s.embedding_dim} dimensions), runs locally |",
        f"| Reranker | `{s.reranker_model}`, runs locally |",
        f"| Prompt versions | answer `{ANSWER_PROMPT_VERSION}`, gap analysis `{GAP_PROMPT_VERSION}`; ingestion pipeline `{PIPELINE_VERSION}` |",
        f"| Retrieval | dense top {s.dense_top_k} + lexical top {s.lexical_top_k}, rank fusion, rerank {s.rerank_candidates}, context {s.context_top_n} passages |",
        f"| Abstention | below reranker score {s.abstain_threshold} no LLM call is made; the model must also return `insufficient_evidence` when passages do not answer |",
        f"| Libraries | fastapi {_version('fastapi')}, sqlalchemy {_version('sqlalchemy')}, pgvector {_version('pgvector')}, "
        f"sentence-transformers {_version('sentence-transformers')}, torch {_version('torch')}, google-genai {_version('google-genai')} |",
        "",
        "## 2. Knowledge base",
        "",
        "| Document | Kind | Version / effective | SHA-256 | Class | Owner / approver / status / review due | Checked vs publisher |",
        "|---|---|---|---|---|---|---|",
    ]
    for d in docs:
        g = d.governance or {}
        who = f"{g.get('owner', '-')} / {g.get('approved_by', '-')} / {g.get('status', '-')} / {g.get('review_due', '-')}" if d.source_kind == "internal" else "public source"
        seen = (lock.get(d.id) or {}).get("checked_at") or (lock.get(d.id) or {}).get("retrieved_at") or "-"
        flag = " **(synthetic sample)**" if d.synthetic else ""
        L.append(f"| `{d.id}`{flag} | {d.source_kind} | {d.version or '-'} / {d.effective_from or '-'} | `{(d.sha256 or '')[:12]}` | {d.classification} | {who} | {str(seen)[:10]} |")
    L += ["", "## 3. Evaluation evidence", ""] + _evaluation_section() + [
        "",
        "The `main` set was used to tune the system, and the held-out and extended results above are after fixes made in response to "
        "their first runs, so only the first-run lines are estimates for unseen questions.",
        "",
        "Full reports: `docs/evaluation.md`, `docs/eval-report*.md`. Questions were written by engineers; **an expert-confirmed "
        "count of 0 means no compliance specialist has validated the expected answers yet.**",
        "",
        "## 4. Controls checked against this deployment",
        "",
        "| Area | Control | Result | Detail |",
        "|---|---|---|---|",
    ]
    checks = controls()
    L += [f"| {c.area} | {c.what} | **{c.result}** | {c.detail} |" for c in checks]
    findings = [c for c in checks if c.result in (FAIL, WARN)]
    L += ["", "## 5. Findings to resolve before approval", ""]
    L += [f"- **{c.result}** - {c.what}: {c.detail}" for c in findings] or ["- none"]
    L += [
        "",
        "## 6. Not verified by this document",
        "",
        "- penetration test or security review by the bank's security team",
        "- integration with the bank's real identity provider (tested against Keycloak and a simulated provider only)",
        "- legal review of the disclaimer and acceptable-use terms (`config/terms.th.md`)",
        "- DPO decisions: retention periods, approval of the external LLM provider and its contract (zero retention, region)",
        "- confirmation of the evaluation questions by compliance experts; behaviour on real user questions",
        "- capacity beyond the measured single-process figures (`docs/deployment.md`); disaster-recovery drill on production data",
        "- accuracy of the corpus against the publishers' latest texts after the last check date in section 2",
        "",
    ]
    return "\n".join(L)


def write(out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(), encoding="utf-8", newline="\n")
    return out


__all__ = ["Check", "build", "controls", "write", "date", "yaml"]
