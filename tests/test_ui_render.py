"""Unit tests for Rich rendering helpers."""

from __future__ import annotations

from rich.console import Console

from dockyard.models import Checkpoint, VerificationState
from dockyard.ui.render import format_age, print_search, verification_summary


def _checkpoint() -> Checkpoint:
    """Create minimal checkpoint fixture for rendering tests."""
    return Checkpoint(
        id="cp_ui_1",
        repo_id="repo_ui",
        branch="main",
        created_at="2026-01-01T00:00:00+00:00",
        objective="Objective",
        decisions="Decisions",
        next_steps=["step"],
        risks_review="risks",
        resume_commands=[],
        git_dirty=False,
        head_sha="abc",
        head_subject="subject",
        recent_commits=[],
        diff_files_changed=0,
        diff_insertions=0,
        diff_deletions=0,
        touched_files=[],
        diff_stat_text="",
        verification=VerificationState(tests_run=True, build_ok=False, lint_ok=True),
        tags=[],
    )


def test_format_age_returns_unknown_for_invalid_timestamp() -> None:
    """Invalid timestamps should render as unknown age."""
    assert format_age("not-a-timestamp") == "unknown"


def test_verification_summary_uses_yes_no_markers() -> None:
    """Verification summary should map booleans to yes/no values."""
    assert verification_summary(_checkpoint()) == "tests:yes build:no lint:yes"


def test_print_search_empty_state_message() -> None:
    """Empty search result rendering should show informative message."""
    console = Console(record=True, width=120)
    print_search(console, [])
    output = console.export_text()
    assert "No checkpoint matches found." in output
