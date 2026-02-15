"""Configuration and path resolution for Dockyard storage."""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from dockyard.errors import DockyardError


@dataclass(slots=True)
class DockyardPaths:
    """Resolved filesystem paths used by Dockyard.

    Attributes:
        base_dir: Base dockyard data directory.
        checkpoints_dir: Root path for markdown checkpoints.
        db_path: SQLite database file path.
        config_path: Optional user configuration path.
    """

    base_dir: Path
    checkpoints_dir: Path
    db_path: Path
    config_path: Path


@dataclass(slots=True)
class ReviewHeuristicsConfig:
    """Review trigger heuristic settings loaded from config."""

    risky_path_patterns: list[str]
    files_changed_threshold: int = 15
    churn_threshold: int = 400
    non_trivial_files_threshold: int = 3
    non_trivial_churn_threshold: int = 80
    branch_prefixes: list[str] | None = None


@dataclass(slots=True)
class DockyardRuntimeConfig:
    """Runtime configuration used by services and CLI."""

    review_heuristics: ReviewHeuristicsConfig


def default_base_dir() -> Path:
    """Return the platform-aware default Dockyard base directory."""
    override = os.environ.get("DOCKYARD_HOME")
    if override:
        return Path(override).expanduser().resolve()

    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "dockyard"
    return Path.home() / ".local" / "share" / "dockyard"


def resolve_paths() -> DockyardPaths:
    """Resolve and create the Dockyard data directories."""
    base = default_base_dir()
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


def default_runtime_config() -> DockyardRuntimeConfig:
    """Return default runtime configuration values."""
    return DockyardRuntimeConfig(
        review_heuristics=ReviewHeuristicsConfig(
            risky_path_patterns=[
                r"(^|/)auth/",
                r"(^|/)infra/",
                r"(^|/)\.github/",
                r"(^|/)terraform/",
                r"(^|/)migrations/",
                r"(^|/)payments/",
                r"(^|/)security/",
            ],
            files_changed_threshold=15,
            churn_threshold=400,
            non_trivial_files_threshold=3,
            non_trivial_churn_threshold=80,
            branch_prefixes=["release/", "hotfix/"],
        )
    )


def load_runtime_config(paths: DockyardPaths | None = None) -> DockyardRuntimeConfig:
    """Load runtime configuration from config.toml when available.

    Args:
        paths: Optional pre-resolved dockyard paths.

    Returns:
        Runtime configuration object with defaults and overrides.

    Raises:
        DockyardError: If config file exists but is invalid.
    """
    resolved = paths or resolve_paths()
    config = default_runtime_config()
    if not resolved.config_path.exists():
        return config

    raw = resolved.config_path.read_text(encoding="utf-8")
    try:
        parsed = tomllib.loads(raw)
    except tomllib.TOMLDecodeError as exc:
        raise DockyardError(f"Invalid config TOML: {resolved.config_path}") from exc

    review = parsed.get("review_heuristics")
    if not review:
        return config
    if not isinstance(review, dict):
        raise DockyardError("Config section [review_heuristics] must be a table.")

    heuristics = config.review_heuristics
    heuristics.risky_path_patterns = _parse_str_list(
        review.get("risky_path_patterns"),
        default=heuristics.risky_path_patterns,
        field_name="review_heuristics.risky_path_patterns",
    )
    _validate_regex_patterns(
        heuristics.risky_path_patterns,
        field_name="review_heuristics.risky_path_patterns",
    )
    heuristics.files_changed_threshold = _parse_int(
        review.get("files_changed_threshold"),
        default=heuristics.files_changed_threshold,
        field_name="review_heuristics.files_changed_threshold",
    )
    heuristics.churn_threshold = _parse_int(
        review.get("churn_threshold"),
        default=heuristics.churn_threshold,
        field_name="review_heuristics.churn_threshold",
    )
    heuristics.non_trivial_files_threshold = _parse_int(
        review.get("non_trivial_files_threshold"),
        default=heuristics.non_trivial_files_threshold,
        field_name="review_heuristics.non_trivial_files_threshold",
    )
    heuristics.non_trivial_churn_threshold = _parse_int(
        review.get("non_trivial_churn_threshold"),
        default=heuristics.non_trivial_churn_threshold,
        field_name="review_heuristics.non_trivial_churn_threshold",
    )
    heuristics.branch_prefixes = _parse_str_list(
        review.get("branch_prefixes"),
        default=heuristics.branch_prefixes or ["release/", "hotfix/"],
        field_name="review_heuristics.branch_prefixes",
    )
    return config


def _parse_int(value, default: int, field_name: str) -> int:
    """Parse optional integer config value with validation."""
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise DockyardError(f"Config field {field_name} must be an integer.")
    return value


def _parse_str_list(value, default: list[str], field_name: str) -> list[str]:
    """Parse optional list-of-string config value with validation."""
    if value is None:
        return default
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise DockyardError(f"Config field {field_name} must be an array of strings.")
    return value


def _validate_regex_patterns(patterns: list[str], field_name: str) -> None:
    """Validate regex patterns and raise actionable errors on failure."""
    for pattern in patterns:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise DockyardError(
                f"Invalid regex in {field_name}: {pattern}"
            ) from exc
