"""Tests ensuring Dockyard does not mutate project repos by default."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


def _run(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> str:
    """Run subprocess command and return stdout."""
    result = subprocess.run(
        command,
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return result.stdout.strip()


def test_save_no_prompt_keeps_repo_working_tree_unchanged(git_repo: Path, tmp_path: Path) -> None:
    """Saving checkpoint should not alter tracked files or git index."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    status_before = _run(["git", "status", "--porcelain"], cwd=git_repo)
    assert status_before == ""

    _run(
        [
            "python3",
            "-m",
            "dockyard",
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Checkpoint objective",
            "--decisions",
            "Decision text",
            "--next-step",
            "Do another thing",
            "--risks",
            "Review infra carefully",
            "--command",
            "pytest -q",
            "--tests-run",
            "--tests-command",
            "pytest -q",
            "--build-ok",
            "--build-command",
            "python -m build",
            "--lint-fail",
            "--smoke-fail",
            "--no-auto-review",
        ],
        cwd=git_repo,
        env=env,
    )

    status_after = _run(["git", "status", "--porcelain"], cwd=git_repo)
    assert status_after == ""


def test_read_only_commands_do_not_modify_repo(git_repo: Path, tmp_path: Path) -> None:
    """Resume/ls/search/review read paths must not mutate repository state."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run(
        [
            "python3",
            "-m",
            "dockyard",
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Read-only command baseline",
            "--decisions",
            "Validate non-mutating command paths",
            "--next-step",
            "Run resume and harbor commands",
            "--risks",
            "None",
            "--command",
            "echo do-not-run",
            "--tests-run",
            "--tests-command",
            "pytest -q",
            "--build-ok",
            "--build-command",
            "echo build",
            "--lint-fail",
            "--smoke-fail",
            "--no-auto-review",
        ],
        cwd=git_repo,
        env=env,
    )

    status_before = _run(["git", "status", "--porcelain"], cwd=git_repo)
    assert status_before == ""

    _run(["python3", "-m", "dockyard", "resume"], cwd=git_repo, env=env)
    _run(["python3", "-m", "dockyard", "ls"], cwd=tmp_path, env=env)
    _run(["python3", "-m", "dockyard", "search", "baseline"], cwd=tmp_path, env=env)
    _run(["python3", "-m", "dockyard", "search", "baseline", "--json"], cwd=tmp_path, env=env)
    _run(["python3", "-m", "dockyard", "review"], cwd=tmp_path, env=env)
    _run(["python3", "-m", "dockyard", "links"], cwd=git_repo, env=env)

    status_after = _run(["git", "status", "--porcelain"], cwd=git_repo)
    assert status_after == ""


def test_review_and_link_commands_do_not_modify_repo(git_repo: Path, tmp_path: Path) -> None:
    """Dockyard metadata mutations must not alter repository working tree."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run(
        [
            "python3",
            "-m",
            "dockyard",
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Mutation command baseline",
            "--decisions",
            "Validate review/link non-interference",
            "--next-step",
            "Run link and review commands",
            "--risks",
            "none",
            "--command",
            "echo noop",
            "--tests-run",
            "--tests-command",
            "pytest -q",
            "--build-ok",
            "--build-command",
            "echo build",
            "--lint-fail",
            "--smoke-fail",
            "--no-auto-review",
        ],
        cwd=git_repo,
        env=env,
    )

    status_before = _run(["git", "status", "--porcelain"], cwd=git_repo)
    assert status_before == ""

    _run(
        ["python3", "-m", "dockyard", "link", "https://example.com/non-interference"],
        cwd=git_repo,
        env=env,
    )
    review_output = _run(
        [
            "python3",
            "-m",
            "dockyard",
            "review",
            "add",
            "--reason",
            "manual",
            "--severity",
            "low",
        ],
        cwd=git_repo,
        env=env,
    )
    review_match = re.search(r"rev_[a-f0-9]+", review_output)
    assert review_match is not None
    _run(
        ["python3", "-m", "dockyard", "review", "done", review_match.group(0)],
        cwd=git_repo,
        env=env,
    )

    status_after = _run(["git", "status", "--porcelain"], cwd=git_repo)
    assert status_after == ""
