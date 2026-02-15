"""Migration tests for SQLite store."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from dockyard.storage.sqlite_store import SQLiteStore


def test_migrations_are_idempotent(tmp_path: Path) -> None:
    """Store initialization can run multiple times safely."""
    db_path = tmp_path / "index.sqlite"
    store = SQLiteStore(db_path)
    store.initialize()
    store.initialize()

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT COUNT(*) FROM schema_migrations WHERE version = 1").fetchone()
    conn.close()
    assert row is not None
    assert row[0] == 1
