"""Tests for git metadata extraction."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from dockyard.errors import NotGitRepositoryError
from dockyard.git_info import detect_repo_root, inspect_repository


def test_detect_repo_root(git_repo: Path) -> None:
    """Repo root should resolve to initialized git directory."""
    nested = git_repo / "a" / "b"
    nested.mkdir(parents=True, exist_ok=True)
    root = detect_repo_root(nested)
    assert root == git_repo


def test_detect_repo_root_raises_for_non_repo(tmp_path: Path) -> None:
    """Repo detection should raise helpful error outside git repos."""
    with pytest.raises(NotGitRepositoryError):
        detect_repo_root(tmp_path)


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


def test_repo_id_falls_back_to_path_hash_without_remote(git_repo: Path) -> None:
    """Repo id should remain stable when origin remote is missing."""
    subprocess.run(
        ["git", "remote", "remove", "origin"],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )
    first = inspect_repository(root_override=str(git_repo))
    second = inspect_repository(root_override=str(git_repo))
    assert first.remote_url is None
    assert first.repo_id == second.repo_id


def test_repo_id_uses_non_origin_remote_when_available(git_repo: Path) -> None:
    """Repo id should use an available non-origin remote URL when present."""
    subprocess.run(
        ["git", "remote", "remove", "origin"],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )
    upstream_url = "https://example.com/team/upstream.git"
    subprocess.run(
        ["git", "remote", "add", "upstream", upstream_url],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )

    snapshot = inspect_repository(root_override=str(git_repo))

    assert snapshot.remote_url == upstream_url
    assert snapshot.repo_id == hashlib.sha1(upstream_url.encode("utf-8")).hexdigest()[:16]


def test_repo_id_non_origin_remote_selection_is_deterministic(git_repo: Path) -> None:
    """Repo id fallback should select remotes deterministically."""
    subprocess.run(
        ["git", "remote", "remove", "origin"],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )
    alpha_url = "https://example.com/team/alpha.git"
    zeta_url = "https://example.com/team/zeta.git"
    subprocess.run(
        ["git", "remote", "add", "zeta", zeta_url],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "remote", "add", "alpha", alpha_url],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )

    snapshot = inspect_repository(root_override=str(git_repo))

    assert snapshot.remote_url == alpha_url
    assert snapshot.repo_id == hashlib.sha1(alpha_url.encode("utf-8")).hexdigest()[:16]


def test_repo_id_prefers_origin_remote_when_multiple_remotes_exist(git_repo: Path) -> None:
    """Repo id should continue preferring origin when multiple remotes exist."""
    origin_url = subprocess.run(
        ["git", "config", "--get", "remote.origin.url"],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "remote", "add", "upstream", "https://example.com/team/upstream.git"],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )

    snapshot = inspect_repository(root_override=str(git_repo))

    assert snapshot.remote_url == origin_url
    assert snapshot.repo_id == hashlib.sha1(origin_url.encode("utf-8")).hexdigest()[:16]
