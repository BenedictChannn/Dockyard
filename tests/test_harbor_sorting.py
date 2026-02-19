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


def test_harbor_sorting_places_unknown_status_after_known_statuses(tmp_path) -> None:
    """Harbor sorting should relegate unknown statuses behind known priorities."""
    store = SQLiteStore(tmp_path / "dock.sqlite")
    store.initialize()

    store.upsert_berth(Berth(repo_id="red", name="Red", root_path="/tmp/red", remote_url=None))
    store.upsert_berth(Berth(repo_id="mystery", name="Mystery", root_path="/tmp/mystery", remote_url=None))
    store.upsert_berth(Berth(repo_id="green", name="Green", root_path="/tmp/green", remote_url=None))

    store.upsert_slip(
        Slip(
            repo_id="red",
            branch="main",
            last_checkpoint_id=None,
            status="red",
            updated_at="2026-01-03T00:00:00+00:00",
        )
    )
    store.upsert_slip(
        Slip(
            repo_id="mystery",
            branch="main",
            last_checkpoint_id=None,
            status="paused",
            updated_at="2026-01-01T00:00:00+00:00",
        )
    )
    store.upsert_slip(
        Slip(
            repo_id="green",
            branch="main",
            last_checkpoint_id=None,
            status="green",
            updated_at="2026-01-02T00:00:00+00:00",
        )
    )

    rows = store.list_harbor()
    assert [row["repo_id"] for row in rows] == ["red", "green", "mystery"]


def test_harbor_stale_filter_ignores_invalid_timestamps(tmp_path) -> None:
    """Stale filtering should skip rows with invalid timestamp values."""
    store = SQLiteStore(tmp_path / "dock.sqlite")
    store.initialize()

    store.upsert_berth(Berth(repo_id="invalid", name="Invalid", root_path="/tmp/invalid", remote_url=None))
    store.upsert_berth(Berth(repo_id="valid", name="Valid", root_path="/tmp/valid", remote_url=None))

    store.upsert_slip(
        Slip(
            repo_id="invalid",
            branch="main",
            last_checkpoint_id=None,
            status="yellow",
            updated_at="not-a-timestamp",
        )
    )
    store.upsert_slip(
        Slip(
            repo_id="valid",
            branch="main",
            last_checkpoint_id=None,
            status="yellow",
            updated_at="2000-01-01T00:00:00+00:00",
        )
    )

    stale_rows = store.list_harbor(stale_days=1)
    assert [row["repo_id"] for row in stale_rows] == ["valid"]


def test_harbor_stale_filter_accepts_naive_timestamps(tmp_path) -> None:
    """Stale filtering should treat naive ISO timestamps as UTC values."""
    store = SQLiteStore(tmp_path / "dock.sqlite")
    store.initialize()

    store.upsert_berth(Berth(repo_id="naive", name="Naive", root_path="/tmp/naive", remote_url=None))
    store.upsert_berth(Berth(repo_id="aware", name="Aware", root_path="/tmp/aware", remote_url=None))

    store.upsert_slip(
        Slip(
            repo_id="naive",
            branch="main",
            last_checkpoint_id=None,
            status="yellow",
            updated_at="2000-01-01T00:00:00",
        )
    )
    store.upsert_slip(
        Slip(
            repo_id="aware",
            branch="main",
            last_checkpoint_id=None,
            status="yellow",
            updated_at="2999-01-01T00:00:00+00:00",
        )
    )

    stale_rows = store.list_harbor(stale_days=1)
    assert [row["repo_id"] for row in stale_rows] == ["naive"]


def test_harbor_stale_filter_skips_non_string_timestamps(tmp_path) -> None:
    """Stale filtering should skip rows with non-string timestamp payloads."""
    store = SQLiteStore(tmp_path / "dock.sqlite")
    store.initialize()

    store.upsert_berth(Berth(repo_id="numeric", name="Numeric", root_path="/tmp/numeric", remote_url=None))
    store.upsert_berth(Berth(repo_id="valid", name="Valid", root_path="/tmp/valid", remote_url=None))

    store.upsert_slip(
        Slip(
            repo_id="numeric",
            branch="main",
            last_checkpoint_id=None,
            status="yellow",
            updated_at=12345,  # type: ignore[arg-type]
        )
    )
    store.upsert_slip(
        Slip(
            repo_id="valid",
            branch="main",
            last_checkpoint_id=None,
            status="yellow",
            updated_at="2000-01-01T00:00:00+00:00",
        )
    )

    stale_rows = store.list_harbor(stale_days=1)
    assert [row["repo_id"] for row in stale_rows] == ["valid"]


def test_harbor_sorting_handles_mixed_updated_at_types(tmp_path) -> None:
    """Harbor sorting should tolerate mixed updated_at value types."""
    store = SQLiteStore(tmp_path / "dock.sqlite")
    store.initialize()

    store.upsert_berth(Berth(repo_id="numeric", name="Numeric", root_path="/tmp/numeric", remote_url=None))
    store.upsert_berth(Berth(repo_id="text", name="Text", root_path="/tmp/text", remote_url=None))

    store.upsert_slip(
        Slip(
            repo_id="numeric",
            branch="main",
            last_checkpoint_id=None,
            status="yellow",
            updated_at=0,  # type: ignore[arg-type]
        )
    )
    store.upsert_slip(
        Slip(
            repo_id="text",
            branch="main",
            last_checkpoint_id=None,
            status="yellow",
            updated_at="2026-01-01T00:00:00+00:00",
        )
    )

    rows = store.list_harbor()
    assert len(rows) == 2
    assert {row["repo_id"] for row in rows} == {"numeric", "text"}


