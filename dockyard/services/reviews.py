"""Review suggestion and management helpers."""

from __future__ import annotations

import re
import uuid

from dockyard.config import ReviewHeuristicsConfig, default_runtime_config
from dockyard.models import Checkpoint, ReviewItem, utc_now_iso


def review_triggers(
    checkpoint: Checkpoint,
    heuristics: ReviewHeuristicsConfig | None = None,
) -> list[str]:
    """Return list of review trigger reasons for a checkpoint."""
    config = heuristics or default_runtime_config().review_heuristics
    triggers: list[str] = []
    risky_patterns = [re.compile(pattern) for pattern in config.risky_path_patterns]

    touches_risky_path = any(
        any(pattern.search(path.lower()) for pattern in risky_patterns)
        for path in checkpoint.touched_files
    )
    if touches_risky_path:
        triggers.append("risky_paths_touched")

    churn = checkpoint.diff_insertions + checkpoint.diff_deletions
    if checkpoint.diff_files_changed >= config.files_changed_threshold:
        triggers.append("many_files_changed")
    if churn >= config.churn_threshold:
        triggers.append("large_diff_churn")

    non_trivial = (
        checkpoint.diff_files_changed >= config.non_trivial_files_threshold
        or churn >= config.non_trivial_churn_threshold
    )
    if non_trivial and not checkpoint.verification.tests_run:
        triggers.append("missing_tests_non_trivial_diff")

    branch = checkpoint.branch.lower()
    branch_prefixes = tuple(prefix.lower() for prefix in (config.branch_prefixes or []))
    if branch_prefixes and branch.startswith(branch_prefixes):
        triggers.append("release_or_hotfix_branch")
    return triggers


def severity_from_triggers(triggers: list[str]) -> str:
    """Compute severity level from trigger set."""
    high_set = {
        "risky_paths_touched",
        "large_diff_churn",
        "release_or_hotfix_branch",
    }
    if any(trigger in high_set for trigger in triggers):
        return "high"
    if triggers:
        return "med"
    return "low"


def build_review_item(
    checkpoint: Checkpoint,
    triggers: list[str],
    notes: str | None = None,
) -> ReviewItem:
    """Create a review item model based on checkpoint heuristic triggers."""
    review_id = f"rev_{uuid.uuid4().hex[:10]}"
    reason = ", ".join(triggers) if triggers else "manual"
    severity = severity_from_triggers(triggers)
    return ReviewItem(
        id=review_id,
        repo_id=checkpoint.repo_id,
        branch=checkpoint.branch,
        checkpoint_id=checkpoint.id,
        created_at=utc_now_iso(),
        reason=reason,
        severity=severity,
        status="open",
        notes=notes,
        files=checkpoint.touched_files[:20],
    )
