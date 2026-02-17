"""Tests for performance smoke script argument and seed guards."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import pytest

from dockyard.storage.sqlite_store import SQLiteStore
from scripts.perf_smoke import (
    _non_negative_int_arg,
    _positive_int_arg,
    seed_data,
)

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "perf_smoke.py"


def test_positive_int_arg_accepts_positive_values() -> None:
    """Positive integer parser should accept values greater than zero."""
    assert _positive_int_arg("3") == 3


def test_positive_int_arg_rejects_zero_or_negative() -> None:
    """Positive integer parser should reject non-positive values."""
    with pytest.raises(argparse.ArgumentTypeError):
        _positive_int_arg("0")
    with pytest.raises(argparse.ArgumentTypeError):
        _positive_int_arg("-1")


def test_non_negative_int_arg_accepts_zero_and_positive() -> None:
    """Non-negative parser should accept zero and positive values."""
    assert _non_negative_int_arg("0") == 0
    assert _non_negative_int_arg("7") == 7


def test_non_negative_int_arg_rejects_negative_values() -> None:
    """Non-negative parser should reject negative values."""
    with pytest.raises(argparse.ArgumentTypeError):
        _non_negative_int_arg("-2")


def test_seed_data_rejects_non_positive_berth_count(tmp_path) -> None:
    """Seeding should fail fast when berth_count is non-positive."""
    store = SQLiteStore(tmp_path / "perf_smoke.sqlite")
    store.initialize()

    with pytest.raises(ValueError, match="berth_count"):
        seed_data(store, berth_count=0, checkpoint_count=1)


def test_seed_data_rejects_negative_checkpoint_count(tmp_path) -> None:
    """Seeding should fail fast when checkpoint_count is negative."""
    store = SQLiteStore(tmp_path / "perf_smoke.sqlite")
    store.initialize()

    with pytest.raises(ValueError, match="checkpoint_count"):
        seed_data(store, berth_count=1, checkpoint_count=-1)


def test_perf_smoke_script_runs_with_small_dataset(tmp_path) -> None:
    """Perf smoke script should execute successfully with minimal valid input."""
    db_path = tmp_path / "perf_smoke_cli.sqlite"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--db-path",
            str(db_path),
            "--berths",
            "1",
            "--checkpoints",
            "0",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "dock ls query:" in completed.stdout
    assert "dock search query:" in completed.stdout


def test_perf_smoke_script_rejects_non_positive_berths(tmp_path) -> None:
    """Perf smoke script should reject non-positive berth count at CLI level."""
    db_path = tmp_path / "perf_smoke_cli_invalid.sqlite"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--db-path",
            str(db_path),
            "--berths",
            "0",
            "--checkpoints",
            "0",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "value must be greater than zero" in completed.stderr
