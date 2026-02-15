"""Tests for harbor dashboard sorting behavior."""

from __future__ import annotations

from dockyard.models import Berth, ReviewItem, Slip
from dockyard.storage.sqlite_store import SQLiteStore


def test_harbor_sorting_prioritizes_reviews_then_status_then_staleness(tmp_path) -> None:
    """Harbor sort order should follow PRD rule precedence."""
    store = SQLiteStore(tmp_path / "dock.sqlite")
    store.initialize()

    store.upsert_berth(Berth(repo_id="a", name="A", root_path="/tmp/a", remote_url=None))
    store.upsert_berth(Berth(repo_id="b", name="B", root_path="/tmp/b", remote_url=None))
    store.upsert_berth(Berth(repo_id="c", name="C", root_path="/tmp/c", remote_url=None))

    store.upsert_slip(Slip(repo_id="a", branch="main", last_checkpoint_id=None, status="yellow", updated_at="2026-01-03T00:00:00+00:00"))
    store.upsert_slip(Slip(repo_id="b", branch="main", last_checkpoint_id=None, status="red", updated_at="2026-01-02T00:00:00+00:00"))
    store.upsert_slip(Slip(repo_id="c", branch="main", last_checkpoint_id=None, status="green", updated_at="2026-01-01T00:00:00+00:00"))

    # Repo "a" gets one open review and should be first despite yellow status.
    store.add_review_item(
        ReviewItem(
            id="rev1",
            repo_id="a",
            branch="main",
            checkpoint_id=None,
            created_at="2026-01-03T01:00:00+00:00",
            reason="manual",
            severity="low",
            status="open",
            notes=None,
            files=[],
        )
    )

    rows = store.list_harbor()
    assert [row["repo_id"] for row in rows] == ["a", "b", "c"]


def test_harbor_filters_for_tag_stale_and_limit(tmp_path) -> None:
    """Harbor list should support tag, staleness, and limit filters."""
    store = SQLiteStore(tmp_path / "dock.sqlite")
    store.initialize()

    store.upsert_berth(Berth(repo_id="old", name="Old", root_path="/tmp/old", remote_url=None))
    store.upsert_berth(Berth(repo_id="fresh", name="Fresh", root_path="/tmp/fresh", remote_url=None))

    store.upsert_slip(
        Slip(
            repo_id="old",
            branch="main",
            last_checkpoint_id=None,
            status="yellow",
            tags=["mvp"],
            updated_at="2000-01-01T00:00:00+00:00",
        )
    )
    store.upsert_slip(
        Slip(
            repo_id="fresh",
            branch="main",
            last_checkpoint_id=None,
            status="green",
            tags=["docs"],
            updated_at="2999-01-01T00:00:00+00:00",
        )
    )

    stale_rows = store.list_harbor(stale_days=1)
    assert len(stale_rows) == 1
    assert stale_rows[0]["repo_id"] == "old"

    tag_rows = store.list_harbor(tag="docs")
    assert len(tag_rows) == 1
    assert tag_rows[0]["repo_id"] == "fresh"

    limited = store.list_harbor(limit=1)
    assert len(limited) == 1
