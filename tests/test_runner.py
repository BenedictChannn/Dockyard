"""Tests for resume command runner."""

from __future__ import annotations

from pathlib import Path

import pytest

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


def test_run_commands_empty_sequence_is_success(tmp_path: Path) -> None:
    """Runner should treat an empty command list as successful no-op."""
    success, results = run_commands([], cwd=tmp_path)
    assert success is True
    assert results == []


def test_run_commands_all_blank_sequence_is_success(tmp_path: Path) -> None:
    """Runner should treat all-blank commands as successful no-op."""
    success, results = run_commands(["", "   ", "\t"], cwd=tmp_path)
    assert success is True
    assert results == []


def test_run_commands_executes_relative_commands_in_provided_cwd(tmp_path: Path) -> None:
    """Runner should execute shell commands from the provided working directory."""
    command = "pwd > cwd_marker.txt"
    success, results = run_commands([command], cwd=tmp_path)

    assert success is True
    assert results == [(command, 0)]
    marker = tmp_path / "cwd_marker.txt"
    assert marker.exists()
    assert marker.read_text(encoding="utf-8").strip() == str(tmp_path)


def test_run_commands_accepts_string_cwd(tmp_path: Path) -> None:
    """Runner should accept cwd provided as string path."""
    command = "pwd > cwd_string_marker.txt"
    success, results = run_commands([command], cwd=str(tmp_path))

    assert success is True
    assert results == [(command, 0)]
    marker = tmp_path / "cwd_string_marker.txt"
    assert marker.exists()
    assert marker.read_text(encoding="utf-8").strip() == str(tmp_path)


def test_run_commands_accepts_cwd_with_spaces(tmp_path: Path) -> None:
    """Runner should execute commands when cwd contains spaces."""
    spaced_dir = tmp_path / "space dir"
    spaced_dir.mkdir(parents=True, exist_ok=True)
    command = "pwd > cwd_space_marker.txt"

    success, results = run_commands([command], cwd=spaced_dir)

    assert success is True
    assert results == [(command, 0)]
    marker = spaced_dir / "cwd_space_marker.txt"
    assert marker.exists()
    assert marker.read_text(encoding="utf-8").strip() == str(spaced_dir)


def test_run_commands_ignores_blank_commands(tmp_path: Path) -> None:
    """Runner should skip blank command entries while executing meaningful ones."""
    marker = tmp_path / "blank_skip_marker.txt"
    command = f"echo ok > {marker}"

    success, results = run_commands(["", "   ", command], cwd=tmp_path)

    assert success is True
    assert results == [(command, 0)]
    assert marker.exists()


def test_run_commands_normalizes_command_whitespace_in_results(tmp_path: Path) -> None:
    """Runner should trim surrounding whitespace before executing commands."""
    marker = tmp_path / "trimmed_marker.txt"
    padded_command = f"  echo ok > {marker}  "
    normalized_command = f"echo ok > {marker}"

    success, results = run_commands([padded_command], cwd=tmp_path)

    assert success is True
    assert results == [(normalized_command, 0)]
    assert marker.exists()


def test_run_commands_missing_cwd_raises_actionable_error(tmp_path: Path) -> None:
    """Runner should raise clear error when cwd does not exist."""
    missing_cwd = tmp_path / "missing-dir"

    with pytest.raises(FileNotFoundError, match="Command runner cwd does not exist:"):
        run_commands(["echo noop"], cwd=missing_cwd)
