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
    store.add_checkpoint(_checkpoint("cp3", "repo_a", "feature/x", "Improve search indexing", ["mvp"]))

    all_hits = store.search_checkpoints("indexing")
    assert len(all_hits) == 2
    assert {hit["id"] for hit in all_hits} == {"cp1", "cp3"}
    assert all_hits[0]["berth_name"] == "A"

    repo_hits = store.search_checkpoints("indexing", repo_id="repo_a")
    assert len(repo_hits) == 2
    tag_hits = store.search_checkpoints("indexing", tag="mvp")
    assert len(tag_hits) == 2
    filtered_out = store.search_checkpoints("indexing", tag="docs")
    assert filtered_out == []
    branch_hits = store.search_checkpoints("indexing", repo_id="repo_a", branch="main")
    assert len(branch_hits) == 1
    assert branch_hits[0]["id"] == "cp1"

    # Verify repo filter is applied across all text-match branches.
    common_term_repo_hits = store.search_checkpoints("Decision", repo_id="repo_a")
    assert len(common_term_repo_hits) == 2
    common_term_branch_hits = store.search_checkpoints("Decision", repo_id="repo_a", branch="main")
    assert len(common_term_branch_hits) == 1
    assert common_term_branch_hits[0]["id"] == "cp1"


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


def test_search_respects_limit(tmp_path: Path) -> None:
    """Search should truncate result set to requested limit."""
    db_path = tmp_path / "dock.sqlite"
    store = SQLiteStore(db_path)
    store.initialize()
    store.upsert_berth(Berth(repo_id="repo_limit", name="Limit", root_path="/tmp/l", remote_url=None))
    store.add_checkpoint(_checkpoint("cp_l1", "repo_limit", "main", "Limit search one", ["mvp"]))
    store.add_checkpoint(_checkpoint("cp_l2", "repo_limit", "main", "Limit search two", ["mvp"]))
    store.add_checkpoint(_checkpoint("cp_l3", "repo_limit", "main", "Limit search three", ["mvp"]))

    hits = store.search_checkpoints("Limit search", limit=2)
    assert len(hits) == 2


def test_search_snippet_prefers_matching_next_steps_and_risks(tmp_path: Path) -> None:
    """Snippet should reflect matching fields beyond objective/decisions."""
    db_path = tmp_path / "dock.sqlite"
    store = SQLiteStore(db_path)
    store.initialize()
    store.upsert_berth(Berth(repo_id="repo_snip", name="Snippet", root_path="/tmp/snip", remote_url=None))

    store.add_checkpoint(
        Checkpoint(
            id="cp_next",
            repo_id="repo_snip",
            branch="main",
            created_at="2026-01-01T00:00:00+00:00",
            objective="Generic objective",
            decisions="",
            next_steps=["Run hotspot verification"],
            risks_review="General risk",
            resume_commands=["echo next"],
            git_dirty=False,
            head_sha="abc123",
            head_subject="subject",
            recent_commits=[],
            diff_files_changed=1,
            diff_insertions=1,
            diff_deletions=0,
            touched_files=[],
            diff_stat_text="",
            verification=VerificationState(),
            tags=[],
        )
    )
    store.add_checkpoint(
        Checkpoint(
            id="cp_risk",
            repo_id="repo_snip",
            branch="main",
            created_at="2026-01-01T00:00:01+00:00",
            objective="Another objective",
            decisions="",
            next_steps=["Do something else"],
            risks_review="Need payments review before merge",
            resume_commands=["echo risk"],
            git_dirty=False,
            head_sha="def456",
            head_subject="subject",
            recent_commits=[],
            diff_files_changed=1,
            diff_insertions=1,
            diff_deletions=0,
            touched_files=[],
            diff_stat_text="",
            verification=VerificationState(),
            tags=[],
        )
    )

    hotspot_hits = store.search_checkpoints("hotspot")
    assert len(hotspot_hits) == 1
    assert hotspot_hits[0]["id"] == "cp_next"
    assert "hotspot" in hotspot_hits[0]["snippet"].lower()

    risk_hits = store.search_checkpoints("payments")
    assert len(risk_hits) == 1
    assert risk_hits[0]["id"] == "cp_risk"
    assert "payments" in risk_hits[0]["snippet"].lower()
