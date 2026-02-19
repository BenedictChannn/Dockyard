"""Checkpoint orchestration service."""

from __future__ import annotations

import uuid
from pathlib import Path

from dockyard.config import ReviewHeuristicsConfig
from dockyard.models import (
    Berth,
    Checkpoint,
    GitSnapshot,
    LinkItem,
    SaveInput,
    Slip,
    VerificationState,
    utc_now_iso,
)
from dockyard.services.reviews import build_review_item, review_triggers
from dockyard.services.status import compute_slip_status
from dockyard.storage.markdown_store import write_checkpoint
from dockyard.storage.sqlite_store import SQLiteStore


def berth_name_from_root(root_path: str) -> str:
    """Derive berth display name from repository root path."""
    return Path(root_path).name


def create_checkpoint(
    store: SQLiteStore,
    paths,
    git: GitSnapshot,
    user_input: SaveInput,
    verification: VerificationState,
    create_review_on_trigger: bool = True,
    review_heuristics: ReviewHeuristicsConfig | None = None,
) -> tuple[Checkpoint, list[str], str | None]:
    """Create and persist checkpoint plus optional review item.

    Args:
        store: SQLite storage layer.
        paths: Resolved dockyard paths.
        git: Auto-captured git snapshot.
        user_input: Prompt- or flag-collected user checkpoint inputs.
        verification: Structured verification state.
        create_review_on_trigger: Whether to auto-create review item if triggered.
        review_heuristics: Optional review trigger config overrides.

    Returns:
        Tuple containing checkpoint, trigger list, and optional created review id.
    """
    created_at = utc_now_iso()
    checkpoint = Checkpoint(
        id=f"cp_{uuid.uuid4().hex[:12]}",
        repo_id=git.repo_id,
        branch=git.branch,
        created_at=created_at,
        objective=user_input.objective.strip(),
        decisions=user_input.decisions.strip(),
        next_steps=[step.strip() for step in user_input.next_steps if step.strip()][:3],
        risks_review=user_input.risks_review.strip(),
        resume_commands=[command.strip() for command in user_input.resume_commands if command.strip()][:5],
        git_dirty=git.git_dirty,
        head_sha=git.head_sha,
        head_subject=git.head_subject,
        recent_commits=git.recent_commits,
        diff_files_changed=git.diff_files_changed,
        diff_insertions=git.diff_insertions,
        diff_deletions=git.diff_deletions,
        touched_files=git.touched_files,
        diff_stat_text=git.diff_stat_text,
        verification=verification,
        tags=user_input.tags,
    )
    berth = Berth(
        repo_id=git.repo_id,
        name=berth_name_from_root(git.root_path),
        root_path=git.root_path,
        remote_url=git.remote_url,
        updated_at=created_at,
    )
    store.upsert_berth(berth)
    write_checkpoint(paths, checkpoint)
    store.add_checkpoint(checkpoint)

    for url in user_input.links:
        store.add_link(
            LinkItem(
                id=f"lnk_{uuid.uuid4().hex[:10]}",
                repo_id=git.repo_id,
                branch=git.branch,
                url=url,
                created_at=created_at,
            )
        )

    triggers = review_triggers(checkpoint, heuristics=review_heuristics)
    created_review_id: str | None = None
    if triggers and create_review_on_trigger:
        review = build_review_item(checkpoint, triggers)
        store.add_review_item(review)
        created_review_id = review.id

    open_review_count = store.count_open_reviews(checkpoint.repo_id, checkpoint.branch)
    has_high_open_review = store.has_high_open_review(checkpoint.repo_id, checkpoint.branch)
    status = compute_slip_status(
        checkpoint=checkpoint,
        open_review_count=open_review_count,
        has_high_open_review=has_high_open_review,
    )
    slip = Slip(
        repo_id=checkpoint.repo_id,
        branch=checkpoint.branch,
        last_checkpoint_id=checkpoint.id,
        status=status,
        tags=checkpoint.tags,
        updated_at=created_at,
    )
    store.upsert_slip(slip)
    return checkpoint, triggers, created_review_id
