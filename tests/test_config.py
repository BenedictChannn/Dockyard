"""Tests for runtime configuration loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from dockyard.config import (
    DockyardPaths,
    default_runtime_config,
    load_runtime_config,
)
from dockyard.errors import DockyardError


def _paths(base: Path) -> DockyardPaths:
    """Build dockyard paths for config loading tests."""
    checkpoints = base / "checkpoints"
    db_dir = base / "db"
    checkpoints.mkdir(parents=True, exist_ok=True)
    db_dir.mkdir(parents=True, exist_ok=True)
    return DockyardPaths(
        base_dir=base,
        checkpoints_dir=checkpoints,
        db_path=db_dir / "index.sqlite",
        config_path=base / "config.toml",
    )


def test_load_runtime_config_defaults_when_missing(tmp_path: Path) -> None:
    """Missing config file should return default values."""
    paths = _paths(tmp_path)
    loaded = load_runtime_config(paths)
    defaults = default_runtime_config()
    assert loaded.review_heuristics.files_changed_threshold == defaults.review_heuristics.files_changed_threshold
    assert loaded.review_heuristics.churn_threshold == defaults.review_heuristics.churn_threshold
    assert loaded.review_heuristics.risky_path_patterns == defaults.review_heuristics.risky_path_patterns


def test_load_runtime_config_applies_overrides(tmp_path: Path) -> None:
    """Valid config file should override heuristic settings."""
    paths = _paths(tmp_path)
    paths.config_path.write_text(
        "\n".join(
            [
                "[review_heuristics]",
                "files_changed_threshold = 4",
                "churn_threshold = 90",
                "non_trivial_files_threshold = 1",
                "non_trivial_churn_threshold = 10",
                'branch_prefixes = ["release/", "urgent/"]',
                'risky_path_patterns = ["(^|/)critical/"]',
            ]
        ),
        encoding="utf-8",
    )
    loaded = load_runtime_config(paths)
    assert loaded.review_heuristics.files_changed_threshold == 4
    assert loaded.review_heuristics.churn_threshold == 90
    assert loaded.review_heuristics.non_trivial_files_threshold == 1
    assert loaded.review_heuristics.non_trivial_churn_threshold == 10
    assert loaded.review_heuristics.branch_prefixes == ["release/", "urgent/"]
    assert loaded.review_heuristics.risky_path_patterns == ["(^|/)critical/"]


def test_load_runtime_config_rejects_invalid_types(tmp_path: Path) -> None:
    """Invalid config value types should raise actionable errors."""
    paths = _paths(tmp_path)
    paths.config_path.write_text(
        "\n".join(
            [
                "[review_heuristics]",
                'files_changed_threshold = "bad"',
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(DockyardError):
        load_runtime_config(paths)


def test_load_runtime_config_rejects_invalid_regex_patterns(tmp_path: Path) -> None:
    """Invalid risky-path regexes should raise config errors."""
    paths = _paths(tmp_path)
    paths.config_path.write_text(
        "\n".join(
            [
                "[review_heuristics]",
                'risky_path_patterns = ["(^|/)[bad"]',
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(DockyardError):
        load_runtime_config(paths)


def test_load_runtime_config_rejects_boolean_for_int_field(tmp_path: Path) -> None:
    """Boolean values should be rejected for integer threshold fields."""
    paths = _paths(tmp_path)
    paths.config_path.write_text(
        "\n".join(
            [
                "[review_heuristics]",
                "files_changed_threshold = true",
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(DockyardError):
        load_runtime_config(paths)


def test_load_runtime_config_rejects_non_string_list_entries(tmp_path: Path) -> None:
    """List-based fields should reject non-string entries."""
    paths = _paths(tmp_path)
    paths.config_path.write_text(
        "\n".join(
            [
                "[review_heuristics]",
                "branch_prefixes = [\"release/\", 123]",
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(DockyardError):
        load_runtime_config(paths)


def test_load_runtime_config_rejects_negative_thresholds(tmp_path: Path) -> None:
    """Threshold values should not accept negatives."""
    paths = _paths(tmp_path)
    paths.config_path.write_text(
        "\n".join(
            [
                "[review_heuristics]",
                "churn_threshold = -1",
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(DockyardError):
        load_runtime_config(paths)


def test_load_runtime_config_empty_review_section_uses_defaults(tmp_path: Path) -> None:
    """Empty review_heuristics table should preserve default values."""
    paths = _paths(tmp_path)
    paths.config_path.write_text("[review_heuristics]\n", encoding="utf-8")

    loaded = load_runtime_config(paths)
    defaults = default_runtime_config()
    assert loaded.review_heuristics.files_changed_threshold == defaults.review_heuristics.files_changed_threshold
    assert loaded.review_heuristics.churn_threshold == defaults.review_heuristics.churn_threshold
    assert loaded.review_heuristics.branch_prefixes == defaults.review_heuristics.branch_prefixes


def test_load_runtime_config_ignores_unknown_sections(tmp_path: Path) -> None:
    """Unknown config sections should not break runtime config loading."""
    paths = _paths(tmp_path)
    paths.config_path.write_text(
        "\n".join(
            [
                "[other_section]",
                'foo = "bar"',
            ]
        ),
        encoding="utf-8",
    )

    loaded = load_runtime_config(paths)
    defaults = default_runtime_config()
    assert loaded.review_heuristics.risky_path_patterns == defaults.review_heuristics.risky_path_patterns
