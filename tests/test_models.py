"""Tests for model helpers."""

from __future__ import annotations

from dockyard.models import Checkpoint, VerificationState, checkpoint_to_jsonable


def test_checkpoint_to_jsonable_includes_project_name_and_verification() -> None:
    """JSON projection should include nested verification and project name."""
    checkpoint = Checkpoint(
        id="cp_model",
        repo_id="repo_id",
        branch="main",
        created_at="2026-01-01T00:00:00+00:00",
        objective="Objective",
        decisions="Decisions",
        next_steps=["step1"],
        risks_review="Risk",
        resume_commands=["echo hi"],
        git_dirty=True,
        head_sha="abc123",
        head_subject="subject",
        recent_commits=["abc123 subject"],
        diff_files_changed=1,
        diff_insertions=2,
        diff_deletions=1,
        touched_files=["a.py"],
        diff_stat_text="1 file changed",
        verification=VerificationState(
            tests_run=True,
            tests_command="pytest -q",
            tests_timestamp="2026-01-01T00:00:00+00:00",
            build_ok=True,
            build_command="echo build",
            build_timestamp="2026-01-01T00:00:00+00:00",
            lint_ok=False,
            smoke_ok=False,
        ),
        tags=["mvp"],
    )
    payload = checkpoint_to_jsonable(
        checkpoint=checkpoint,
        open_reviews=2,
        project_name="my-repo",
    )
    assert payload["project_name"] == "my-repo"
    assert payload["open_reviews"] == 2
    assert payload["verification"]["tests_run"] is True
    assert payload["verification"]["build_ok"] is True
