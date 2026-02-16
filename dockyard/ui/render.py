"""Rich rendering helpers for Dockyard command output."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from dockyard.models import Checkpoint


def format_age(timestamp_iso: str) -> str:
    """Return compact human-readable age string for timestamp."""
    try:
        then = datetime.fromisoformat(timestamp_iso)
    except (TypeError, ValueError):
        return "unknown"
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    delta = now - then
    seconds = max(0, int(delta.total_seconds()))
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h"
    days = hours // 24
    return f"{days}d"


def verification_summary(checkpoint: Checkpoint) -> str:
    """Build concise verification summary text."""
    verification = checkpoint.verification
    tests = "yes" if verification.tests_run else "no"
    build = "yes" if verification.build_ok else "no"
    lint = "yes" if verification.lint_ok else "no"
    return f"tests:{tests} build:{build} lint:{lint}"


def print_resume(
    console: Console,
    checkpoint: Checkpoint,
    open_reviews: int,
    project_name: str,
) -> None:
    """Render resume output with required top-lines summary.

    Args:
        console: Rich console instance.
        checkpoint: Checkpoint being resumed.
        open_reviews: Open review count for the slip.
        project_name: Human-readable berth/project label.
    """
    summary_lines = [
        f"Project/Branch: {project_name} / {checkpoint.branch}",
        f"Last Checkpoint: {checkpoint.created_at} ({format_age(checkpoint.created_at)} ago)",
        f"Objective: {checkpoint.objective}",
        "Next Steps:",
    ]
    summary_lines.extend(
        [f"  {index + 1}. {step}" for index, step in enumerate(checkpoint.next_steps)]
    )
    summary_lines.append(f"Open Reviews: {open_reviews}")
    summary_lines.append(f"Verification: {verification_summary(checkpoint)}")
    console.print("\n".join(summary_lines))

    console.print(
        Panel.fit(
            checkpoint.decisions or "(none)",
            title="Decisions / Findings",
            border_style="cyan",
        )
    )
    console.print(
        Panel.fit(
            checkpoint.risks_review or "(none)",
            title="Risks / Review Needed",
            border_style="yellow",
        )
    )

    touched = "\n".join(f"- {path}" for path in checkpoint.touched_files[:20]) or "(none)"
    console.print(Panel.fit(touched, title="Touched Files", border_style="magenta"))

    diff_text = checkpoint.diff_stat_text.strip() or "(no diff)"
    console.print(Panel.fit(diff_text, title="Diff Stat", border_style="green"))

    if checkpoint.resume_commands:
        commands = "\n".join(f"$ {command}" for command in checkpoint.resume_commands)
    else:
        commands = "(no commands recorded)"
    console.print(Panel.fit(commands, title="Resume Commands", border_style="blue"))


def print_harbor(console: Console, rows: list[dict[str, Any]]) -> None:
    """Render harbor (dock ls) table."""
    table = Table(title="Dockyard Harbor")
    table.add_column("Berth")
    table.add_column("Branch")
    table.add_column("Status")
    table.add_column("Age")
    table.add_column("Next Step")
    table.add_column("Open Reviews", justify="right")

    status_badge = {"green": "[green]G[/green]", "yellow": "[yellow]Y[/yellow]", "red": "[red]R[/red]"}
    for row in rows:
        next_step = row["next_steps"][0] if row["next_steps"] else row["objective"][:60]
        table.add_row(
            row["berth_name"],
            row["branch"],
            status_badge.get(row["status"], row["status"]),
            format_age(row["updated_at"]),
            next_step,
            str(row["open_review_count"]),
        )
    console.print(table)


def print_search(console: Console, rows: list[dict[str, Any]]) -> None:
    """Render search result table."""
    if not rows:
        console.print("No checkpoint matches found.")
        return
    table = Table(title="Dockyard Search Results")
    table.add_column("Berth")
    table.add_column("Branch")
    table.add_column("Timestamp")
    table.add_column("Snippet")
    for row in rows:
        snippet = row.get("snippet") or ""
        if not isinstance(snippet, str):
            snippet = str(snippet)
        table.add_row(
            row.get("berth_name", row["repo_id"]),
            row["branch"],
            row["created_at"],
            snippet[:120],
        )
    console.print(table)
