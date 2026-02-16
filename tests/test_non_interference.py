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


def _run_commands(commands: list[list[str]], cwd: Path, env: dict[str, str]) -> None:
    """Run a sequence of commands in a shared working directory.

    Args:
        commands: Commands to execute in order.
        cwd: Working directory used for all commands.
        env: Environment variables for subprocess execution.
    """
    for command in commands:
        _run(command, cwd=cwd, env=env)


def _assert_repo_clean(git_repo: Path) -> None:
    """Assert repository working tree/index has no pending changes.

    Args:
        git_repo: Repository path to check.
    """
    assert _run(["git", "status", "--porcelain"], cwd=git_repo) == ""


def _configure_editor(env: dict[str, str], tmp_path: Path, script_name: str, decisions_text: str) -> None:
    """Create editor script and wire EDITOR env var for save --editor tests.

    Args:
        env: Mutable environment mapping used by subprocess calls.
        tmp_path: Temporary directory for script placement.
        script_name: Filename for the generated editor script.
        decisions_text: Text the editor writes into the decisions file.
    """
    editor_script = tmp_path / script_name
    editor_script.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                f"printf '{decisions_text}\\n' > \"$1\"",
            ]
        ),
        encoding="utf-8",
    )
    editor_script.chmod(0o755)
    env["EDITOR"] = str(editor_script)


def _write_non_interference_template(template_path: Path, objective: str) -> None:
    """Write baseline template payload used by non-interference tests.

    Args:
        template_path: Destination path for template JSON file.
        objective: Objective string persisted in template payload.
    """
    template_path.write_text(
        json.dumps(
            {
                "objective": objective,
                "decisions": "Template decisions",
                "next_steps": ["Run resume"],
                "risks_review": "none",
                "resume_commands": ["echo noop"],
                "verification": {"tests_run": True, "build_ok": True},
            }
        ),
        encoding="utf-8",
    )


def _save_checkpoint(
    git_repo: Path,
    env: dict[str, str],
    *,
    objective: str,
    decisions: str,
    next_step: str,
    risks: str,
    command: str = "echo noop",
    extra_args: list[str] | None = None,
) -> None:
    """Create a no-prompt checkpoint with shared verification defaults.

    Args:
        git_repo: Target repository root for `dockyard save --root`.
        env: Environment variables used for subprocess execution.
        objective: Save objective text.
        decisions: Save decisions text.
        next_step: Save next-step text.
        risks: Save risks/review-needed text.
        command: Resume command text captured in checkpoint.
        extra_args: Optional additional CLI args appended to save command.
    """
    save_command = [
        "python3",
        "-m",
        "dockyard",
        "save",
        "--root",
        str(git_repo),
        "--no-prompt",
        "--objective",
        objective,
        "--decisions",
        decisions,
        "--next-step",
        next_step,
        "--risks",
        risks,
        "--command",
        command,
        "--tests-run",
        "--tests-command",
        "pytest -q",
        "--build-ok",
        "--build-command",
        "echo build",
        "--lint-fail",
        "--smoke-fail",
        "--no-auto-review",
    ]
    if extra_args:
        save_command.extend(extra_args)
    _run(save_command, cwd=git_repo, env=env)


def test_save_no_prompt_keeps_repo_working_tree_unchanged(git_repo: Path, tmp_path: Path) -> None:
    """Saving checkpoint should not alter tracked files or git index."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _assert_repo_clean(git_repo)

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

    _assert_repo_clean(git_repo)


def test_read_only_commands_do_not_modify_repo(git_repo: Path, tmp_path: Path) -> None:
    """Resume/ls/search/review read paths must not mutate repository state."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    base_branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=git_repo)

    _save_checkpoint(
        git_repo,
        env,
        objective="Read-only command baseline",
        decisions="Validate non-mutating command paths",
        next_step="Run resume and harbor commands",
        risks="None",
        command="echo do-not-run",
        extra_args=["--tag", "baseline"],
    )

    _assert_repo_clean(git_repo)

    in_repo_commands = [
        ["python3", "-m", "dockyard", "resume"],
        ["python3", "-m", "dockyard", "resume", "--json"],
        ["python3", "-m", "dockyard", "resume", "--handoff"],
        ["python3", "-m", "dockyard", "resume", "--branch", base_branch],
        ["python3", "-m", "dockyard", "r"],
        ["python3", "-m", "dockyard", "undock"],
        ["python3", "-m", "dockyard", "links"],
    ]
    _run_commands(in_repo_commands, cwd=git_repo, env=env)

    outside_repo_commands = [
        ["python3", "-m", "dockyard", "resume", git_repo.name],
        ["python3", "-m", "dockyard", "resume", git_repo.name, "--json"],
        ["python3", "-m", "dockyard", "resume", git_repo.name, "--handoff"],
        ["python3", "-m", "dockyard", "resume", git_repo.name, "--branch", base_branch],
        ["python3", "-m", "dockyard", "resume", git_repo.name, "--branch", base_branch, "--json"],
        ["python3", "-m", "dockyard", "resume", git_repo.name, "--branch", base_branch, "--handoff"],
        ["python3", "-m", "dockyard", "ls"],
        ["python3", "-m", "dockyard", "ls", "--json"],
        ["python3", "-m", "dockyard", "ls", "--limit", "1", "--json"],
        ["python3", "-m", "dockyard", "ls", "--stale", "0", "--json"],
        ["python3", "-m", "dockyard", "ls", "--tag", "baseline", "--json"],
        ["python3", "-m", "dockyard", "ls", "--tag", "baseline", "--stale", "0", "--limit", "1", "--json"],
        ["python3", "-m", "dockyard", "harbor"],
        ["python3", "-m", "dockyard", "harbor", "--json"],
        ["python3", "-m", "dockyard", "harbor", "--limit", "1", "--json"],
        ["python3", "-m", "dockyard", "harbor", "--stale", "0", "--json"],
        ["python3", "-m", "dockyard", "harbor", "--tag", "baseline", "--json"],
        ["python3", "-m", "dockyard", "harbor", "--tag", "baseline", "--stale", "0", "--limit", "1", "--json"],
        ["python3", "-m", "dockyard", "harbor", "--tag", "baseline", "--stale", "0", "--limit", "1"],
        ["python3", "-m", "dockyard", "search", "baseline"],
        ["python3", "-m", "dockyard", "search", "baseline", "--json"],
        ["python3", "-m", "dockyard", "search", "baseline", "--tag", "baseline"],
        ["python3", "-m", "dockyard", "search", "baseline", "--tag", "missing-tag"],
        ["python3", "-m", "dockyard", "search", "baseline", "--repo", git_repo.name],
        ["python3", "-m", "dockyard", "search", "baseline", "--branch", base_branch],
        ["python3", "-m", "dockyard", "search", "baseline", "--tag", "baseline", "--branch", base_branch],
        ["python3", "-m", "dockyard", "search", "baseline", "--tag", "baseline", "--branch", base_branch, "--json"],
        ["python3", "-m", "dockyard", "search", "baseline", "--tag", "baseline", "--repo", git_repo.name, "--json"],
        [
            "python3",
            "-m",
            "dockyard",
            "search",
            "baseline",
            "--tag",
            "baseline",
            "--repo",
            git_repo.name,
            "--branch",
            base_branch,
            "--json",
        ],
        ["python3", "-m", "dockyard", "search", "baseline", "--repo", git_repo.name, "--branch", base_branch, "--json"],
        ["python3", "-m", "dockyard", "f", "baseline"],
        ["python3", "-m", "dockyard", "f", "baseline", "--json"],
        ["python3", "-m", "dockyard", "f", "baseline", "--repo", git_repo.name, "--json"],
        ["python3", "-m", "dockyard", "f", "baseline", "--branch", base_branch, "--json"],
        ["python3", "-m", "dockyard", "f", "baseline", "--repo", git_repo.name, "--branch", base_branch, "--json"],
        ["python3", "-m", "dockyard", "f", "baseline", "--tag", "missing-tag"],
        ["python3", "-m", "dockyard", "f", "baseline", "--tag", "baseline"],
        ["python3", "-m", "dockyard", "f", "baseline", "--tag", "baseline", "--repo", git_repo.name],
        ["python3", "-m", "dockyard", "f", "baseline", "--tag", "baseline", "--repo", git_repo.name, "--json"],
        [
            "python3",
            "-m",
            "dockyard",
            "f",
            "baseline",
            "--tag",
            "baseline",
            "--repo",
            git_repo.name,
            "--branch",
            base_branch,
            "--json",
        ],
        [
            "python3",
            "-m",
            "dockyard",
            "f",
            "baseline",
            "--tag",
            "baseline",
            "--repo",
            git_repo.name,
            "--branch",
            base_branch,
        ],
        ["python3", "-m", "dockyard", "f", "baseline", "--tag", "baseline", "--branch", base_branch, "--json"],
        ["python3", "-m", "dockyard", "review"],
        ["python3", "-m", "dockyard", "review", "list"],
        ["python3", "-m", "dockyard", "review", "--all"],
        ["python3", "-m", "dockyard", "review", "list", "--all"],
    ]
    _run_commands(outside_repo_commands, cwd=tmp_path, env=env)

    _assert_repo_clean(git_repo)


def test_resume_read_paths_do_not_execute_saved_commands(git_repo: Path, tmp_path: Path) -> None:
    """Resume read-only paths must not execute stored resume commands."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    marker = git_repo / "dockyard_resume_should_not_run.txt"
    marker_command = f"touch {marker}"

    _save_checkpoint(
        git_repo,
        env,
        objective="Resume command safety baseline",
        decisions="Ensure resume read paths do not execute stored commands",
        next_step="Inspect resume output",
        risks="none",
        command=marker_command,
    )

    assert not marker.exists()
    _assert_repo_clean(git_repo)

    _run(["python3", "-m", "dockyard", "resume"], cwd=git_repo, env=env)
    _run(["python3", "-m", "dockyard", "resume", "--json"], cwd=git_repo, env=env)
    _run(["python3", "-m", "dockyard", "resume", "--handoff"], cwd=git_repo, env=env)
    _run(["python3", "-m", "dockyard", "r"], cwd=git_repo, env=env)
    _run(["python3", "-m", "dockyard", "undock"], cwd=git_repo, env=env)

    assert not marker.exists()
    _assert_repo_clean(git_repo)


def test_resume_alias_berth_read_paths_do_not_execute_saved_commands(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Berth-targeted alias read paths must not execute stored commands."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    marker = git_repo / "dockyard_alias_berth_resume_should_not_run.txt"
    marker_command = f"touch {marker}"
    base_branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=git_repo)

    _save_checkpoint(
        git_repo,
        env,
        objective="Alias berth command safety baseline",
        decisions="Ensure alias berth read paths do not execute stored commands",
        next_step="Inspect alias berth resume output",
        risks="none",
        command=marker_command,
    )

    assert not marker.exists()
    _assert_repo_clean(git_repo)
    _run_commands(
        [
            ["python3", "-m", "dockyard", "r", git_repo.name],
            ["python3", "-m", "dockyard", "r", git_repo.name, "--json"],
            ["python3", "-m", "dockyard", "r", git_repo.name, "--handoff"],
            ["python3", "-m", "dockyard", "r", git_repo.name, "--branch", base_branch],
            ["python3", "-m", "dockyard", "r", git_repo.name, "--branch", base_branch, "--json"],
            ["python3", "-m", "dockyard", "r", git_repo.name, "--branch", base_branch, "--handoff"],
            ["python3", "-m", "dockyard", "undock", git_repo.name],
            ["python3", "-m", "dockyard", "undock", git_repo.name, "--json"],
            ["python3", "-m", "dockyard", "undock", git_repo.name, "--handoff"],
            ["python3", "-m", "dockyard", "undock", git_repo.name, "--branch", base_branch],
            ["python3", "-m", "dockyard", "undock", git_repo.name, "--branch", base_branch, "--json"],
            ["python3", "-m", "dockyard", "undock", git_repo.name, "--branch", base_branch, "--handoff"],
        ],
        cwd=tmp_path,
        env=env,
    )

    assert not marker.exists()
    _assert_repo_clean(git_repo)


def test_resume_alias_trimmed_berth_read_paths_do_not_execute_saved_commands(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Trimmed berth/branch alias read paths must not execute stored commands."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    marker = git_repo / "dockyard_alias_trimmed_resume_should_not_run.txt"
    marker_command = f"touch {marker}"
    base_branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=git_repo)

    _save_checkpoint(
        git_repo,
        env,
        objective="Alias trimmed berth command safety baseline",
        decisions="Ensure trimmed alias berth read paths do not execute stored commands",
        next_step="Inspect trimmed alias berth resume output",
        risks="none",
        command=marker_command,
    )

    assert not marker.exists()
    _assert_repo_clean(git_repo)
    trimmed_berth = f"  {git_repo.name}  "
    trimmed_branch = f"  {base_branch}  "

    _run_commands(
        [
            ["python3", "-m", "dockyard", "r", trimmed_berth],
            ["python3", "-m", "dockyard", "r", trimmed_berth, "--json"],
            ["python3", "-m", "dockyard", "r", trimmed_berth, "--handoff"],
            ["python3", "-m", "dockyard", "r", trimmed_berth, "--branch", trimmed_branch],
            ["python3", "-m", "dockyard", "r", trimmed_berth, "--branch", trimmed_branch, "--json"],
            ["python3", "-m", "dockyard", "r", trimmed_berth, "--branch", trimmed_branch, "--handoff"],
            ["python3", "-m", "dockyard", "undock", trimmed_berth],
            ["python3", "-m", "dockyard", "undock", trimmed_berth, "--json"],
            ["python3", "-m", "dockyard", "undock", trimmed_berth, "--handoff"],
            ["python3", "-m", "dockyard", "undock", trimmed_berth, "--branch", trimmed_branch],
            ["python3", "-m", "dockyard", "undock", trimmed_berth, "--branch", trimmed_branch, "--json"],
            ["python3", "-m", "dockyard", "undock", trimmed_berth, "--branch", trimmed_branch, "--handoff"],
        ],
        cwd=tmp_path,
        env=env,
    )

    assert not marker.exists()
    _assert_repo_clean(git_repo)


def test_resume_explicit_trimmed_berth_read_paths_do_not_execute_saved_commands(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Trimmed berth/branch primary resume paths must never execute commands."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    marker = git_repo / "dockyard_primary_trimmed_resume_should_not_run.txt"
    marker_command = f"touch {marker}"
    base_branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=git_repo)

    _save_checkpoint(
        git_repo,
        env,
        objective="Primary trimmed berth command safety baseline",
        decisions="Ensure trimmed primary berth read paths do not execute commands",
        next_step="Inspect trimmed primary berth resume output",
        risks="none",
        command=marker_command,
    )

    assert not marker.exists()
    _assert_repo_clean(git_repo)
    trimmed_berth = f"  {git_repo.name}  "
    trimmed_branch = f"  {base_branch}  "

    _run_commands(
        [
            ["python3", "-m", "dockyard", "resume", trimmed_berth],
            ["python3", "-m", "dockyard", "resume", trimmed_berth, "--json"],
            ["python3", "-m", "dockyard", "resume", trimmed_berth, "--handoff"],
            ["python3", "-m", "dockyard", "resume", trimmed_berth, "--branch", trimmed_branch],
            ["python3", "-m", "dockyard", "resume", trimmed_berth, "--branch", trimmed_branch, "--json"],
            ["python3", "-m", "dockyard", "resume", trimmed_berth, "--branch", trimmed_branch, "--handoff"],
        ],
        cwd=tmp_path,
        env=env,
    )

    assert not marker.exists()
    _assert_repo_clean(git_repo)


def test_review_and_link_commands_do_not_modify_repo(git_repo: Path, tmp_path: Path) -> None:
    """Dockyard metadata mutations must not alter repository working tree."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _save_checkpoint(
        git_repo,
        env,
        objective="Mutation command baseline",
        decisions="Validate review/link non-interference",
        next_step="Run link and review commands",
        risks="none",
    )

    _assert_repo_clean(git_repo)

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
        ["python3", "-m", "dockyard", "review", "open", review_match.group(0)],
        cwd=git_repo,
        env=env,
    )
    _run(
        ["python3", "-m", "dockyard", "review", "done", review_match.group(0)],
        cwd=git_repo,
        env=env,
    )

    _assert_repo_clean(git_repo)


def test_review_and_link_root_override_commands_do_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Root/override metadata mutations must not alter repository tree/index."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    base_branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=git_repo)

    _save_checkpoint(
        git_repo,
        env,
        objective="Root override mutation baseline",
        decisions="Validate root override review/link non-interference",
        next_step="Run root override metadata commands",
        risks="none",
    )

    _assert_repo_clean(git_repo)

    _run(
        [
            "python3",
            "-m",
            "dockyard",
            "link",
            "https://example.com/non-interference-root-override",
            "--root",
            str(git_repo),
        ],
        cwd=tmp_path,
        env=env,
    )
    _run(
        ["python3", "-m", "dockyard", "links", "--root", str(git_repo)],
        cwd=tmp_path,
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
            "manual-root-override",
            "--severity",
            "low",
            "--repo",
            git_repo.name,
            "--branch",
            base_branch,
            "--notes",
            "outside repo invocation",
        ],
        cwd=tmp_path,
        env=env,
    )
    review_match = re.search(r"rev_[a-f0-9]+", review_output)
    assert review_match is not None
    review_id = review_match.group(0)
    _run(["python3", "-m", "dockyard", "review", "open", review_id], cwd=tmp_path, env=env)
    _run(["python3", "-m", "dockyard", "review", "done", review_id], cwd=tmp_path, env=env)

    _assert_repo_clean(git_repo)


def test_save_with_editor_does_not_modify_repo(git_repo: Path, tmp_path: Path) -> None:
    """Editor-assisted save flow should not alter project working tree/index."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _configure_editor(
        env=env,
        tmp_path=tmp_path,
        script_name="editor.sh",
        decisions_text="Editor decisions for non-interference",
    )

    _assert_repo_clean(git_repo)

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

    _assert_repo_clean(git_repo)


def test_save_with_template_does_not_modify_repo(git_repo: Path, tmp_path: Path) -> None:
    """Template-driven save flow should not alter project working tree/index."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    template_path = tmp_path / "save_template.json"
    _write_non_interference_template(
        template_path=template_path,
        objective="Template non-interference objective",
    )

    _assert_repo_clean(git_repo)

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

    _assert_repo_clean(git_repo)


def test_save_alias_s_with_template_does_not_modify_repo(git_repo: Path, tmp_path: Path) -> None:
    """Alias `s` template save flow should not alter project tree/index."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    template_path = tmp_path / "save_alias_s_template.json"
    _write_non_interference_template(
        template_path=template_path,
        objective="Template alias s non-interference objective",
    )

    _assert_repo_clean(git_repo)

    _run(
        [
            "python3",
            "-m",
            "dockyard",
            "s",
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

    _assert_repo_clean(git_repo)


def test_save_alias_s_with_editor_does_not_modify_repo(git_repo: Path, tmp_path: Path) -> None:
    """Alias `s` editor save flow should not alter project tree/index."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _configure_editor(
        env=env,
        tmp_path=tmp_path,
        script_name="alias_s_editor.sh",
        decisions_text="Alias s editor decisions for non-interference",
    )

    _assert_repo_clean(git_repo)

    _run(
        [
            "python3",
            "-m",
            "dockyard",
            "s",
            "--root",
            str(git_repo),
            "--editor",
            "--no-prompt",
            "--objective",
            "Alias s editor non-interference objective",
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

    _assert_repo_clean(git_repo)


def test_save_alias_s_no_prompt_does_not_modify_repo(git_repo: Path, tmp_path: Path) -> None:
    """Alias `s` no-prompt save should not alter project tree/index."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _assert_repo_clean(git_repo)

    _run(
        [
            "python3",
            "-m",
            "dockyard",
            "s",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Alias s no-prompt non-interference objective",
            "--decisions",
            "Alias s no-prompt non-interference decisions",
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

    _assert_repo_clean(git_repo)


def test_save_alias_dock_with_template_does_not_modify_repo(git_repo: Path, tmp_path: Path) -> None:
    """Alias `dock` template save flow should not alter project tree/index."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    template_path = tmp_path / "save_alias_dock_template.json"
    _write_non_interference_template(
        template_path=template_path,
        objective="Template alias dock non-interference objective",
    )

    _assert_repo_clean(git_repo)

    _run(
        [
            "python3",
            "-m",
            "dockyard",
            "dock",
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

    _assert_repo_clean(git_repo)


def test_save_alias_dock_with_editor_does_not_modify_repo(git_repo: Path, tmp_path: Path) -> None:
    """Alias `dock` editor save flow should not alter project tree/index."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _configure_editor(
        env=env,
        tmp_path=tmp_path,
        script_name="alias_dock_editor.sh",
        decisions_text="Alias dock editor decisions for non-interference",
    )

    _assert_repo_clean(git_repo)

    _run(
        [
            "python3",
            "-m",
            "dockyard",
            "dock",
            "--root",
            str(git_repo),
            "--editor",
            "--no-prompt",
            "--objective",
            "Alias dock editor non-interference objective",
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

    _assert_repo_clean(git_repo)


def test_bare_dock_command_does_not_modify_repo(git_repo: Path, tmp_path: Path) -> None:
    """Bare dock command (harbor view) should not alter repo state."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _assert_repo_clean(git_repo)

    _run(["python3", "-m", "dockyard"], cwd=git_repo, env=env)

    _assert_repo_clean(git_repo)


def test_dock_alias_save_does_not_modify_repo(git_repo: Path, tmp_path: Path) -> None:
    """`dock dock` alias save flow should not alter project working tree/index."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _assert_repo_clean(git_repo)

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

    _assert_repo_clean(git_repo)


def test_resume_run_opt_in_can_modify_repo(git_repo: Path, tmp_path: Path) -> None:
    """Resume --run is explicit opt-in and may mutate repository files."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    marker = git_repo / "resume_run_opt_in_marker.txt"

    _save_checkpoint(
        git_repo,
        env,
        objective="Resume run opt-in mutation baseline",
        decisions="Verify explicit --run path may execute mutating commands",
        next_step="run resume --run",
        risks="none",
        command=f"touch {marker}",
    )
    assert not marker.exists()
    _assert_repo_clean(git_repo)

    _run(["python3", "-m", "dockyard", "resume", "--run"], cwd=git_repo, env=env)

    assert marker.exists()
    status_after = _run(["git", "status", "--porcelain"], cwd=git_repo)
    assert "resume_run_opt_in_marker.txt" in status_after


def test_resume_alias_run_opt_in_can_modify_repo(git_repo: Path, tmp_path: Path) -> None:
    """Alias `r --run` is explicit opt-in and may mutate repository files."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    marker = git_repo / "resume_alias_run_opt_in_marker.txt"

    _save_checkpoint(
        git_repo,
        env,
        objective="Resume alias run opt-in mutation baseline",
        decisions="Verify r --run may execute mutating commands",
        next_step="run r --run",
        risks="none",
        command=f"touch {marker}",
    )
    assert not marker.exists()
    _assert_repo_clean(git_repo)

    _run(["python3", "-m", "dockyard", "r", "--run"], cwd=git_repo, env=env)

    assert marker.exists()
    status_after = _run(["git", "status", "--porcelain"], cwd=git_repo)
    assert "resume_alias_run_opt_in_marker.txt" in status_after


def test_undock_alias_run_opt_in_with_berth_can_modify_repo(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Alias `undock <berth> --run` is opt-in and may mutate repo files."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    marker = git_repo / "undock_alias_run_opt_in_marker.txt"

    _save_checkpoint(
        git_repo,
        env,
        objective="Undock alias run opt-in mutation baseline",
        decisions="Verify undock --run with berth may execute mutating commands",
        next_step="run undock <berth> --run",
        risks="none",
        command=f"touch {marker}",
    )
    assert not marker.exists()
    _assert_repo_clean(git_repo)

    _run(
        ["python3", "-m", "dockyard", "undock", f"  {git_repo.name}  ", "--run"],
        cwd=tmp_path,
        env=env,
    )

    assert marker.exists()
    status_after = _run(["git", "status", "--porcelain"], cwd=git_repo)
    assert "undock_alias_run_opt_in_marker.txt" in status_after


def test_resume_run_opt_in_with_trimmed_berth_can_modify_repo(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Primary `resume <berth> --run` may mutate repo when explicitly opted-in."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    marker = git_repo / "resume_run_with_berth_opt_in_marker.txt"

    _save_checkpoint(
        git_repo,
        env,
        objective="Resume berth run opt-in mutation baseline",
        decisions="Verify resume <berth> --run may execute mutating commands",
        next_step="run resume <berth> --run",
        risks="none",
        command=f"touch {marker}",
    )
    assert not marker.exists()
    _assert_repo_clean(git_repo)

    _run(
        ["python3", "-m", "dockyard", "resume", f"  {git_repo.name}  ", "--run"],
        cwd=tmp_path,
        env=env,
    )

    assert marker.exists()
    status_after = _run(["git", "status", "--porcelain"], cwd=git_repo)
    assert "resume_run_with_berth_opt_in_marker.txt" in status_after


def test_resume_alias_run_opt_in_with_trimmed_berth_can_modify_repo(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Alias `r <berth> --run` may mutate repo when explicitly opted-in."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    marker = git_repo / "resume_alias_run_with_berth_opt_in_marker.txt"

    _save_checkpoint(
        git_repo,
        env,
        objective="Resume alias berth run opt-in mutation baseline",
        decisions="Verify r <berth> --run may execute mutating commands",
        next_step="run r <berth> --run",
        risks="none",
        command=f"touch {marker}",
    )
    assert not marker.exists()
    _assert_repo_clean(git_repo)

    _run(
        ["python3", "-m", "dockyard", "r", f"  {git_repo.name}  ", "--run"],
        cwd=tmp_path,
        env=env,
    )

    assert marker.exists()
    status_after = _run(["git", "status", "--porcelain"], cwd=git_repo)
    assert "resume_alias_run_with_berth_opt_in_marker.txt" in status_after
