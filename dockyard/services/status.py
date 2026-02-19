"""Status heuristic computations for slips."""

from __future__ import annotations

from dockyard.models import Checkpoint


def compute_slip_status(
    checkpoint: Checkpoint,
    open_review_count: int,
    has_high_open_review: bool,
) -> str:
    """Compute slip status (green/yellow/red) from checkpoint and reviews.

    Rules are aligned to the PRD:
    - Green: tests_run and build_ok and no high open reviews.
    - Yellow: some verification missing or open low/med reviews.
    - Red: risky conditions with no verification/review confidence.

    Args:
        checkpoint: Latest checkpoint for the slip.
        open_review_count: Number of open review items.
        has_high_open_review: Whether a high-severity review is open.

    Returns:
        Status string: `green`, `yellow`, or `red`.
    """
    large_diff = checkpoint.diff_files_changed >= 15 or (
        checkpoint.diff_insertions + checkpoint.diff_deletions >= 400
    )
    risky_paths_touched = any(
        token in path.lower()
        for path in checkpoint.touched_files
        for token in ("auth/", "infra/", ".github/", "terraform/", "migrations/", "payments/", "security/")
    )

    if has_high_open_review:
        return "red"
    if risky_paths_touched and not checkpoint.verification.tests_run:
        return "red"
    if large_diff and open_review_count == 0:
        return "red"

    tests_ok = checkpoint.verification.tests_run
    build_ok = checkpoint.verification.build_ok
    if tests_ok and build_ok and open_review_count == 0:
        return "green"
    return "yellow"
