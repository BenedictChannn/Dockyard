"""Rich rendering helpers for Dockyard command output."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from dockyard.models import Checkpoint


def _display_berth_label(row: dict[str, Any]) -> str:
    """Return berth label fallback chain for render rows."""
    for key in ("berth_name", "repo_id"):
        value = row.get(key)
        if value is not None:
            compact = " ".join(str(value).split())
            if compact:
                return compact[:120]
    return "(unknown)"


def _preview_text(value: Any, max_length: int) -> str:
    """Return compact, single-line preview text bounded by max length."""
    text = str(value) if value is not None else ""
    compact = " ".join(text.split())
    return compact[:max_length]


def _label_text(value: Any, max_length: int) -> str:
    """Return compact label text with unknown fallback."""
    preview = _preview_text(value, max_length)
    return preview if preview else "(unknown)"


def _coerce_text_items(value: Any) -> list[str]:
    """Coerce mixed values to a list of text items."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, tuple | set):
        return [str(item) for item in value]
    return [str(value)]


def format_age(timestamp_iso: Any) -> str:
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
        (
            "Project/Branch: "
            f"{_label_text(project_name, 120)} / {_label_text(checkpoint.branch, 120)}"
        ),
        f"Last Checkpoint: {checkpoint.created_at} ({format_age(checkpoint.created_at)} ago)",
        f"Objective: {_preview_text(checkpoint.objective, 200)}",
        "Next Steps:",
    ]
    next_steps = _coerce_text_items(checkpoint.next_steps)
    if next_steps:
        summary_lines.extend(
            [
                f"  {index + 1}. {_preview_text(step, 200)}"
                for index, step in enumerate(next_steps)
            ]
        )
    else:
        summary_lines.append("  (none recorded)")
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

    touched_files = _coerce_text_items(checkpoint.touched_files)
    touched = "\n".join(f"- {_preview_text(path, 240)}" for path in touched_files[:20]) or "(none)"
    console.print(Panel.fit(touched, title="Touched Files", border_style="magenta"))

    if checkpoint.diff_stat_text is None:
        diff_text = "(no diff)"
    else:
        diff_text = str(checkpoint.diff_stat_text).strip() or "(no diff)"
    console.print(Panel.fit(diff_text, title="Diff Stat", border_style="green"))

    resume_commands = _coerce_text_items(checkpoint.resume_commands)
    if resume_commands:
        commands = "\n".join(f"$ {command}" for command in resume_commands)
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
        berth = _display_berth_label(row)
        branch = row.get("branch", "")
        status = row.get("status", "unknown")
        next_steps = _coerce_text_items(row.get("next_steps"))
        objective = row.get("objective") or ""
        if not isinstance(objective, str):
            objective = str(objective)
        if next_steps:
            next_step = next_steps[0]
        else:
            next_step = objective
        table.add_row(
            str(berth),
            _label_text(branch, 120),
            status_badge.get(str(status), str(status)),
            format_age(row.get("updated_at")),
            _preview_text(next_step, 60),
            str(row.get("open_review_count", 0)),
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
        berth = _display_berth_label(row)
        branch = row.get("branch", "")
        created_at = row.get("created_at", "")
        snippet = row.get("snippet") or ""
        if not isinstance(snippet, str):
            snippet = str(snippet)
        table.add_row(
            str(berth),
            _label_text(branch, 120),
            _preview_text(created_at, 120),
            _preview_text(snippet, 120),
        )
    console.print(table)
