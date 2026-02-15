"""Performance smoke runner for Dockyard query paths.

This script seeds synthetic data and measures the query latency of:
- `dock ls` equivalent (`SQLiteStore.list_harbor`)
- `dock search` equivalent (`SQLiteStore.search_checkpoints`)

By default it reports timings only. Use `--enforce-targets` to fail when
measured timings exceed PRD targets.
"""

from __future__ import annotations

import argparse
import time
import uuid
from pathlib import Path

from dockyard.models import Berth, Checkpoint, Slip, VerificationState
from dockyard.storage.sqlite_store import SQLiteStore


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for smoke performance run."""
    parser = argparse.ArgumentParser(description="Dockyard performance smoke test")
    parser.add_argument(
        "--db-path",
        type=Path,
        default=Path("/tmp/dockyard_perf_smoke.sqlite"),
        help="SQLite path to use for synthetic benchmark data.",
    )
    parser.add_argument(
        "--berths",
        type=int,
        default=200,
        help="Number of berths to seed.",
    )
    parser.add_argument(
        "--checkpoints",
        type=int,
        default=5000,
        help="Total number of checkpoints to seed.",
    )
    parser.add_argument(
        "--enforce-targets",
        action="store_true",
        help="Fail with non-zero exit if measured timings exceed PRD targets.",
    )
    return parser.parse_args()


def build_checkpoint(repo_id: str, branch: str, index: int) -> Checkpoint:
    """Create deterministic synthetic checkpoint payload."""
    return Checkpoint(
        id=f"cp_{repo_id}_{branch}_{index}_{uuid.uuid4().hex[:6]}",
        repo_id=repo_id,
        branch=branch,
        created_at=f"2026-01-{(index % 28) + 1:02d}T12:00:00+00:00",
        objective=f"Objective {index}: improve search pipeline",
        decisions="Synthetic benchmark checkpoint",
        next_steps=["Run perf checks", "Inspect results"],
        risks_review="none",
        resume_commands=["echo benchmark"],
        git_dirty=False,
        head_sha=f"sha{index:06d}",
        head_subject="benchmark seed",
        recent_commits=[f"{index:04d} benchmark seed"],
        diff_files_changed=2,
        diff_insertions=20,
        diff_deletions=5,
        touched_files=[f"src/file_{index % 40}.py"],
        diff_stat_text="2 files changed, 20 insertions(+), 5 deletions(-)",
        verification=VerificationState(
            tests_run=True,
            tests_command="pytest -q",
            tests_timestamp="2026-01-01T00:00:00+00:00",
            build_ok=True,
            build_command="python -m build",
            build_timestamp="2026-01-01T00:00:00+00:00",
            lint_ok=True,
            lint_command="ruff check",
            lint_timestamp="2026-01-01T00:00:00+00:00",
            smoke_ok=True,
            smoke_notes="ok",
            smoke_timestamp="2026-01-01T00:00:00+00:00",
        ),
        tags=["perf", "mvp"] if index % 2 == 0 else ["perf"],
    )


def seed_data(store: SQLiteStore, berth_count: int, checkpoint_count: int) -> None:
    """Seed synthetic dataset for performance smoke checks."""
    branches = ["main", "feature/a", "feature/b"]
    for berth_index in range(berth_count):
        repo_id = f"repo_{berth_index:04d}"
        berth = Berth(
            repo_id=repo_id,
            name=f"repo-{berth_index:04d}",
            root_path=f"/tmp/repo-{berth_index:04d}",
            remote_url=f"git@example.com:repo-{berth_index:04d}.git",
        )
        store.upsert_berth(berth)
        store.upsert_slip(
            Slip(
                repo_id=repo_id,
                branch="main",
                last_checkpoint_id=None,
                status="green",
                tags=["perf"],
                updated_at="2026-01-01T00:00:00+00:00",
            )
        )

    for index in range(checkpoint_count):
        repo_id = f"repo_{index % berth_count:04d}"
        branch = branches[index % len(branches)]
        checkpoint = build_checkpoint(repo_id=repo_id, branch=branch, index=index)
        store.add_checkpoint(checkpoint)
        store.upsert_slip(
            Slip(
                repo_id=repo_id,
                branch=branch,
                last_checkpoint_id=checkpoint.id,
                status="green",
                tags=checkpoint.tags,
                updated_at=checkpoint.created_at,
            )
        )


def main() -> int:
    """Execute perf smoke scenario and optionally enforce PRD targets."""
    args = parse_args()
    if args.db_path.exists():
        args.db_path.unlink()

    store = SQLiteStore(args.db_path)
    store.initialize()
    seed_data(store, berth_count=args.berths, checkpoint_count=args.checkpoints)

    start_ls = time.perf_counter()
    harbor_rows = store.list_harbor(limit=50)
    elapsed_ls_ms = (time.perf_counter() - start_ls) * 1000

    start_search = time.perf_counter()
    search_rows = store.search_checkpoints("search pipeline", limit=20)
    elapsed_search_ms = (time.perf_counter() - start_search) * 1000

    print(
        "dock ls query: "
        f"{elapsed_ls_ms:.2f} ms (rows={len(harbor_rows)}) | "
        "target < 200 ms"
    )
    print(
        "dock search query: "
        f"{elapsed_search_ms:.2f} ms (rows={len(search_rows)}) | "
        "target < 500 ms"
    )

    if not args.enforce_targets:
        return 0

    if elapsed_ls_ms >= 200 or elapsed_search_ms >= 500:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
