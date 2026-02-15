"""Tests ensuring Dockyard does not mutate project repos by default."""

from __future__ import annotations

import os
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
