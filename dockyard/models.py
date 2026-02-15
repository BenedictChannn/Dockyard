"""Domain models for Dockyard entities."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(slots=True)
class Berth:
    """Represents a repository identity (project) in Dockyard.

    Attributes:
        repo_id: Stable repository identifier hash.
        name: Human-friendly berth name.
        root_path: Absolute repository root path.
        remote_url: Git remote URL when available.
        created_at: Record creation timestamp.
        updated_at: Last update timestamp.
    """

    repo_id: str
    name: str
    root_path: str
    remote_url: str | None
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class VerificationState:
    """Represents explicit verification evidence for a checkpoint."""

    tests_run: bool = False
    tests_command: str | None = None
    tests_timestamp: str | None = None
    build_ok: bool = False
    build_command: str | None = None
    build_timestamp: str | None = None
    lint_ok: bool = False
    lint_command: str | None = None
    lint_timestamp: str | None = None
    smoke_ok: bool = False
    smoke_notes: str | None = None
    smoke_timestamp: str | None = None


@dataclass(slots=True)
class Checkpoint:
    """Represents a captured work checkpoint."""

    id: str
    repo_id: str
    branch: str
    created_at: str
    objective: str
    decisions: str
    next_steps: list[str]
    risks_review: str
    resume_commands: list[str]
    git_dirty: bool
    head_sha: str
    head_subject: str
    recent_commits: list[str]
    diff_files_changed: int
    diff_insertions: int
    diff_deletions: int
    touched_files: list[str]
    diff_stat_text: str
    verification: VerificationState
    tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Slip:
    """Represents a branch-scoped workstream under a berth."""

    repo_id: str
    branch: str
    last_checkpoint_id: str | None
    status: str
    tags: list[str] = field(default_factory=list)
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class ReviewItem:
    """Represents a review item tracked by Dockyard."""

    id: str
    repo_id: str
    branch: str
    checkpoint_id: str | None
    created_at: str
    reason: str
    severity: str
    status: str
    notes: str | None = None
    files: list[str] = field(default_factory=list)


@dataclass(slots=True)
class LinkItem:
    """Represents a URL attached to a branch context."""

    id: str
    repo_id: str
    branch: str
    url: str
    created_at: str


@dataclass(slots=True)
class SaveInput:
    """Structured input for creating a checkpoint."""

    objective: str
    decisions: str
    next_steps: list[str]
    risks_review: str
    resume_commands: list[str]
    tags: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)


@dataclass(slots=True)
class GitSnapshot:
    """Represents auto-captured git metadata used in checkpoints."""

    root_path: str
    branch: str
    repo_id: str
    remote_url: str | None
    head_sha: str
    head_subject: str
    git_dirty: bool
    recent_commits: list[str]
    diff_files_changed: int
    diff_insertions: int
    diff_deletions: int
    touched_files: list[str]
    diff_stat_text: str


def checkpoint_to_jsonable(checkpoint: Checkpoint, open_reviews: int = 0) -> dict[str, Any]:
    """Convert checkpoint to JSON-serializable dictionary.

    Args:
        checkpoint: Checkpoint model instance.
        open_reviews: Number of open review items for this slip.

    Returns:
        JSON-friendly dictionary representing the checkpoint.
    """
    return {
        "id": checkpoint.id,
        "repo_id": checkpoint.repo_id,
        "branch": checkpoint.branch,
        "created_at": checkpoint.created_at,
        "objective": checkpoint.objective,
        "decisions": checkpoint.decisions,
        "next_steps": checkpoint.next_steps,
        "risks_review": checkpoint.risks_review,
        "resume_commands": checkpoint.resume_commands,
        "git_dirty": checkpoint.git_dirty,
        "head_sha": checkpoint.head_sha,
        "head_subject": checkpoint.head_subject,
        "recent_commits": checkpoint.recent_commits,
        "diff_files_changed": checkpoint.diff_files_changed,
        "diff_insertions": checkpoint.diff_insertions,
        "diff_deletions": checkpoint.diff_deletions,
        "touched_files": checkpoint.touched_files,
        "diff_stat_text": checkpoint.diff_stat_text,
        "verification": checkpoint.verification.__dict__,
        "tags": checkpoint.tags,
        "open_reviews": open_reviews,
    }
