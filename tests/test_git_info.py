"""Tests for git metadata extraction."""

from __future__ import annotations

import subprocess
from pathlib import Path

from dockyard.git_info import detect_repo_root, inspect_repository


def test_detect_repo_root(git_repo: Path) -> None:
    """Repo root should resolve to initialized git directory."""
    nested = git_repo / "a" / "b"
    nested.mkdir(parents=True, exist_ok=True)
    root = detect_repo_root(nested)
    assert root == git_repo


def test_inspect_repository_captures_required_fields(git_repo: Path) -> None:
    """Inspect should include branch, head, and diff details."""
    (git_repo / "feature.py").write_text("print('hello')\n", encoding="utf-8")
    snapshot = inspect_repository(root_override=str(git_repo))
    assert snapshot.root_path == str(git_repo)
    assert snapshot.branch in ("main", "master")
    assert snapshot.repo_id
    assert snapshot.head_sha
    assert snapshot.head_subject == "initial"
    assert snapshot.git_dirty is True
    assert snapshot.diff_files_changed >= 1
    assert "feature.py" in snapshot.touched_files


def test_detached_head_uses_expected_naming(git_repo: Path) -> None:
    """Detached HEAD should map to DETACHED@sha pattern."""
    sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(["git", "checkout", "--detach"], cwd=str(git_repo), check=True, capture_output=True)
    snapshot = inspect_repository(root_override=str(git_repo))
    assert snapshot.branch == f"DETACHED@{sha}"
