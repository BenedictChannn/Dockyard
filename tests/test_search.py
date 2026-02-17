"""Search indexing and filtering tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from dockyard.models import Berth, Checkpoint, VerificationState
from dockyard.storage.sqlite_store import SQLiteStore, _is_fts_query_parser_error


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


@pytest.mark.parametrize(
    "message",
    [
        "fts5: syntax error near '/'",
        "malformed match expression: foo",
        "unterminated string",
        "no such column: token",
    ],
)
def test_is_fts_query_parser_error_recognizes_known_messages(message: str) -> None:
    """Parser-error classifier should identify known MATCH parse failures."""
    assert _is_fts_query_parser_error(sqlite3.OperationalError(message))


def test_is_fts_query_parser_error_rejects_unrelated_messages() -> None:
    """Parser-error classifier should ignore unrelated operational failures."""
    assert not _is_fts_query_parser_error(sqlite3.OperationalError("database disk image is malformed"))


def test_search_falls_back_for_fts_parser_operational_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Search should fallback when FTS path raises parser OperationalError."""
    db_path = tmp_path / "dock.sqlite"
    store = SQLiteStore(db_path)
    store.initialize()
    store.upsert_berth(
        Berth(
            repo_id="repo_parser_error",
            name="ParserError",
            root_path="/tmp/parser-error",
            remote_url=None,
        )
    )
    store.add_checkpoint(
        _checkpoint(
            "cp_parser_error",
            "repo_parser_error",
            "main",
            "Fallback path for parser/error query",
            ["mvp"],
        )
    )

    def _force_fts_enabled(_conn: sqlite3.Connection) -> bool:
        return True

    def _raise_parser_error(**_kwargs: object) -> list[sqlite3.Row]:
        raise sqlite3.OperationalError("fts5: syntax error near '/'")

    monkeypatch.setattr(store, "_has_fts", _force_fts_enabled)
    monkeypatch.setattr(store, "_search_rows_fts", _raise_parser_error)

    hits = store.search_checkpoints("parser/error")
    assert len(hits) == 1
    assert hits[0]["id"] == "cp_parser_error"


def test_search_like_fallback_honors_repo_and_branch_filters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LIKE fallback should preserve repo/branch filter precedence."""
    db_path = tmp_path / "dock.sqlite"
    store = SQLiteStore(db_path)
    store.initialize()
    store.upsert_berth(Berth(repo_id="repo_like_a", name="LikeA", root_path="/tmp/la", remote_url=None))
    store.upsert_berth(Berth(repo_id="repo_like_b", name="LikeB", root_path="/tmp/lb", remote_url=None))
    store.add_checkpoint(
        _checkpoint(
            "cp_like_a_main",
            "repo_like_a",
            "main",
            "Fallback security/path main",
            ["mvp"],
        )
    )
    store.add_checkpoint(
        _checkpoint(
            "cp_like_a_feature",
            "repo_like_a",
            "feature/x",
            "Fallback security/path feature",
            ["mvp"],
        )
    )
    store.add_checkpoint(
        _checkpoint(
            "cp_like_b_main",
            "repo_like_b",
            "main",
            "Fallback security/path other repo",
            ["mvp"],
        )
    )

    def _force_fts_enabled(_conn: sqlite3.Connection) -> bool:
        return True

    def _raise_parser_error(**_kwargs: object) -> list[sqlite3.Row]:
        raise sqlite3.OperationalError("fts5: syntax error near '/'")

    monkeypatch.setattr(store, "_has_fts", _force_fts_enabled)
    monkeypatch.setattr(store, "_search_rows_fts", _raise_parser_error)

    repo_hits = store.search_checkpoints("security/path", repo_id="repo_like_a")
    assert {hit["id"] for hit in repo_hits} == {"cp_like_a_main", "cp_like_a_feature"}

    branch_hits = store.search_checkpoints("security/path", repo_id="repo_like_a", branch="main")
    assert len(branch_hits) == 1
    assert branch_hits[0]["id"] == "cp_like_a_main"

    other_repo_hits = store.search_checkpoints("security/path", repo_id="repo_like_b", branch="main")
    assert len(other_repo_hits) == 1
    assert other_repo_hits[0]["id"] == "cp_like_b_main"


def test_search_reraises_non_parser_fts_operational_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Search should not swallow non-parser OperationalError from FTS path."""
    db_path = tmp_path / "dock.sqlite"
    store = SQLiteStore(db_path)
    store.initialize()
    store.upsert_berth(
        Berth(
            repo_id="repo_non_parser_error",
            name="NonParserError",
            root_path="/tmp/non-parser-error",
            remote_url=None,
        )
    )
    store.add_checkpoint(
        _checkpoint(
            "cp_non_parser_error",
            "repo_non_parser_error",
            "main",
            "No fallback for unrelated operational errors",
            ["mvp"],
        )
    )

    def _force_fts_enabled(_conn: sqlite3.Connection) -> bool:
        return True

    def _raise_unrelated_operational_error(**_kwargs: object) -> list[sqlite3.Row]:
        raise sqlite3.OperationalError("database disk image is malformed")

    monkeypatch.setattr(store, "_has_fts", _force_fts_enabled)
    monkeypatch.setattr(store, "_search_rows_fts", _raise_unrelated_operational_error)

    with pytest.raises(sqlite3.OperationalError, match="database disk image is malformed"):
        store.search_checkpoints("non-parser-error")


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


def test_search_snippet_prefers_objective_when_multiple_fields_match(tmp_path: Path) -> None:
    """Objective text should win when query appears in multiple fields."""
    db_path = tmp_path / "dock.sqlite"
    store = SQLiteStore(db_path)
    store.initialize()
    store.upsert_berth(Berth(repo_id="repo_priority", name="Priority", root_path="/tmp/p", remote_url=None))
    store.add_checkpoint(
        Checkpoint(
            id="cp_priority",
            repo_id="repo_priority",
            branch="main",
            created_at="2026-01-01T00:00:00+00:00",
            objective="priority token in objective",
            decisions="priority token in decisions",
            next_steps=["priority token in next steps"],
            risks_review="priority token in risk",
            resume_commands=["echo priority"],
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

    hits = store.search_checkpoints("priority token")
    assert len(hits) == 1
    assert hits[0]["snippet"] == "priority token in objective"


def test_search_snippet_normalizes_multiline_whitespace(tmp_path: Path) -> None:
    """Snippet text should collapse multiline whitespace for readability."""
    db_path = tmp_path / "dock.sqlite"
    store = SQLiteStore(db_path)
    store.initialize()
    store.upsert_berth(Berth(repo_id="repo_ws", name="Whitespace", root_path="/tmp/ws", remote_url=None))
    store.add_checkpoint(
        Checkpoint(
            id="cp_ws",
            repo_id="repo_ws",
            branch="main",
            created_at="2026-01-01T00:00:00+00:00",
            objective="Objective",
            decisions="",
            next_steps=["line one\nline two\tline three"],
            risks_review="risk",
            resume_commands=["echo ws"],
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

    hits = store.search_checkpoints("line two")
    assert len(hits) == 1
    assert hits[0]["snippet"] == "line one line two line three"


def test_search_snippet_normalizes_objective_spacing(tmp_path: Path) -> None:
    """Objective snippet text should collapse repeated whitespace."""
    db_path = tmp_path / "dock.sqlite"
    store = SQLiteStore(db_path)
    store.initialize()
    store.upsert_berth(Berth(repo_id="repo_obj_ws", name="ObjWS", root_path="/tmp/ows", remote_url=None))
    store.add_checkpoint(
        Checkpoint(
            id="cp_obj_ws",
            repo_id="repo_obj_ws",
            branch="main",
            created_at="2026-01-01T00:00:00+00:00",
            objective="token   with\t\tspace",
            decisions="none",
            next_steps=["step"],
            risks_review="risk",
            resume_commands=[],
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

    hits = store.search_checkpoints("token")
    assert len(hits) == 1
    assert hits[0]["snippet"] == "token with space"


def test_search_snippet_preserves_unicode_characters(tmp_path: Path) -> None:
    """Snippet normalization should preserve unicode characters."""
    db_path = tmp_path / "dock.sqlite"
    store = SQLiteStore(db_path)
    store.initialize()
    store.upsert_berth(Berth(repo_id="repo_unicode", name="Unicode", root_path="/tmp/u", remote_url=None))
    store.add_checkpoint(
        Checkpoint(
            id="cp_unicode",
            repo_id="repo_unicode",
            branch="main",
            created_at="2026-01-01T00:00:00+00:00",
            objective="Unicode objective",
            decisions="",
            next_steps=["step"],
            risks_review="Need façade validation",
            resume_commands=[],
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

    hits = store.search_checkpoints("façade")
    assert len(hits) == 1
    assert "façade" in hits[0]["snippet"]
