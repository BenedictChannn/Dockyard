"""Review suggestion and management helpers."""

from __future__ import annotations

import re
import uuid

from dockyard.models import Checkpoint, ReviewItem, utc_now_iso

RISKY_PATH_PATTERNS = [
    re.compile(r"(^|/)auth/"),
    re.compile(r"(^|/)infra/"),
    re.compile(r"(^|/)\.github/"),
    re.compile(r"(^|/)terraform/"),
    re.compile(r"(^|/)migrations/"),
    re.compile(r"(^|/)payments/"),
    re.compile(r"(^|/)security/"),
]


def review_triggers(checkpoint: Checkpoint) -> list[str]:
    """Return list of review trigger reasons for a checkpoint."""
    triggers: list[str] = []

    touches_risky_path = any(
        any(pattern.search(path.lower()) for pattern in RISKY_PATH_PATTERNS)
        for path in checkpoint.touched_files
    )
    if touches_risky_path:
        triggers.append("risky_paths_touched")

    churn = checkpoint.diff_insertions + checkpoint.diff_deletions
    if checkpoint.diff_files_changed >= 15:
        triggers.append("many_files_changed")
    if churn >= 400:
        triggers.append("large_diff_churn")

    non_trivial = checkpoint.diff_files_changed >= 3 or churn >= 80
    if non_trivial and not checkpoint.verification.tests_run:
        triggers.append("missing_tests_non_trivial_diff")

    branch = checkpoint.branch.lower()
    if branch.startswith("release/") or branch.startswith("hotfix/"):
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
