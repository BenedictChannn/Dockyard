"""Markdown checkpoint storage backend."""

from __future__ import annotations

from pathlib import Path

from dockyard.config import DockyardPaths
from dockyard.models import Checkpoint


def _safe_branch(branch: str) -> str:
    """Normalize branch name for filesystem paths."""
    return branch.replace("/", "__")


def checkpoint_path(paths: DockyardPaths, checkpoint: Checkpoint) -> Path:
    """Compute markdown file path for a checkpoint."""
    return (
        paths.checkpoints_dir
        / checkpoint.repo_id
        / _safe_branch(checkpoint.branch)
        / f"{checkpoint.id}.md"
    )


def render_checkpoint_markdown(checkpoint: Checkpoint) -> str:
    """Render checkpoint model to markdown text."""
    lines = [
        "---",
        f"id: {checkpoint.id}",
        f"repo_id: {checkpoint.repo_id}",
        f"branch: {checkpoint.branch}",
        f"created_at: {checkpoint.created_at}",
        f"head_sha: {checkpoint.head_sha}",
        f"head_subject: {checkpoint.head_subject}",
        f"git_dirty: {str(checkpoint.git_dirty).lower()}",
        f"diff_files_changed: {checkpoint.diff_files_changed}",
        f"diff_insertions: {checkpoint.diff_insertions}",
        f"diff_deletions: {checkpoint.diff_deletions}",
        f"tags: {', '.join(checkpoint.tags)}",
        "---",
        "",
        "## Objective",
        checkpoint.objective.strip(),
        "",
        "## Decisions/Findings",
        checkpoint.decisions.strip(),
        "",
        "## Next Steps",
        *[f"{idx + 1}. {step}" for idx, step in enumerate(checkpoint.next_steps)],
        "",
        "## Risks / Review Needed",
        checkpoint.risks_review.strip(),
        "",
        "## Resume Commands",
        *[f"- `{command}`" for command in checkpoint.resume_commands],
        "",
        "## Auto-captured Git Evidence",
        f"- Branch: `{checkpoint.branch}`",
        f"- Dirty: `{checkpoint.git_dirty}`",
        f"- Touched files: `{len(checkpoint.touched_files)}`",
        "",
        "### Recent Commits",
        *[f"- {entry}" for entry in checkpoint.recent_commits],
        "",
        "### Touched Files",
        *[f"- `{path}`" for path in checkpoint.touched_files],
        "",
        "### Diff Stat",
        "```",
        checkpoint.diff_stat_text.strip() or "(no diff)",
        "```",
        "",
        "## Verification",
        f"- tests_run: `{checkpoint.verification.tests_run}`",
        f"- tests_command: `{checkpoint.verification.tests_command or ''}`",
        f"- tests_timestamp: `{checkpoint.verification.tests_timestamp or ''}`",
        f"- build_ok: `{checkpoint.verification.build_ok}`",
        f"- build_command: `{checkpoint.verification.build_command or ''}`",
        f"- build_timestamp: `{checkpoint.verification.build_timestamp or ''}`",
        f"- lint_ok: `{checkpoint.verification.lint_ok}`",
        f"- lint_command: `{checkpoint.verification.lint_command or ''}`",
        f"- lint_timestamp: `{checkpoint.verification.lint_timestamp or ''}`",
        f"- smoke_ok: `{checkpoint.verification.smoke_ok}`",
        f"- smoke_notes: `{checkpoint.verification.smoke_notes or ''}`",
        f"- smoke_timestamp: `{checkpoint.verification.smoke_timestamp or ''}`",
        "",
    ]
    return "\n".join(lines)


def write_checkpoint(paths: DockyardPaths, checkpoint: Checkpoint) -> Path:
    """Write checkpoint markdown and return file path."""
    path = checkpoint_path(paths, checkpoint)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_checkpoint_markdown(checkpoint), encoding="utf-8")
    return path
