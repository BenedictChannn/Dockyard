"""Tests for checkpoint markdown render/parse round-trip behavior."""

from __future__ import annotations

from dockyard.models import Checkpoint, VerificationState
from dockyard.storage.markdown_store import parse_checkpoint_markdown, render_checkpoint_markdown


def test_markdown_round_trip_sections() -> None:
    """Rendered checkpoint markdown should be parseable for key sections."""
    checkpoint = Checkpoint(
        id="cp_round",
        repo_id="repo_a",
        branch="feature/roundtrip",
        created_at="2026-02-15T00:00:00+00:00",
        objective="Improve markdown parser reliability",
        decisions="Use lightweight parser for own template output.",
        next_steps=["Add round-trip test", "Wire parser utility"],
        risks_review="Low risk, parser constrained to known format",
        resume_commands=["pytest -q", "python3 -m dockyard ls"],
        git_dirty=True,
        head_sha="abc123",
        head_subject="subject",
        recent_commits=["abc subject"],
        diff_files_changed=2,
        diff_insertions=20,
        diff_deletions=5,
        touched_files=["dockyard/storage/markdown_store.py"],
        diff_stat_text="1 file changed, 20 insertions(+), 5 deletions(-)",
        verification=VerificationState(
            tests_run=True,
            tests_command="pytest -q",
            tests_timestamp="2026-02-15T00:00:00+00:00",
            build_ok=False,
            lint_ok=False,
            smoke_ok=False,
        ),
        tags=["mvp"],
    )
    markdown = render_checkpoint_markdown(checkpoint)
    parsed = parse_checkpoint_markdown(markdown)

    assert parsed["objective"] == checkpoint.objective
    assert parsed["decisions"] == checkpoint.decisions
    assert parsed["next_steps"] == checkpoint.next_steps
    assert parsed["risks_review"] == checkpoint.risks_review
    assert parsed["resume_commands"] == checkpoint.resume_commands
