"""Configuration and path resolution for Dockyard storage."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


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
