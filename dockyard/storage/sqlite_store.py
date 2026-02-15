"""SQLite index backend for Dockyard."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from dockyard.models import (
    Berth,
    Checkpoint,
    LinkItem,
    ReviewItem,
    Slip,
    VerificationState,
)

SCHEMA_VERSION = 1


def _to_json(value: Any) -> str:
    """Serialize arbitrary value into compact JSON."""
    return json.dumps(value, separators=(",", ":"))


def _from_json(raw: str | None, default: Any) -> Any:
    """Deserialize JSON string with fallback default."""
    if not raw:
        return default
    return json.loads(raw)


class SQLiteStore:
    """Provides CRUD operations and query helpers over SQLite index."""

    def __init__(self, db_path: Path) -> None:
        """Initialize store bound to a database path.

        Args:
            db_path: SQLite database file path.
        """
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Open a SQLite connection with row factory enabled."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        """Initialize schema and apply migrations."""
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            current = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
            current_version = int(current["v"]) if current and current["v"] is not None else 0
            if current_version >= SCHEMA_VERSION:
                return
            self._apply_v1(conn)
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)",
                (SCHEMA_VERSION,),
            )

    def _apply_v1(self, conn: sqlite3.Connection) -> None:
        """Apply initial schema migration."""
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS berths (
                repo_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                root_path TEXT NOT NULL,
                remote_url TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS slips (
                repo_id TEXT NOT NULL,
                branch TEXT NOT NULL,
                last_checkpoint_id TEXT,
                status TEXT NOT NULL,
                tags_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (repo_id, branch),
                FOREIGN KEY (repo_id) REFERENCES berths(repo_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS checkpoints (
                id TEXT PRIMARY KEY,
                repo_id TEXT NOT NULL,
                branch TEXT NOT NULL,
                created_at TEXT NOT NULL,
                objective TEXT NOT NULL,
                decisions TEXT NOT NULL,
                next_steps_json TEXT NOT NULL,
                risks_review TEXT NOT NULL,
                resume_commands_json TEXT NOT NULL,
                git_dirty INTEGER NOT NULL,
                head_sha TEXT NOT NULL,
                head_subject TEXT NOT NULL,
                recent_commits_json TEXT NOT NULL,
                diff_files_changed INTEGER NOT NULL,
                diff_insertions INTEGER NOT NULL,
                diff_deletions INTEGER NOT NULL,
                touched_files_json TEXT NOT NULL,
                diff_stat_text TEXT NOT NULL,
                tests_run INTEGER NOT NULL,
                tests_command TEXT,
                tests_timestamp TEXT,
                build_ok INTEGER NOT NULL,
                build_command TEXT,
                build_timestamp TEXT,
                lint_ok INTEGER NOT NULL,
                lint_command TEXT,
                lint_timestamp TEXT,
                smoke_ok INTEGER NOT NULL,
                smoke_notes TEXT,
                smoke_timestamp TEXT,
                tags_json TEXT NOT NULL,
                FOREIGN KEY (repo_id) REFERENCES berths(repo_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS review_items (
                id TEXT PRIMARY KEY,
                repo_id TEXT NOT NULL,
                branch TEXT NOT NULL,
                checkpoint_id TEXT,
                created_at TEXT NOT NULL,
                reason TEXT NOT NULL,
                severity TEXT NOT NULL,
                status TEXT NOT NULL,
                notes TEXT,
                files_json TEXT NOT NULL,
                FOREIGN KEY (repo_id) REFERENCES berths(repo_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS links (
                id TEXT PRIMARY KEY,
                repo_id TEXT NOT NULL,
                branch TEXT NOT NULL,
                url TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (repo_id) REFERENCES berths(repo_id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_checkpoints_repo_branch_created ON checkpoints(repo_id, branch, created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_checkpoints_created ON checkpoints(created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_review_open ON review_items(status, severity)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_links_repo_branch ON links(repo_id, branch)")
        try:
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS checkpoint_fts
                USING fts5(
                    checkpoint_id UNINDEXED,
                    objective,
                    decisions,
                    next_steps,
                    risks_review
                )
                """
            )
        except sqlite3.OperationalError:
            # Some SQLite builds may not include FTS5; callers fallback to LIKE search.
            pass

    def upsert_berth(self, berth: Berth) -> None:
        """Insert or update a berth record."""
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO berths(repo_id, name, root_path, remote_url, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(repo_id) DO UPDATE SET
                  name=excluded.name,
                  root_path=excluded.root_path,
                  remote_url=excluded.remote_url,
                  updated_at=excluded.updated_at
                """,
                (
                    berth.repo_id,
                    berth.name,
                    berth.root_path,
                    berth.remote_url,
                    berth.created_at,
                    berth.updated_at,
                ),
            )

    def upsert_slip(self, slip: Slip) -> None:
        """Insert or update a slip record."""
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO slips(repo_id, branch, last_checkpoint_id, status, tags_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(repo_id, branch) DO UPDATE SET
                  last_checkpoint_id=excluded.last_checkpoint_id,
                  status=excluded.status,
                  tags_json=excluded.tags_json,
                  updated_at=excluded.updated_at
                """,
                (
                    slip.repo_id,
                    slip.branch,
                    slip.last_checkpoint_id,
                    slip.status,
                    _to_json(slip.tags),
                    slip.updated_at,
                ),
            )

    def add_checkpoint(self, checkpoint: Checkpoint) -> None:
        """Insert checkpoint and update search index."""
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO checkpoints(
                    id, repo_id, branch, created_at, objective, decisions, next_steps_json, risks_review,
                    resume_commands_json, git_dirty, head_sha, head_subject, recent_commits_json,
                    diff_files_changed, diff_insertions, diff_deletions, touched_files_json, diff_stat_text,
                    tests_run, tests_command, tests_timestamp, build_ok, build_command, build_timestamp,
                    lint_ok, lint_command, lint_timestamp, smoke_ok, smoke_notes, smoke_timestamp, tags_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    checkpoint.id,
                    checkpoint.repo_id,
                    checkpoint.branch,
                    checkpoint.created_at,
                    checkpoint.objective,
                    checkpoint.decisions,
                    _to_json(checkpoint.next_steps),
                    checkpoint.risks_review,
                    _to_json(checkpoint.resume_commands),
                    int(checkpoint.git_dirty),
                    checkpoint.head_sha,
                    checkpoint.head_subject,
                    _to_json(checkpoint.recent_commits),
                    checkpoint.diff_files_changed,
                    checkpoint.diff_insertions,
                    checkpoint.diff_deletions,
                    _to_json(checkpoint.touched_files),
                    checkpoint.diff_stat_text,
                    int(checkpoint.verification.tests_run),
                    checkpoint.verification.tests_command,
                    checkpoint.verification.tests_timestamp,
                    int(checkpoint.verification.build_ok),
                    checkpoint.verification.build_command,
                    checkpoint.verification.build_timestamp,
                    int(checkpoint.verification.lint_ok),
                    checkpoint.verification.lint_command,
                    checkpoint.verification.lint_timestamp,
                    int(checkpoint.verification.smoke_ok),
                    checkpoint.verification.smoke_notes,
                    checkpoint.verification.smoke_timestamp,
                    _to_json(checkpoint.tags),
                ),
            )
            try:
                conn.execute(
                    """
                    INSERT INTO checkpoint_fts(checkpoint_id, objective, decisions, next_steps, risks_review)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        checkpoint.id,
                        checkpoint.objective,
                        checkpoint.decisions,
                        "\n".join(checkpoint.next_steps),
                        checkpoint.risks_review,
                    ),
                )
            except sqlite3.OperationalError:
                # Fallback mode without FTS5.
                pass

    def add_link(self, link: LinkItem) -> None:
        """Insert link record."""
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO links(id, repo_id, branch, url, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (link.id, link.repo_id, link.branch, link.url, link.created_at),
            )

    def list_links(self, repo_id: str, branch: str) -> list[LinkItem]:
        """Return links for a specific slip."""
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, repo_id, branch, url, created_at
                FROM links
                WHERE repo_id = ? AND branch = ?
                ORDER BY created_at DESC
                """,
                (repo_id, branch),
            ).fetchall()
        return [
            LinkItem(
                id=row["id"],
                repo_id=row["repo_id"],
                branch=row["branch"],
                url=row["url"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def add_review_item(self, item: ReviewItem) -> None:
        """Insert review item."""
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO review_items(
                    id, repo_id, branch, checkpoint_id, created_at, reason, severity, status, notes, files_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.id,
                    item.repo_id,
                    item.branch,
                    item.checkpoint_id,
                    item.created_at,
                    item.reason,
                    item.severity,
                    item.status,
                    item.notes,
                    _to_json(item.files),
                ),
            )

    def mark_review_done(self, review_id: str) -> bool:
        """Mark review as done and return whether it existed."""
        with self.connect() as conn:
            cur = conn.execute(
                "UPDATE review_items SET status = 'done' WHERE id = ?",
                (review_id,),
            )
            return cur.rowcount > 0

    def get_review(self, review_id: str) -> ReviewItem | None:
        """Fetch a review item by id."""
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT id, repo_id, branch, checkpoint_id, created_at, reason, severity, status, notes, files_json
                FROM review_items
                WHERE id = ?
                """,
                (review_id,),
            ).fetchone()
        if not row:
            return None
        return ReviewItem(
            id=row["id"],
            repo_id=row["repo_id"],
            branch=row["branch"],
            checkpoint_id=row["checkpoint_id"],
            created_at=row["created_at"],
            reason=row["reason"],
            severity=row["severity"],
            status=row["status"],
            notes=row["notes"],
            files=_from_json(row["files_json"], []),
        )

    def list_reviews(self, open_only: bool = True) -> list[ReviewItem]:
        """List review items sorted by newest first."""
        query = """
            SELECT id, repo_id, branch, checkpoint_id, created_at, reason, severity, status, notes, files_json
            FROM review_items
        """
        params: tuple[Any, ...] = ()
        if open_only:
            query += " WHERE status = 'open'"
        query += " ORDER BY created_at DESC"

        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            ReviewItem(
                id=row["id"],
                repo_id=row["repo_id"],
                branch=row["branch"],
                checkpoint_id=row["checkpoint_id"],
                created_at=row["created_at"],
                reason=row["reason"],
                severity=row["severity"],
                status=row["status"],
                notes=row["notes"],
                files=_from_json(row["files_json"], []),
            )
            for row in rows
        ]

    def count_open_reviews(self, repo_id: str, branch: str) -> int:
        """Count open review items for a slip."""
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM review_items
                WHERE repo_id = ? AND branch = ? AND status = 'open'
                """,
                (repo_id, branch),
            ).fetchone()
        return int(row["count"]) if row else 0

    def has_high_open_review(self, repo_id: str, branch: str) -> bool:
        """Return true when slip has high-severity open review."""
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM review_items
                WHERE repo_id = ? AND branch = ? AND status = 'open' AND severity = 'high'
                """,
                (repo_id, branch),
            ).fetchone()
        return bool(row and row["count"] > 0)

    def get_latest_checkpoint(
        self,
        repo_id: str,
        branch: str | None = None,
    ) -> Checkpoint | None:
        """Fetch latest checkpoint for repo (and optional branch)."""
        query = """
            SELECT *
            FROM checkpoints
            WHERE repo_id = ?
        """
        params: list[Any] = [repo_id]
        if branch:
            query += " AND branch = ?"
            params.append(branch)
        query += " ORDER BY created_at DESC LIMIT 1"
        with self.connect() as conn:
            row = conn.execute(query, tuple(params)).fetchone()
        if not row:
            return None
        return self._row_to_checkpoint(row)

    def get_checkpoint(self, checkpoint_id: str) -> Checkpoint | None:
        """Fetch checkpoint by primary key."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM checkpoints WHERE id = ? LIMIT 1",
                (checkpoint_id,),
            ).fetchone()
        if not row:
            return None
        return self._row_to_checkpoint(row)

    def resolve_berth(self, berth_lookup: str) -> Berth | None:
        """Resolve berth by repo_id or exact name."""
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT repo_id, name, root_path, remote_url, created_at, updated_at
                FROM berths
                WHERE repo_id = ? OR name = ?
                LIMIT 1
                """,
                (berth_lookup, berth_lookup),
            ).fetchone()
        if not row:
            return None
        return Berth(
            repo_id=row["repo_id"],
            name=row["name"],
            root_path=row["root_path"],
            remote_url=row["remote_url"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_harbor(
        self,
        stale_days: int | None = None,
        tag: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """List slips with berth metadata and open review counts."""
        query = """
            SELECT
                s.repo_id,
                b.name AS berth_name,
                s.branch,
                s.status,
                s.updated_at,
                s.tags_json,
                c.objective,
                c.next_steps_json,
                COALESCE((
                    SELECT COUNT(*)
                    FROM review_items r
                    WHERE r.repo_id = s.repo_id AND r.branch = s.branch AND r.status = 'open'
                ), 0) AS open_review_count
            FROM slips s
            JOIN berths b ON b.repo_id = s.repo_id
            LEFT JOIN checkpoints c ON c.id = s.last_checkpoint_id
        """
        with self.connect() as conn:
            rows = conn.execute(query).fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            tags = _from_json(row["tags_json"], [])
            if tag and tag not in tags:
                continue
            item = {
                "repo_id": row["repo_id"],
                "berth_name": row["berth_name"],
                "branch": row["branch"],
                "status": row["status"],
                "updated_at": row["updated_at"],
                "tags": tags,
                "objective": row["objective"] or "",
                "next_steps": _from_json(row["next_steps_json"], []),
                "open_review_count": int(row["open_review_count"]),
            }
            results.append(item)

        if stale_days is not None:
            from datetime import datetime, timedelta, timezone

            threshold = datetime.now(timezone.utc) - timedelta(days=stale_days)
            filtered: list[dict[str, Any]] = []
            for item in results:
                try:
                    updated = datetime.fromisoformat(item["updated_at"])
                except ValueError:
                    continue
                if updated <= threshold:
                    filtered.append(item)
            results = filtered

        severity_rank = {"red": 3, "yellow": 2, "green": 1}
        results.sort(
            key=lambda entry: (
                -entry["open_review_count"],
                -severity_rank.get(entry["status"], 0),
                entry["updated_at"],
            )
        )
        if limit is not None:
            results = results[:limit]
        return results

    def search_checkpoints(
        self,
        query: str,
        tag: str | None = None,
        repo_id: str | None = None,
        branch: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search checkpoints by textual content with optional filters."""
        with self.connect() as conn:
            if self._has_fts(conn):
                base = """
                    SELECT c.id, c.repo_id, c.branch, c.created_at, c.objective, c.decisions, c.next_steps_json, c.tags_json
                    FROM checkpoint_fts f
                    JOIN checkpoints c ON c.id = f.checkpoint_id
                    WHERE checkpoint_fts MATCH ?
                """
                params: list[Any] = [query]
            else:
                like = f"%{query}%"
                base = """
                    SELECT id, repo_id, branch, created_at, objective, decisions, next_steps_json, tags_json
                    FROM checkpoints
                    WHERE objective LIKE ? OR decisions LIKE ? OR next_steps_json LIKE ? OR risks_review LIKE ?
                """
                params = [like, like, like, like]

            if repo_id:
                base += " AND c.repo_id = ?" if " c." in base else " AND repo_id = ?"
                params.append(repo_id)
            if branch:
                base += " AND c.branch = ?" if " c." in base else " AND branch = ?"
                params.append(branch)
            base += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(base, tuple(params)).fetchall()

        items: list[dict[str, Any]] = []
        for row in rows:
            tags = _from_json(row["tags_json"], [])
            if tag and tag not in tags:
                continue
            objective = row["objective"] or ""
            decisions = row["decisions"] or ""
            snippet = objective if query.lower() in objective.lower() else decisions[:140]
            items.append(
                {
                    "id": row["id"],
                    "repo_id": row["repo_id"],
                    "branch": row["branch"],
                    "created_at": row["created_at"],
                    "snippet": snippet.strip(),
                    "objective": objective,
                }
            )
        return items[:limit]

    def _has_fts(self, conn: sqlite3.Connection) -> bool:
        """Return whether FTS table is available."""
        row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM sqlite_master
            WHERE type='table' AND name='checkpoint_fts'
            """
        ).fetchone()
        return bool(row and row["count"] > 0)

    def _row_to_checkpoint(self, row: sqlite3.Row) -> Checkpoint:
        """Convert checkpoint row to model instance."""
        verification = VerificationState(
            tests_run=bool(row["tests_run"]),
            tests_command=row["tests_command"],
            tests_timestamp=row["tests_timestamp"],
            build_ok=bool(row["build_ok"]),
            build_command=row["build_command"],
            build_timestamp=row["build_timestamp"],
            lint_ok=bool(row["lint_ok"]),
            lint_command=row["lint_command"],
            lint_timestamp=row["lint_timestamp"],
            smoke_ok=bool(row["smoke_ok"]),
            smoke_notes=row["smoke_notes"],
            smoke_timestamp=row["smoke_timestamp"],
        )
        return Checkpoint(
            id=row["id"],
            repo_id=row["repo_id"],
            branch=row["branch"],
            created_at=row["created_at"],
            objective=row["objective"],
            decisions=row["decisions"],
            next_steps=_from_json(row["next_steps_json"], []),
            risks_review=row["risks_review"],
            resume_commands=_from_json(row["resume_commands_json"], []),
            git_dirty=bool(row["git_dirty"]),
            head_sha=row["head_sha"],
            head_subject=row["head_subject"],
            recent_commits=_from_json(row["recent_commits_json"], []),
            diff_files_changed=int(row["diff_files_changed"]),
            diff_insertions=int(row["diff_insertions"]),
            diff_deletions=int(row["diff_deletions"]),
            touched_files=_from_json(row["touched_files_json"], []),
            diff_stat_text=row["diff_stat_text"],
            verification=verification,
            tags=_from_json(row["tags_json"], []),
        )
