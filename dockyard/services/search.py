"""Search service wrappers."""

from __future__ import annotations

from dockyard.storage.sqlite_store import SQLiteStore


def search(
    store: SQLiteStore,
    query: str,
    tag: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Search checkpoint content from indexed database."""
    return store.search_checkpoints(
        query=query,
        tag=tag,
        repo_id=repo,
        branch=branch,
        limit=limit,
    )
