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
