"""Tests for resume command runner."""

from __future__ import annotations

from pathlib import Path

from dockyard.runner import run_commands


def test_run_commands_stops_on_first_failure(tmp_path: Path) -> None:
    """Runner should stop execution sequence at first non-zero exit."""
    marker = tmp_path / "should_not_exist.txt"
    commands = [
        "echo first",
        "false",
        f"echo late > {marker}",
    ]
    success, results = run_commands(commands, cwd=tmp_path)
    assert success is False
    assert results == [("echo first", 0), ("false", 1)]
    assert not marker.exists()


def test_run_commands_executes_all_when_successful(tmp_path: Path) -> None:
    """Runner should execute full command list when all commands pass."""
    marker = tmp_path / "done.txt"
    commands = [
        "echo first",
        f"echo ok > {marker}",
    ]
    success, results = run_commands(commands, cwd=tmp_path)
    assert success is True
    assert results == [("echo first", 0), (f"echo ok > {marker}", 0)]
    assert marker.exists()
