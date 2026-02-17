"""Tests for performance smoke script argument and seed guards."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import pytest

from dockyard.storage.sqlite_store import SQLiteStore
from scripts.perf_smoke import (
    _non_empty_query_arg,
    _non_negative_float_arg,
    _non_negative_int_arg,
    _positive_int_arg,
    _targets_met,
    build_checkpoint,
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


def test_non_negative_float_arg_accepts_zero_and_positive() -> None:
    """Non-negative float parser should accept zero and positive values."""
    assert _non_negative_float_arg("0") == 0.0
    assert _non_negative_float_arg("2.5") == 2.5


def test_non_negative_float_arg_rejects_negative_values() -> None:
    """Non-negative float parser should reject negative values."""
    with pytest.raises(argparse.ArgumentTypeError):
        _non_negative_float_arg("-0.1")


def test_non_empty_query_arg_accepts_trimmed_values() -> None:
    """Non-empty query parser should return trimmed query text."""
    assert _non_empty_query_arg("  search text  ") == "search text"


def test_non_empty_query_arg_rejects_blank_values() -> None:
    """Non-empty query parser should reject blank query text."""
    with pytest.raises(argparse.ArgumentTypeError):
        _non_empty_query_arg("   ")


def test_targets_met_uses_strict_less_than_thresholds() -> None:
    """Target helper should enforce strict less-than semantics."""
    assert _targets_met(
        elapsed_ls_ms=99.9,
        elapsed_search_ms=199.9,
        ls_target_ms=100.0,
        search_target_ms=200.0,
    )
    assert not _targets_met(
        elapsed_ls_ms=100.0,
        elapsed_search_ms=150.0,
        ls_target_ms=100.0,
        search_target_ms=200.0,
    )
    assert not _targets_met(
        elapsed_ls_ms=50.0,
        elapsed_search_ms=200.0,
        ls_target_ms=100.0,
        search_target_ms=200.0,
    )


def test_build_checkpoint_id_is_deterministic() -> None:
    """Synthetic checkpoint IDs should be deterministic for seed repeatability."""
    checkpoint_a = build_checkpoint(repo_id="repo_0001", branch="feature/a", index=7)
    checkpoint_b = build_checkpoint(repo_id="repo_0001", branch="feature/a", index=7)

    assert checkpoint_a.id == checkpoint_b.id == "cp_repo_0001_feature_a_00007"


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
    assert "harbor query limit: 50" in completed.stdout
    assert "search query limit: 20" in completed.stdout
    assert "search workload query: search pipeline" in completed.stdout


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


def test_perf_smoke_script_rejects_non_positive_ls_limit(tmp_path) -> None:
    """Perf smoke script should reject non-positive ls-limit values."""
    db_path = tmp_path / "perf_smoke_cli_invalid_ls_limit.sqlite"
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
            "--ls-limit",
            "0",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "value must be greater than zero" in completed.stderr


def test_perf_smoke_script_rejects_non_positive_search_limit(tmp_path) -> None:
    """Perf smoke script should reject non-positive search-limit values."""
    db_path = tmp_path / "perf_smoke_cli_invalid_search_limit.sqlite"
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
            "--search-limit",
            "0",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "value must be greater than zero" in completed.stderr


def test_perf_smoke_script_rejects_negative_checkpoints(tmp_path) -> None:
    """Perf smoke script should reject negative checkpoint count at CLI level."""
    db_path = tmp_path / "perf_smoke_cli_invalid_checkpoints.sqlite"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--db-path",
            str(db_path),
            "--berths",
            "1",
            "--checkpoints",
            "-1",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "value must be non-negative" in completed.stderr


def test_perf_smoke_script_rejects_negative_latency_target(tmp_path) -> None:
    """Perf smoke script should reject negative latency thresholds."""
    db_path = tmp_path / "perf_smoke_cli_invalid_target.sqlite"
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
            "--ls-target-ms",
            "-1",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "value must be non-negative" in completed.stderr


def test_perf_smoke_script_rejects_negative_search_target(tmp_path) -> None:
    """Perf smoke script should reject negative search latency thresholds."""
    db_path = tmp_path / "perf_smoke_cli_invalid_search_target.sqlite"
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
            "--search-target-ms",
            "-1",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "value must be non-negative" in completed.stderr


def test_perf_smoke_script_rejects_blank_search_query(tmp_path) -> None:
    """Perf smoke script should reject blank search-query values."""
    db_path = tmp_path / "perf_smoke_cli_invalid_query.sqlite"
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
            "--search-query",
            "   ",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "value must be a non-empty query" in completed.stderr


def test_perf_smoke_script_trims_search_query_value(tmp_path) -> None:
    """Perf smoke script should trim surrounding whitespace in search-query."""
    db_path = tmp_path / "perf_smoke_cli_trim_query.sqlite"
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
            "--search-query",
            "  search term  ",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "search workload query: search term" in completed.stdout


def test_perf_smoke_script_enforce_targets_fails_with_zero_thresholds(tmp_path) -> None:
    """CLI should return non-zero when enforced targets are set to zero."""
    db_path = tmp_path / "perf_smoke_cli_strict.sqlite"
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
            "--enforce-targets",
            "--ls-target-ms",
            "0",
            "--search-target-ms",
            "0",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    assert "target < 0.00 ms" in completed.stdout


def test_perf_smoke_script_enforce_targets_succeeds_with_high_thresholds(tmp_path) -> None:
    """CLI should succeed when enforce-targets thresholds are permissive."""
    db_path = tmp_path / "perf_smoke_cli_relaxed.sqlite"
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
            "--enforce-targets",
            "--ls-target-ms",
            "10000",
            "--search-target-ms",
            "10000",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "target < 10000.00 ms" in completed.stdout


def test_perf_smoke_script_allows_custom_search_query(tmp_path) -> None:
    """CLI should honor custom search query input for benchmark search path."""
    db_path = tmp_path / "perf_smoke_cli_query.sqlite"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--db-path",
            str(db_path),
            "--berths",
            "1",
            "--checkpoints",
            "1",
            "--search-query",
            "nonexistent-query-token",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "dock search query:" in completed.stdout
    assert "search workload query: nonexistent-query-token" in completed.stdout
    assert "rows=0" in completed.stdout


def test_perf_smoke_script_applies_custom_ls_limit(tmp_path) -> None:
    """CLI should honor custom ls-limit in benchmark output row count."""
    db_path = tmp_path / "perf_smoke_cli_ls_limit.sqlite"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--db-path",
            str(db_path),
            "--berths",
            "3",
            "--checkpoints",
            "0",
            "--ls-limit",
            "1",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "dock ls query:" in completed.stdout
    assert "harbor query limit: 1" in completed.stdout
    assert "(rows=1)" in completed.stdout


def test_perf_smoke_script_applies_custom_search_limit(tmp_path) -> None:
    """CLI should honor custom search-limit in benchmark output row count."""
    db_path = tmp_path / "perf_smoke_cli_search_limit.sqlite"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--db-path",
            str(db_path),
            "--berths",
            "1",
            "--checkpoints",
            "5",
            "--search-limit",
            "1",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "dock search query:" in completed.stdout
    assert "search query limit: 1" in completed.stdout
    assert "(rows=1)" in completed.stdout
