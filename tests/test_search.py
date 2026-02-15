"""Search indexing and filtering tests."""

from __future__ import annotations

from pathlib import Path

from dockyard.models import Berth, Checkpoint, VerificationState
from dockyard.storage.sqlite_store import SQLiteStore


def _checkpoint(checkpoint_id: str, repo_id: str, branch: str, objective: str, tags: list[str]) -> Checkpoint:
    """Create a checkpoint model for search tests."""
    return Checkpoint(
        id=checkpoint_id,
        repo_id=repo_id,
        branch=branch,
        created_at="2026-01-01T00:00:00+00:00",
        objective=objective,
        decisions="Decision log includes migration notes",
        next_steps=["Ship search"],
        risks_review="No major risk",
        resume_commands=["pytest -q"],
        git_dirty=False,
        head_sha="abc123",
        head_subject="subject",
        recent_commits=["abc subject"],
        diff_files_changed=1,
        diff_insertions=10,
        diff_deletions=5,
        touched_files=["src/a.py"],
        diff_stat_text="1 file changed",
        verification=VerificationState(tests_run=True, build_ok=True, lint_ok=True, smoke_ok=True),
        tags=tags,
    )


def test_search_returns_matches_and_honors_filters(tmp_path: Path) -> None:
    """Search should return text matches and respect repo/tag filters."""
    db_path = tmp_path / "dock.sqlite"
    store = SQLiteStore(db_path)
    store.initialize()
    store.upsert_berth(
        Berth(
            repo_id="repo_a",
            name="A",
            root_path="/tmp/a",
            remote_url=None,
        )
    )
    store.upsert_berth(
        Berth(
            repo_id="repo_b",
            name="B",
            root_path="/tmp/b",
            remote_url=None,
        )
    )
    store.add_checkpoint(_checkpoint("cp1", "repo_a", "main", "Implement search indexing", ["mvp"]))
    store.add_checkpoint(_checkpoint("cp2", "repo_b", "main", "Refactor docs", ["docs"]))

    all_hits = store.search_checkpoints("indexing")
    assert len(all_hits) == 1
    assert all_hits[0]["id"] == "cp1"

    repo_hits = store.search_checkpoints("indexing", repo_id="repo_a")
    assert len(repo_hits) == 1
    tag_hits = store.search_checkpoints("indexing", tag="mvp")
    assert len(tag_hits) == 1
    filtered_out = store.search_checkpoints("indexing", tag="docs")
    assert filtered_out == []


def test_search_falls_back_for_fts_special_characters(tmp_path: Path) -> None:
    """Search should succeed when query contains FTS-special syntax."""
    db_path = tmp_path / "dock.sqlite"
    store = SQLiteStore(db_path)
    store.initialize()
    store.upsert_berth(
        Berth(
            repo_id="repo_special",
            name="Special",
            root_path="/tmp/special",
            remote_url=None,
        )
    )
    store.add_checkpoint(
        _checkpoint(
            "cp_special",
            "repo_special",
            "main",
            "Inspect security/path handling",
            ["mvp"],
        )
    )

    # "/" can trigger FTS parser errors in MATCH mode; fallback should keep search working.
    hits = store.search_checkpoints("security/path")
    assert len(hits) == 1
    assert hits[0]["id"] == "cp_special"
