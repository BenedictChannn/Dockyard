"""Performance smoke runner for Dockyard query paths.

This script seeds synthetic data and measures the query latency of:
- `dock ls` equivalent (`SQLiteStore.list_harbor`)
- `dock search` equivalent (`SQLiteStore.search_checkpoints`)

By default it reports text timings and context lines. It also supports:
- configurable workload sizing/limits (`--berths`, `--checkpoints`,
  `--ls-limit`, `--search-limit`)
- configurable latency thresholds (`--ls-target-ms`, `--search-target-ms`)
- configurable search workload query (`--search-query`)
- machine-readable output (`--json`)
- threshold-enforced exit behavior (`--enforce-targets`)
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from dockyard.models import Berth, Checkpoint, Slip, VerificationState
from dockyard.storage.sqlite_store import SQLiteStore


def _positive_int_arg(value: str) -> int:
    """Parse argparse integer input requiring value > 0."""
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be an integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def _non_negative_int_arg(value: str) -> int:
    """Parse argparse integer input requiring value >= 0."""
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return parsed


def _non_negative_float_arg(value: str) -> float:
    """Parse argparse float input requiring value >= 0."""
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be a number") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return parsed


def _non_empty_query_arg(value: str) -> str:
    """Parse search query input requiring non-empty trimmed text."""
    normalized = value.strip()
    if not normalized:
        raise argparse.ArgumentTypeError("value must be a non-empty query")
    return normalized


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
        type=_positive_int_arg,
        default=200,
        help="Number of berths to seed.",
    )
    parser.add_argument(
        "--checkpoints",
        type=_non_negative_int_arg,
        default=5000,
        help="Total number of checkpoints to seed.",
    )
    parser.add_argument(
        "--enforce-targets",
        action="store_true",
        help="Fail with non-zero exit if measured timings exceed PRD targets.",
    )
    parser.add_argument(
        "--ls-target-ms",
        type=_non_negative_float_arg,
        default=200.0,
        help="Target threshold (ms) for dock ls query path.",
    )
    parser.add_argument(
        "--search-target-ms",
        type=_non_negative_float_arg,
        default=500.0,
        help="Target threshold (ms) for dock search query path.",
    )
    parser.add_argument(
        "--search-query",
        type=_non_empty_query_arg,
        default="search pipeline",
        help="Search query string used for benchmark lookup.",
    )
    parser.add_argument(
        "--ls-limit",
        type=_positive_int_arg,
        default=50,
        help="Result limit used for harbor query benchmark.",
    )
    parser.add_argument(
        "--search-limit",
        type=_positive_int_arg,
        default=20,
        help="Result limit used for search query benchmark.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit benchmark results as JSON payload.",
    )
    return parser.parse_args()


def build_checkpoint(repo_id: str, branch: str, index: int) -> Checkpoint:
    """Create deterministic synthetic checkpoint payload."""
    branch_key = branch.replace("/", "_")
    return Checkpoint(
        id=f"cp_{repo_id}_{branch_key}_{index:05d}",
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
    if berth_count <= 0:
        raise ValueError("berth_count must be greater than zero")
    if checkpoint_count < 0:
        raise ValueError("checkpoint_count must be non-negative")

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


def _targets_met(
    *,
    elapsed_ls_ms: float,
    elapsed_search_ms: float,
    ls_target_ms: float,
    search_target_ms: float,
) -> bool:
    """Return whether measured latencies satisfy configured thresholds."""
    return elapsed_ls_ms < ls_target_ms and elapsed_search_ms < search_target_ms


def _failed_targets(
    *,
    elapsed_ls_ms: float,
    elapsed_search_ms: float,
    ls_target_ms: float,
    search_target_ms: float,
) -> list[str]:
    """Return target keys that failed configured latency thresholds."""
    failed: list[str] = []
    if elapsed_ls_ms >= ls_target_ms:
        failed.append("ls")
    if elapsed_search_ms >= search_target_ms:
        failed.append("search")
    return failed


def main() -> int:
    """Execute perf smoke scenario and optionally enforce PRD targets."""
    args = parse_args()
    args.db_path.parent.mkdir(parents=True, exist_ok=True)
    if args.db_path.exists():
        args.db_path.unlink()

    store = SQLiteStore(args.db_path)
    store.initialize()
    seed_data(store, berth_count=args.berths, checkpoint_count=args.checkpoints)

    start_ls = time.perf_counter()
    harbor_rows = store.list_harbor(limit=args.ls_limit)
    elapsed_ls_ms = (time.perf_counter() - start_ls) * 1000

    start_search = time.perf_counter()
    search_rows = store.search_checkpoints(args.search_query, limit=args.search_limit)
    elapsed_search_ms = (time.perf_counter() - start_search) * 1000
    targets_met = _targets_met(
        elapsed_ls_ms=elapsed_ls_ms,
        elapsed_search_ms=elapsed_search_ms,
        ls_target_ms=args.ls_target_ms,
        search_target_ms=args.search_target_ms,
    )
    failed_targets = _failed_targets(
        elapsed_ls_ms=elapsed_ls_ms,
        elapsed_search_ms=elapsed_search_ms,
        ls_target_ms=args.ls_target_ms,
        search_target_ms=args.search_target_ms,
    )

    payload = {
        "schema_version": 1,
        "measured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "db_path": str(args.db_path),
        "seed": {
            "berths": args.berths,
            "checkpoints": args.checkpoints,
        },
        "ls": {
            "elapsed_ms": round(elapsed_ls_ms, 2),
            "rows": len(harbor_rows),
            "limit": args.ls_limit,
            "target_ms": args.ls_target_ms,
        },
        "search": {
            "elapsed_ms": round(elapsed_search_ms, 2),
            "rows": len(search_rows),
            "limit": args.search_limit,
            "target_ms": args.search_target_ms,
            "query": args.search_query,
        },
        "targets_met": targets_met,
        "failed_targets": failed_targets,
        "enforce_targets": args.enforce_targets,
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if (not args.enforce_targets or targets_met) else 1

    print(
        "dock ls query: "
        f"{elapsed_ls_ms:.2f} ms (rows={len(harbor_rows)}) | "
        f"target < {args.ls_target_ms:.2f} ms"
    )
    print(
        "dock search query: "
        f"{elapsed_search_ms:.2f} ms (rows={len(search_rows)}) | "
        f"target < {args.search_target_ms:.2f} ms"
    )
    print(f"harbor query limit: {args.ls_limit}")
    print(f"search query limit: {args.search_limit}")
    print(f"search workload query: {args.search_query}")
    if args.enforce_targets and failed_targets:
        print(f"failed targets: {', '.join(failed_targets)}")

    if not args.enforce_targets:
        return 0

    if not targets_met:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
