"""Tests for git metadata extraction."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from dockyard import git_info as git_info_module
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


def test_repo_id_ignores_empty_non_origin_remote_urls(git_repo: Path) -> None:
    """Repo id fallback should skip remotes with empty configured URLs."""
    subprocess.run(
        ["git", "remote", "remove", "origin"],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "remote", "add", "alpha", "https://example.com/team/alpha.git"],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )
    # Simulate malformed config where remote URL exists but is blank.
    subprocess.run(
        ["git", "config", "remote.alpha.url", ""],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )
    beta_url = "https://example.com/team/beta.git"
    subprocess.run(
        ["git", "remote", "add", "beta", beta_url],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )

    snapshot = inspect_repository(root_override=str(git_repo))

    assert snapshot.remote_url == beta_url
    assert snapshot.repo_id == hashlib.sha1(beta_url.encode("utf-8")).hexdigest()[:16]


def test_remote_url_returns_none_when_remote_listing_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Remote resolver should return None when git remote listing fails."""

    def _failing_run_git(args: list[str], cwd: Path) -> str:
        raise subprocess.CalledProcessError(returncode=1, cmd=["git", *args])

    monkeypatch.setattr(git_info_module, "_run_git", _failing_run_git)

    assert git_info_module._remote_url(Path("/tmp/repo")) is None


def test_remote_url_skips_failed_remote_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Remote resolver should continue when one remote URL lookup fails."""
    alpha_lookup_count = 0

    def _run_git_with_failed_alpha(args: list[str], cwd: Path) -> str:
        nonlocal alpha_lookup_count
        if args == ["config", "--get", "remote.origin.url"]:
            raise subprocess.CalledProcessError(returncode=1, cmd=["git", *args])
        if args == ["remote"]:
            return " alpha \n\nbeta\nalpha"
        if args == ["config", "--get", "remote.alpha.url"]:
            alpha_lookup_count += 1
            raise subprocess.CalledProcessError(returncode=1, cmd=["git", *args])
        if args == ["config", "--get", "remote.beta.url"]:
            return "https://example.com/team/beta.git"
        raise AssertionError(f"Unexpected git args: {args}")

    monkeypatch.setattr(git_info_module, "_run_git", _run_git_with_failed_alpha)

    assert git_info_module._remote_url(Path("/tmp/repo")) == "https://example.com/team/beta.git"
    assert alpha_lookup_count == 1


def test_remote_url_skips_duplicate_origin_lookup_when_origin_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Remote resolver should not re-query origin in fallback remote loop."""
    origin_lookup_count = 0

    def _run_git_with_blank_origin(args: list[str], cwd: Path) -> str:
        nonlocal origin_lookup_count
        if args == ["config", "--get", "remote.origin.url"]:
            origin_lookup_count += 1
            return ""
        if args == ["remote"]:
            return "origin\nbeta"
        if args == ["config", "--get", "remote.beta.url"]:
            return "https://example.com/team/beta.git"
        raise AssertionError(f"Unexpected git args: {args}")

    monkeypatch.setattr(git_info_module, "_run_git", _run_git_with_blank_origin)

    assert git_info_module._remote_url(Path("/tmp/repo")) == "https://example.com/team/beta.git"
    assert origin_lookup_count == 1


def test_remote_url_returns_none_for_blank_remote_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Remote resolver should ignore blank remote-name entries."""

    def _run_git_with_blank_remote_names(args: list[str], cwd: Path) -> str:
        if args == ["config", "--get", "remote.origin.url"]:
            raise subprocess.CalledProcessError(returncode=1, cmd=["git", *args])
        if args == ["remote"]:
            return " \n\n"
        raise AssertionError(f"Unexpected git args: {args}")

    monkeypatch.setattr(git_info_module, "_run_git", _run_git_with_blank_remote_names)

    assert git_info_module._remote_url(Path("/tmp/repo")) is None


def test_remote_url_returns_none_when_only_origin_is_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Remote resolver should return None when origin exists but URL is blank."""
    origin_lookup_count = 0

    def _run_git_origin_blank_only(args: list[str], cwd: Path) -> str:
        nonlocal origin_lookup_count
        if args == ["config", "--get", "remote.origin.url"]:
            origin_lookup_count += 1
            return ""
        if args == ["remote"]:
            return "origin"
        raise AssertionError(f"Unexpected git args: {args}")

    monkeypatch.setattr(git_info_module, "_run_git", _run_git_origin_blank_only)

    assert git_info_module._remote_url(Path("/tmp/repo")) is None
    assert origin_lookup_count == 1


def test_remote_url_sorts_fallback_names_case_insensitively(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Remote resolver should sort fallback names case-insensitively."""

    def _run_git_case_insensitive_sort(args: list[str], cwd: Path) -> str:
        if args == ["config", "--get", "remote.origin.url"]:
            raise subprocess.CalledProcessError(returncode=1, cmd=["git", *args])
        if args == ["remote"]:
            return "Zeta\nalpha"
        if args == ["config", "--get", "remote.alpha.url"]:
            return "https://example.com/team/alpha.git"
        if args == ["config", "--get", "remote.Zeta.url"]:
            raise AssertionError("Case-insensitive ordering should resolve alpha first")
        raise AssertionError(f"Unexpected git args: {args}")

    monkeypatch.setattr(git_info_module, "_run_git", _run_git_case_insensitive_sort)

    assert git_info_module._remote_url(Path("/tmp/repo")) == "https://example.com/team/alpha.git"


def test_remote_url_tie_breaks_case_insensitive_name_collisions_deterministically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Remote resolver should deterministically order case-colliding names."""

    def _run_git_case_collision(args: list[str], cwd: Path) -> str:
        if args == ["config", "--get", "remote.origin.url"]:
            raise subprocess.CalledProcessError(returncode=1, cmd=["git", *args])
        if args == ["remote"]:
            return "alpha\nAlpha"
        if args == ["config", "--get", "remote.Alpha.url"]:
            return "https://example.com/team/alpha-upper.git"
        if args == ["config", "--get", "remote.alpha.url"]:
            return "https://example.com/team/alpha-lower.git"
        raise AssertionError(f"Unexpected git args: {args}")

    monkeypatch.setattr(git_info_module, "_run_git", _run_git_case_collision)

    assert git_info_module._remote_url(Path("/tmp/repo")) == "https://example.com/team/alpha-upper.git"
