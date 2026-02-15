"""Utilities for executing resume commands."""

from __future__ import annotations

import subprocess
from pathlib import Path


def run_commands(commands: list[str], cwd: str | Path) -> tuple[bool, list[tuple[str, int]]]:
    """Run commands sequentially and stop on first failure.

    Args:
        commands: Shell commands to execute.
        cwd: Working directory in which commands should be executed.

    Returns:
        Tuple of:
            - success boolean
            - list of (command, exit_code) for executed commands
    """
    results: list[tuple[str, int]] = []
    working_dir = Path(cwd)
    for command in commands:
        completed = subprocess.run(
            command,
            cwd=str(working_dir),
            shell=True,
            check=False,
        )
        results.append((command, completed.returncode))
        if completed.returncode != 0:
            return False, results
    return True, results
