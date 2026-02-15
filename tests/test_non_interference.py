"""Tests ensuring Dockyard does not mutate project repos by default."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path


def _run(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> str:
    """Run subprocess command and return stdout."""
    result = subprocess.run(
        command,
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return result.stdout.strip()


def test_save_no_prompt_keeps_repo_working_tree_unchanged(git_repo: Path, tmp_path: Path) -> None:
    """Saving checkpoint should not alter tracked files or git index."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    status_before = _run(["git", "status", "--porcelain"], cwd=git_repo)
    assert status_before == ""

    _run(
        [
            "python3",
            "-m",
            "dockyard",
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Checkpoint objective",
            "--decisions",
            "Decision text",
            "--next-step",
            "Do another thing",
            "--risks",
            "Review infra carefully",
            "--command",
            "pytest -q",
            "--tests-run",
            "--tests-command",
            "pytest -q",
            "--build-ok",
            "--build-command",
            "python -m build",
            "--lint-fail",
            "--smoke-fail",
            "--no-auto-review",
        ],
        cwd=git_repo,
        env=env,
    )

    status_after = _run(["git", "status", "--porcelain"], cwd=git_repo)
    assert status_after == ""


def test_read_only_commands_do_not_modify_repo(git_repo: Path, tmp_path: Path) -> None:
    """Resume/ls/search/review read paths must not mutate repository state."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run(
        [
            "python3",
            "-m",
            "dockyard",
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Read-only command baseline",
            "--decisions",
            "Validate non-mutating command paths",
            "--next-step",
            "Run resume and harbor commands",
            "--risks",
            "None",
            "--command",
            "echo do-not-run",
            "--tests-run",
            "--tests-command",
            "pytest -q",
            "--build-ok",
            "--build-command",
            "echo build",
            "--lint-fail",
            "--smoke-fail",
            "--no-auto-review",
        ],
        cwd=git_repo,
        env=env,
    )

    status_before = _run(["git", "status", "--porcelain"], cwd=git_repo)
    assert status_before == ""

    _run(["python3", "-m", "dockyard", "resume"], cwd=git_repo, env=env)
    _run(["python3", "-m", "dockyard", "r"], cwd=git_repo, env=env)
    _run(["python3", "-m", "dockyard", "undock"], cwd=git_repo, env=env)
    _run(["python3", "-m", "dockyard", "ls"], cwd=tmp_path, env=env)
    _run(["python3", "-m", "dockyard", "harbor"], cwd=tmp_path, env=env)
    _run(["python3", "-m", "dockyard", "search", "baseline"], cwd=tmp_path, env=env)
    _run(["python3", "-m", "dockyard", "f", "baseline"], cwd=tmp_path, env=env)
    _run(["python3", "-m", "dockyard", "search", "baseline", "--json"], cwd=tmp_path, env=env)
    _run(["python3", "-m", "dockyard", "review"], cwd=tmp_path, env=env)
    _run(["python3", "-m", "dockyard", "links"], cwd=git_repo, env=env)

    status_after = _run(["git", "status", "--porcelain"], cwd=git_repo)
    assert status_after == ""


def test_review_and_link_commands_do_not_modify_repo(git_repo: Path, tmp_path: Path) -> None:
    """Dockyard metadata mutations must not alter repository working tree."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run(
        [
            "python3",
            "-m",
            "dockyard",
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Mutation command baseline",
            "--decisions",
            "Validate review/link non-interference",
            "--next-step",
            "Run link and review commands",
            "--risks",
            "none",
            "--command",
            "echo noop",
            "--tests-run",
            "--tests-command",
            "pytest -q",
            "--build-ok",
            "--build-command",
            "echo build",
            "--lint-fail",
            "--smoke-fail",
            "--no-auto-review",
        ],
        cwd=git_repo,
        env=env,
    )

    status_before = _run(["git", "status", "--porcelain"], cwd=git_repo)
    assert status_before == ""

    _run(
        ["python3", "-m", "dockyard", "link", "https://example.com/non-interference"],
        cwd=git_repo,
        env=env,
    )
    review_output = _run(
        [
            "python3",
            "-m",
            "dockyard",
            "review",
            "add",
            "--reason",
            "manual",
            "--severity",
            "low",
        ],
        cwd=git_repo,
        env=env,
    )
    review_match = re.search(r"rev_[a-f0-9]+", review_output)
    assert review_match is not None
    _run(
        ["python3", "-m", "dockyard", "review", "done", review_match.group(0)],
        cwd=git_repo,
        env=env,
    )

    status_after = _run(["git", "status", "--porcelain"], cwd=git_repo)
    assert status_after == ""


def test_save_with_editor_does_not_modify_repo(git_repo: Path, tmp_path: Path) -> None:
    """Editor-assisted save flow should not alter project working tree/index."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    editor_script = tmp_path / "editor.sh"
    editor_script.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "printf 'Editor decisions for non-interference\\n' > \"$1\"",
            ]
        ),
        encoding="utf-8",
    )
    editor_script.chmod(0o755)
    env["EDITOR"] = str(editor_script)

    status_before = _run(["git", "status", "--porcelain"], cwd=git_repo)
    assert status_before == ""

    _run(
        [
            "python3",
            "-m",
            "dockyard",
            "save",
            "--root",
            str(git_repo),
            "--editor",
            "--no-prompt",
            "--objective",
            "Editor non-interference objective",
            "--next-step",
            "run resume",
            "--risks",
            "none",
            "--command",
            "echo noop",
            "--tests-run",
            "--tests-command",
            "pytest -q",
            "--build-ok",
            "--build-command",
            "echo build",
            "--lint-fail",
            "--smoke-fail",
            "--no-auto-review",
        ],
        cwd=git_repo,
        env=env,
    )

    status_after = _run(["git", "status", "--porcelain"], cwd=git_repo)
    assert status_after == ""


def test_save_with_template_does_not_modify_repo(git_repo: Path, tmp_path: Path) -> None:
    """Template-driven save flow should not alter project working tree/index."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    template_path = tmp_path / "save_template.json"
    template_path.write_text(
        json.dumps(
            {
                "objective": "Template non-interference objective",
                "decisions": "Template decisions",
                "next_steps": ["Run resume"],
                "risks_review": "none",
                "resume_commands": ["echo noop"],
                "verification": {"tests_run": True, "build_ok": True},
            }
        ),
        encoding="utf-8",
    )

    status_before = _run(["git", "status", "--porcelain"], cwd=git_repo)
    assert status_before == ""

    _run(
        [
            "python3",
            "-m",
            "dockyard",
            "save",
            "--root",
            str(git_repo),
            "--template",
            str(template_path),
            "--no-prompt",
            "--no-auto-review",
        ],
        cwd=git_repo,
        env=env,
    )

    status_after = _run(["git", "status", "--porcelain"], cwd=git_repo)
    assert status_after == ""


def test_bare_dock_command_does_not_modify_repo(git_repo: Path, tmp_path: Path) -> None:
    """Bare dock command (harbor view) should not alter repo state."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    status_before = _run(["git", "status", "--porcelain"], cwd=git_repo)
    assert status_before == ""

    _run(["python3", "-m", "dockyard"], cwd=git_repo, env=env)

    status_after = _run(["git", "status", "--porcelain"], cwd=git_repo)
    assert status_after == ""


def test_dock_alias_save_does_not_modify_repo(git_repo: Path, tmp_path: Path) -> None:
    """`dock dock` alias save flow should not alter project working tree/index."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    status_before = _run(["git", "status", "--porcelain"], cwd=git_repo)
    assert status_before == ""

    _run(
        [
            "python3",
            "-m",
            "dockyard",
            "dock",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Dock alias save objective",
            "--decisions",
            "Dock alias save decisions",
            "--next-step",
            "Run resume",
            "--risks",
            "none",
            "--command",
            "echo noop",
            "--tests-run",
            "--tests-command",
            "pytest -q",
            "--build-ok",
            "--build-command",
            "echo build",
            "--lint-fail",
            "--smoke-fail",
            "--no-auto-review",
        ],
        cwd=git_repo,
        env=env,
    )

    status_after = _run(["git", "status", "--porcelain"], cwd=git_repo)
    assert status_after == ""
