"""Tests for link persistence behavior."""

from __future__ import annotations

from dockyard.models import LinkItem
from dockyard.storage.sqlite_store import SQLiteStore


def test_list_links_returns_branch_scoped_newest_first(tmp_path) -> None:
    """Link listing should be branch-scoped and ordered by newest first."""
    store = SQLiteStore(tmp_path / "dock.sqlite")
    store.initialize()

    store.add_link(
        LinkItem(
            id="lnk_old",
            repo_id="repo",
            branch="main",
            url="https://example.com/old",
            created_at="2026-01-01T00:00:00+00:00",
        )
    )
    store.add_link(
        LinkItem(
            id="lnk_new",
            repo_id="repo",
            branch="main",
            url="https://example.com/new",
            created_at="2026-01-02T00:00:00+00:00",
        )
    )
    store.add_link(
        LinkItem(
            id="lnk_other_branch",
            repo_id="repo",
            branch="feature/x",
            url="https://example.com/other",
            created_at="2026-01-03T00:00:00+00:00",
        )
    )

    main_links = store.list_links("repo", "main")
    assert [item.id for item in main_links] == ["lnk_new", "lnk_old"]

    feature_links = store.list_links("repo", "feature/x")
    assert [item.id for item in feature_links] == ["lnk_other_branch"]
