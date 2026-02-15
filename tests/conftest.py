"""Test fixtures for Dockyard."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def _run(command: list[str], cwd: Path) -> str:
    """Run subprocess command and return stripped stdout."""
    result = subprocess.run(
        command,
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """Create an initialized git repository with one commit."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    _run(["git", "init"], cwd=repo)
    _run(["git", "config", "user.email", "dockyard@example.com"], cwd=repo)
    _run(["git", "config", "user.name", "Dockyard Test"], cwd=repo)
    _run(["git", "remote", "add", "origin", "git@github.com:org/sample.git"], cwd=repo)
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _run(["git", "add", "README.md"], cwd=repo)
    _run(["git", "commit", "-m", "initial"], cwd=repo)
    return repo
