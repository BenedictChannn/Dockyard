"""Tests for review listing behavior."""

from __future__ import annotations

from dockyard.models import ReviewItem
from dockyard.storage.sqlite_store import SQLiteStore


def test_review_listing_prioritizes_high_severity(tmp_path) -> None:
    """Open review listing should prioritize higher severity items."""
    store = SQLiteStore(tmp_path / "dock.sqlite")
    store.initialize()

    store.add_review_item(
        ReviewItem(
            id="rev_low",
            repo_id="repo",
            branch="main",
            checkpoint_id=None,
            created_at="2026-01-01T00:00:00+00:00",
            reason="low reason",
            severity="low",
            status="open",
            notes=None,
            files=[],
        )
    )
    store.add_review_item(
        ReviewItem(
            id="rev_high",
            repo_id="repo",
            branch="main",
            checkpoint_id=None,
            created_at="2026-01-01T00:00:01+00:00",
            reason="high reason",
            severity="high",
            status="open",
            notes=None,
            files=[],
        )
    )
    store.add_review_item(
        ReviewItem(
            id="rev_med",
            repo_id="repo",
            branch="main",
            checkpoint_id=None,
            created_at="2026-01-01T00:00:02+00:00",
            reason="med reason",
            severity="med",
            status="open",
            notes=None,
            files=[],
        )
    )

    listed = store.list_reviews(open_only=True)
    assert [item.id for item in listed] == ["rev_high", "rev_med", "rev_low"]


def test_review_listing_uses_recency_within_same_severity(tmp_path) -> None:
    """Within same severity bucket, newer items should appear first."""
    store = SQLiteStore(tmp_path / "dock.sqlite")
    store.initialize()

    store.add_review_item(
        ReviewItem(
            id="rev_old",
            repo_id="repo",
            branch="main",
            checkpoint_id=None,
            created_at="2026-01-01T00:00:00+00:00",
            reason="old",
            severity="med",
            status="open",
            notes=None,
            files=[],
        )
    )
    store.add_review_item(
        ReviewItem(
            id="rev_new",
            repo_id="repo",
            branch="main",
            checkpoint_id=None,
            created_at="2026-01-01T00:00:01+00:00",
            reason="new",
            severity="med",
            status="open",
            notes=None,
            files=[],
        )
    )

    listed = store.list_reviews(open_only=True)
    assert [item.id for item in listed] == ["rev_new", "rev_old"]
