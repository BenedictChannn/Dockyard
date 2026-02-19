"""Tests for checkpoint creation and markdown persistence."""

from __future__ import annotations

from pathlib import Path

from dockyard.config import resolve_paths
from dockyard.git_info import inspect_repository
from dockyard.models import SaveInput, VerificationState
from dockyard.services.checkpoints import create_checkpoint
from dockyard.storage.sqlite_store import SQLiteStore


def test_create_checkpoint_writes_markdown_and_index(
    git_repo: Path,
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Checkpoint creation should persist both markdown and SQLite records."""
    monkeypatch.setenv("DOCKYARD_HOME", str(tmp_path / ".dockyard_data"))
    paths = resolve_paths()
    store = SQLiteStore(paths.db_path)
    store.initialize()
    snapshot = inspect_repository(root_override=str(git_repo))

    user_input = SaveInput(
        objective="Implement save flow",
        decisions="Use sqlite + markdown",
        next_steps=["Add tests", "Polish docs"],
        risks_review="Need review on schema migration behavior",
        resume_commands=["pytest -q"],
        tags=["mvp"],
    )
    verification = VerificationState(
        tests_run=True,
        tests_command="pytest -q",
        build_ok=True,
        build_command="python -m build",
        lint_ok=False,
        smoke_ok=False,
    )
    checkpoint, _, _ = create_checkpoint(
        store=store,
        paths=paths,
        git=snapshot,
        user_input=user_input,
        verification=verification,
    )
    indexed = store.get_latest_checkpoint(snapshot.repo_id, snapshot.branch)
    assert indexed is not None
    assert indexed.id == checkpoint.id
    markdown_path = (
        paths.checkpoints_dir / checkpoint.repo_id / checkpoint.branch.replace("/", "__") / f"{checkpoint.id}.md"
    )
    assert markdown_path.exists()
    assert "## Objective" in markdown_path.read_text(encoding="utf-8")
