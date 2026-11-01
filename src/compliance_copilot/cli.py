"""Command line:  uv run copilot --help"""

from __future__ import annotations

import json
import sys
from datetime import date
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(add_completion=False, help="Compliance Copilot - ingestion, evaluation and ops")
console = Console()

if sys.platform == "win32":  # Thai output on Windows consoles
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]


@app.command()
def fetch(force: bool = False) -> None:
    """Download the public regulation PDFs listed in data/sources.yaml."""
    from .ingestion.pipeline import fetch_sources

    fetch_sources(force=force, log=console.print)


@app.command()
def ingest(
    doc: Annotated[list[str] | None, typer.Option(help="Only these document ids")] = None,
    force: bool = False,
    ocr: Annotated[bool, typer.Option(help="OCR scanned pages with the LLM")] = True,
) -> None:
    """Parse, chunk, embed and index documents into Postgres."""
    from .ingestion.pipeline import ingest as run

    run(doc_ids=doc, force=force, use_ocr=ocr, log=console.print)


@app.command("add-policy")
def add_policy(
    file: Annotated[str, typer.Argument(help="Policy markdown file with governance front matter")],
    replace: Annotated[bool, typer.Option(help="Overwrite an existing document with the same id")] = False,
    dry_run: Annotated[bool, typer.Option(help="Validate and preview the clauses only")] = False,
) -> None:
    """Add an approved internal policy: validates owner/approver/review dates, then indexes it."""
    from pathlib import Path

    from .governance import GovernanceError
    from .ingestion.updates import add_policy as run

    try:
        run(Path(file), replace=replace, dry_run=dry_run, log=console.print)
    except GovernanceError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e


@app.command("check-updates")
def check_updates() -> None:
    """Compare the public sources with their pinned hashes (exit 1 if any changed). Read-only."""
    from .ingestion.updates import check_updates as run

    results = run(log=console.print)
    changed = [r.doc_id for r in results if r.status == "changed"]
    if changed:
        console.print(f"[yellow]changed at the publisher: {', '.join(changed)} - review, then "
                      "`copilot fetch --force` and `copilot ingest`[/yellow]")
        raise typer.Exit(1)


@app.command()
def governance() -> None:
    """Corpus governance report: reviews due, drafts, sample documents, sources not re-verified."""
    from . import governance as gov
    from .ingestion.loaders import load_manifest
    from .ingestion.updates import stale_sources

    table = Table(title="Internal documents")
    for c in ("id", "owner", "approved by", "status", "review due", "state"):
        table.add_column(c)
    specs = [s for s in load_manifest() if s.source_kind == "internal"]
    for s in specs:
        r = gov.review_state(s.meta)
        colour = {"overdue": "red", "due_soon": "yellow"}.get(r.state, "green")
        table.add_row(s.id, str(s.meta.get("owner")), str(s.meta.get("approved_by")), str(s.meta.get("status")),
                      str(s.meta.get("review_due")), f"[{colour}]{r.state}[/{colour}]")
    console.print(table)
    sample = sum(bool(s.meta.get("synthetic")) for s in specs)
    if sample:
        console.print(f"[yellow]{sample} of {len(specs)} internal documents are synthetic samples - "
                      "replace them with approved policies before production[/yellow]")
    if stale := stale_sources():
        console.print(f"[yellow]not verified against the publisher for >{90} days: {', '.join(stale)} "
                      "(run `copilot check-updates`)[/yellow]")


@app.command("create-user")
def create_user(
    username: str,
    role: Annotated[str, typer.Option(help="employee | compliance_officer | auditor | admin")] = "admin",
    department: str = "it",
    clearance: Annotated[str, typer.Option(help="public | internal | confidential | restricted")] = "restricted",
    display_name: Annotated[str | None, typer.Option()] = None,
    update: Annotated[bool, typer.Option(help="Change an existing user (e.g. reset the password)")] = False,
    password: Annotated[str, typer.Option(prompt=True, hide_input=True, confirmation_prompt=True)] = "",
) -> None:
    """Create a local account, e.g. the first admin of a production deployment."""
    from .security import create_user as run

    try:
        run(username, display_name or username, role, department, clearance, password, update=update)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    console.print(f"user {username} saved ({role}, {clearance})")


@app.command("seed-users")
def seed_users() -> None:
    """Create/update demo users from config/users.yaml."""
    from .security import seed_users as run

    console.print(f"seeded {run()} users")


@app.command()
def setup() -> None:
    """One-shot local setup: schema, users, fetch and ingest."""
    from .db import init_db

    init_db()
    seed_users()
    fetch()
    ingest()


@app.command()
def ask(
    question: str,
    user: str = "nida",
    as_of: Annotated[str | None, typer.Option(help="YYYY-MM-DD")] = None,
    show_sources: bool = True,
) -> None:
    """Ask a question from the terminal as a given demo user."""
    from sqlalchemy import select

    from .db import User, session
    from .generation.answerer import answer_question
    from .security import to_context

    with session() as db:
        u = db.execute(select(User).where(User.username == user)).scalar_one()
        ctx = to_context(u)
    r = answer_question(question, ctx, as_of=date.fromisoformat(as_of) if as_of else None)
    console.rule(f"[bold]{r.status}[/bold]  (audit #{r.audit_id})")
    console.print(r.answer)
    for n in r.notices:
        console.print(f"[yellow]⚠ {n}[/yellow]")
    if show_sources:
        t = Table("id", "source", "score", "cited")
        for s in r.sources:
            t.add_row(s.id, f"{s.short_title} — {s.label}", f"{s.rerank_score or 0:.3f}", "✔" if s.cited else "")
        console.print(t)


@app.command()
def gap(policy: str, user: str = "nida", out: Annotated[str | None, typer.Option(help="Write Markdown report")] = None) -> None:
    """Run policy gap analysis for an internal policy id."""
    from sqlalchemy import select

    from .db import User, session
    from .features.gap_analysis import analyze_policy, report_markdown
    from .security import to_context

    with session() as db:
        ctx = to_context(db.execute(select(User).where(User.username == user)).scalar_one())
    report = analyze_policy(policy, ctx)
    md = report_markdown(report)
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(md)
        console.print(f"wrote {out}")
    else:
        console.print(md)


@app.command("eval")
def evaluate(
    retrieval: bool = True,
    e2e: Annotated[bool, typer.Option("--e2e/--no-e2e", help="End-to-end eval (uses the LLM)")] = True,
    limit: int | None = None,
    fresh: Annotated[bool, typer.Option("--fresh", help="Re-evaluate questions already done")] = False,
    eval_set: Annotated[str, typer.Option("--set", help="main | holdout")] = "main",
    min_hit6: Annotated[float | None, typer.Option(help="Exit 1 if production Hit@6 is below this (CI gate)")] = None,
) -> None:
    """Run the golden-set evaluation and write eval/results + docs/eval-report.md.

    End-to-end results accumulate across runs, so a quota-limited run resumes with the
    questions not evaluated yet."""
    from .evaluation import run

    out = run(retrieval=retrieval, end_to_end=e2e, limit=limit, log=console.print, resume=not fresh, eval_set=eval_set)
    if out.get("end_to_end"):
        e = out["end_to_end"]
        console.print_json(json.dumps(e["summary"], ensure_ascii=False))
        if e.get("remaining"):
            console.print(f"[yellow]{len(e['remaining'])} questions not evaluated yet - run again to continue[/yellow]")
    console.print(f"report: docs/eval-report{'' if eval_set == 'main' else '-' + eval_set}.md")
    if min_hit6 is not None and retrieval:
        prod = out["retrieval_ablation"][-1]
        ok = prod["hit@6"] >= min_hit6
        console.print(f"[{'green' if ok else 'red'}]quality gate: production Hit@6 {prod['hit@6']:.3f} "
                      f"{'>=' if ok else '<'} {min_hit6}[/]")
        if not ok:
            raise typer.Exit(1)


@app.command()
def bench(
    concurrency: Annotated[str, typer.Option(help="Comma-separated numbers of simultaneous users")] = "1,4,8",
    requests: Annotated[int, typer.Option(help="Questions per level")] = 24,
    user: str = "nida",
) -> None:
    """Capacity check of the local part of answering (embedding + hybrid search + rerank; no LLM)."""
    import statistics
    import time
    from concurrent.futures import ThreadPoolExecutor

    import yaml
    from sqlalchemy import select

    from .config import ROOT
    from .db import User, session
    from .retrieval import models
    from .retrieval.retriever import retrieve
    from .security import to_context

    with session() as db:
        ctx = to_context(db.execute(select(User).where(User.username == user)).scalar_one())
    items = yaml.safe_load((ROOT / "eval" / "golden_set.yaml").read_text(encoding="utf-8"))["items"]
    questions = [i["question"] for i in items]
    device = models._device()
    t0 = time.perf_counter()
    models.embed_query("warm up")
    models.rerank("warm up", ["warm up"])
    load_s = time.perf_counter() - t0
    torch = None
    if device == "cuda":
        import torch

        torch.cuda.reset_peak_memory_stats()

    table = Table(title=f"Retrieval capacity on {device} (model load {load_s:.1f}s)")
    for col in ("users", "requests", "p50 ms", "p95 ms", "throughput /s"):
        table.add_column(col, justify="right")
    for level in [int(x) for x in concurrency.split(",")]:
        qs = [questions[i % len(questions)] for i in range(requests)]

        def one(q: str) -> float:
            s = time.perf_counter()
            retrieve(q, ctx)
            return (time.perf_counter() - s) * 1000

        start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=level) as pool:
            lat = sorted(pool.map(one, qs))
        wall = time.perf_counter() - start
        p95 = lat[min(len(lat) - 1, int(round(0.95 * len(lat))) - 1)]
        table.add_row(str(level), str(requests), f"{statistics.median(lat):.0f}", f"{p95:.0f}", f"{requests / wall:.2f}")
    console.print(table)
    if torch is not None:
        console.print(f"peak GPU memory for the two models + inference: {torch.cuda.max_memory_allocated() / 2**30:.2f} GiB")


@app.command("purge-history")
def purge_history() -> None:
    """Delete conversations older than the retention period (COPILOT_CHAT_RETENTION_DAYS)."""
    from .history import purge_expired

    console.print(f"purged {purge_expired()} conversations")


@app.command("audit-verify")
def audit_verify() -> None:
    """Re-walk the audit hash chain and report tampering."""
    from .audit import verify_chain

    console.print(verify_chain())


if __name__ == "__main__":
    app()
