"""Git metadata collection helpers."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from dockyard.errors import NotGitRepositoryError
from dockyard.models import GitSnapshot


def _run_git(args: list[str], cwd: Path) -> str:
    """Run a git command and return stdout.

    Args:
        args: Git command arguments without leading `git`.
        cwd: Working directory for the command.

    Returns:
        Command stdout stripped of trailing whitespace.

    Raises:
        subprocess.CalledProcessError: If git exits with non-zero status.
    """
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def detect_repo_root(start: str | Path | None = None) -> Path:
    """Detect git repository root from a starting path.

    Args:
        start: Optional starting path. Defaults to current working directory.

    Returns:
        Absolute repository root path.

    Raises:
        NotGitRepositoryError: If repository root cannot be determined.
    """
    cwd = Path(start or ".").resolve()
    try:
        root = _run_git(["rev-parse", "--show-toplevel"], cwd=cwd)
    except subprocess.CalledProcessError as exc:
        raise NotGitRepositoryError("Current path is not inside a git repository.") from exc
    return Path(root).resolve()


def _current_branch(repo_root: Path) -> str:
    """Return current branch name or detached head pseudo-name."""
    try:
        branch = _run_git(["symbolic-ref", "--quiet", "--short", "HEAD"], cwd=repo_root)
        if branch:
            return branch
    except subprocess.CalledProcessError:
        pass

    head_sha = _run_git(["rev-parse", "--short", "HEAD"], cwd=repo_root)
    return f"DETACHED@{head_sha}"


def _repo_id(remote_url: str | None, root_path: Path) -> str:
    """Return stable repository identifier hash."""
    source = remote_url.strip() if remote_url else str(root_path)
    digest = hashlib.sha1(source.encode("utf-8")).hexdigest()
    return digest[:16]


def _remote_url(repo_root: Path) -> str | None:
    """Return preferred remote URL for repo identity, if available."""
    try:
        url = _run_git(["config", "--get", "remote.origin.url"], cwd=repo_root)
        if url:
            return url
    except subprocess.CalledProcessError:
        pass

    try:
        remotes = _run_git(["remote"], cwd=repo_root).splitlines()
    except subprocess.CalledProcessError:
        return None
    remote_names = sorted({remote.strip() for remote in remotes if remote.strip()})
    for name in remote_names:
        try:
            url = _run_git(["config", "--get", f"remote.{name}.url"], cwd=repo_root)
        except subprocess.CalledProcessError:
            continue
        if url:
            return url
    return None


def _parse_numstat(numstat_text: str) -> tuple[int, int, int]:
    """Parse `git diff --numstat` output into aggregate counts."""
    files_changed = 0
    insertions = 0
    deletions = 0
    for line in numstat_text.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        files_changed += 1
        added, removed = parts[0], parts[1]
        if added.isdigit():
            insertions += int(added)
        if removed.isdigit():
            deletions += int(removed)
    return files_changed, insertions, deletions


def inspect_repository(root_override: str | None = None, recent_commit_count: int = 5) -> GitSnapshot:
    """Collect git snapshot used for Dockyard checkpoints.

    Args:
        root_override: Optional explicit repository root path.
        recent_commit_count: Number of recent commits to capture.

    Returns:
        Populated git snapshot.
    """
    repo_root = detect_repo_root(root_override)
    branch = _current_branch(repo_root)
    remote_url = _remote_url(repo_root)

    head_info = _run_git(["log", "-1", "--pretty=%H%n%s"], cwd=repo_root).splitlines()
    head_sha = head_info[0] if head_info else ""
    head_subject = head_info[1] if len(head_info) > 1 else ""
    status_porcelain = _run_git(["status", "--porcelain", "--untracked-files=all"], cwd=repo_root)
    dirty = bool(status_porcelain)

    # Compare working tree + index against HEAD to capture in-progress work.
    numstat = _run_git(["diff", "--numstat", "HEAD"], cwd=repo_root)
    files_changed, insertions, deletions = _parse_numstat(numstat)
    touched_files = _run_git(["diff", "--name-only", "HEAD"], cwd=repo_root).splitlines()
    untracked_files: list[str] = []
    for line in status_porcelain.splitlines():
        if line.startswith("?? "):
            untracked_files.append(line[3:])

    # Include untracked files because they represent real in-progress work context.
    for path in untracked_files:
        if path not in touched_files:
            touched_files.append(path)
    files_changed += len([path for path in untracked_files if path])

    diff_stat_text = _run_git(["diff", "--stat", "HEAD"], cwd=repo_root)
    if untracked_files:
        untracked_block = "\n".join(f" {path} | untracked" for path in untracked_files)
        if diff_stat_text:
            diff_stat_text = f"{diff_stat_text}\n{untracked_block}"
        else:
            diff_stat_text = untracked_block
    recent_commits = _run_git(
        ["log", f"-{recent_commit_count}", "--pretty=%h %s"],
        cwd=repo_root,
    ).splitlines()

    return GitSnapshot(
        root_path=str(repo_root),
        branch=branch,
        repo_id=_repo_id(remote_url=remote_url, root_path=repo_root),
        remote_url=remote_url or None,
        head_sha=head_sha,
        head_subject=head_subject,
        git_dirty=dirty,
        recent_commits=recent_commits,
        diff_files_changed=files_changed,
        diff_insertions=insertions,
        diff_deletions=deletions,
        touched_files=[path for path in touched_files if path],
        diff_stat_text=diff_stat_text,
    )
