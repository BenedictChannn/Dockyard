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


def test_checkpoint_to_jsonable_project_name_optional() -> None:
    """Project name should remain optional in JSON projection output."""
    checkpoint = Checkpoint(
        id="cp_model_2",
        repo_id="repo_id",
        branch="main",
        created_at="2026-01-01T00:00:00+00:00",
        objective="Objective",
        decisions="Decisions",
        next_steps=["step1"],
        risks_review="Risk",
        resume_commands=[],
        git_dirty=False,
        head_sha="abc123",
        head_subject="subject",
        recent_commits=[],
        diff_files_changed=0,
        diff_insertions=0,
        diff_deletions=0,
        touched_files=[],
        diff_stat_text="",
        verification=VerificationState(),
        tags=[],
    )
    payload = checkpoint_to_jsonable(checkpoint=checkpoint)
    assert payload["project_name"] is None
    assert payload["open_reviews"] == 0


def test_checkpoint_to_jsonable_includes_full_expected_shape() -> None:
    """JSON projection should expose stable top-level keys and list payloads."""
    checkpoint = Checkpoint(
        id="cp_model_shape",
        repo_id="repo_shape",
        branch="feature/model-shape",
        created_at="2026-01-01T00:00:00+00:00",
        objective="Shape objective",
        decisions="Shape decisions",
        next_steps=["step-a", "step-b"],
        risks_review="shape risk",
        resume_commands=["echo one", "echo two"],
        git_dirty=False,
        head_sha="abc123",
        head_subject="shape subject",
        recent_commits=["abc123 shape subject"],
        diff_files_changed=2,
        diff_insertions=5,
        diff_deletions=3,
        touched_files=["a.py", "b.py"],
        diff_stat_text="2 files changed",
        verification=VerificationState(
            tests_run=False,
            build_ok=False,
            lint_ok=True,
            smoke_ok=False,
        ),
        tags=["mvp", "release"],
    )

    payload = checkpoint_to_jsonable(
        checkpoint=checkpoint,
        open_reviews=1,
        project_name="shape-repo",
    )

    assert set(payload.keys()) == {
        "id",
        "repo_id",
        "branch",
        "created_at",
        "objective",
        "decisions",
        "next_steps",
        "risks_review",
        "resume_commands",
        "git_dirty",
        "head_sha",
        "head_subject",
        "recent_commits",
        "diff_files_changed",
        "diff_insertions",
        "diff_deletions",
        "touched_files",
        "diff_stat_text",
        "verification",
        "tags",
        "open_reviews",
        "project_name",
    }
    assert payload["next_steps"] == ["step-a", "step-b"]
    assert payload["resume_commands"] == ["echo one", "echo two"]
    assert payload["touched_files"] == ["a.py", "b.py"]
    assert payload["tags"] == ["mvp", "release"]
    assert payload["verification"]["lint_ok"] is True
