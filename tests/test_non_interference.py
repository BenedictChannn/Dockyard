"""Tests ensuring Dockyard does not mutate project repos by default."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest


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


def _current_branch(git_repo: Path) -> str:
    """Return current branch name for repository path.

    Args:
        git_repo: Repository path to inspect.

    Returns:
        Active branch name.
    """
    return _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=git_repo)


def _dockyard_env(tmp_path: Path) -> dict[str, str]:
    """Create environment mapping with isolated Dockyard home.

    Args:
        tmp_path: Temporary test path used for Dockyard data.

    Returns:
        Environment variables with DOCKYARD_HOME configured.
    """
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    return env


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
    command: str | None = "echo noop",
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
        command: Optional resume command text captured in checkpoint.
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
    if command is not None:
        save_command.extend(["--command", command])
    if extra_args:
        save_command.extend(extra_args)
    _run(save_command, cwd=git_repo, env=env)


def _assert_opt_in_run_mutates_repo(
    git_repo: Path,
    tmp_path: Path,
    *,
    run_command: list[str],
    run_cwd: Path,
    marker_name: str,
    objective: str,
    decisions: str,
    next_step: str,
) -> None:
    """Assert explicit run mode executes mutating command in repository.

    Args:
        git_repo: Repository path where mutation should occur.
        tmp_path: Temporary path used for Dockyard home.
        run_command: Dockyard CLI command to execute (must include ``--run``).
        run_cwd: Working directory from which to execute ``run_command``.
        marker_name: Marker filename expected after command executes.
        objective: Checkpoint objective text for setup save.
        decisions: Checkpoint decisions text for setup save.
        next_step: Checkpoint next-step text for setup save.
    """
    env = _dockyard_env(tmp_path)
    marker = git_repo / marker_name

    _save_checkpoint(
        git_repo,
        env,
        objective=objective,
        decisions=decisions,
        next_step=next_step,
        risks="none",
        command=f"touch {marker}",
    )
    assert not marker.exists()
    _assert_repo_clean(git_repo)

    _run(run_command, cwd=run_cwd, env=env)

    assert marker.exists()
    status_after = _run(["git", "status", "--porcelain"], cwd=git_repo)
    assert marker_name in status_after


def _assert_opt_in_run_with_trimmed_berth_and_branch_mutates_repo(
    git_repo: Path,
    tmp_path: Path,
    *,
    command_name: str,
    marker_name: str,
    objective: str,
    decisions: str,
    next_step: str,
) -> None:
    """Assert `<command> <trimmed_berth> --branch <trimmed_branch> --run` mutates.

    Args:
        git_repo: Repository path where mutation should occur.
        tmp_path: Temporary path used for Dockyard home.
        command_name: Dockyard command token (resume/r/undock).
        marker_name: Marker filename expected in git status after run.
        objective: Checkpoint objective text for setup save.
        decisions: Checkpoint decisions text for setup save.
        next_step: Checkpoint next-step text for setup save.
    """
    base_branch = _current_branch(git_repo)
    _assert_opt_in_run_mutates_repo(
        git_repo,
        tmp_path,
        run_command=[
            "python3",
            "-m",
            "dockyard",
            command_name,
            f"  {git_repo.name}  ",
            "--branch",
            f"  {base_branch}  ",
            "--run",
        ],
        run_cwd=tmp_path,
        marker_name=marker_name,
        objective=objective,
        decisions=decisions,
        next_step=next_step,
    )


def _assert_opt_in_run_with_branch_mutates_repo(
    git_repo: Path,
    tmp_path: Path,
    *,
    command_name: str,
    marker_name: str,
    objective: str,
    decisions: str,
    next_step: str,
) -> None:
    """Assert `<command> --branch <trimmed_branch> --run` mutates repository.

    Args:
        git_repo: Repository path where mutation should occur.
        tmp_path: Temporary path used for Dockyard home.
        command_name: Dockyard command token (resume/r/undock).
        marker_name: Marker filename expected in git status after run.
        objective: Checkpoint objective text for setup save.
        decisions: Checkpoint decisions text for setup save.
        next_step: Checkpoint next-step text for setup save.
    """
    base_branch = _current_branch(git_repo)
    _assert_opt_in_run_mutates_repo(
        git_repo,
        tmp_path,
        run_command=[
            "python3",
            "-m",
            "dockyard",
            command_name,
            "--branch",
            f"  {base_branch}  ",
            "--run",
        ],
        run_cwd=git_repo,
        marker_name=marker_name,
        objective=objective,
        decisions=decisions,
        next_step=next_step,
    )


def _assert_opt_in_run_with_trimmed_berth_mutates_repo(
    git_repo: Path,
    tmp_path: Path,
    *,
    command_name: str,
    marker_name: str,
    objective: str,
    decisions: str,
    next_step: str,
) -> None:
    """Assert `<command> <trimmed_berth> --run` mutates repository.

    Args:
        git_repo: Repository path where mutation should occur.
        tmp_path: Temporary path used for Dockyard home.
        command_name: Dockyard command token (resume/r/undock).
        marker_name: Marker filename expected in git status after run.
        objective: Checkpoint objective text for setup save.
        decisions: Checkpoint decisions text for setup save.
        next_step: Checkpoint next-step text for setup save.
    """
    _assert_opt_in_run_mutates_repo(
        git_repo,
        tmp_path,
        run_command=["python3", "-m", "dockyard", command_name, f"  {git_repo.name}  ", "--run"],
        run_cwd=tmp_path,
        marker_name=marker_name,
        objective=objective,
        decisions=decisions,
        next_step=next_step,
    )


def _assert_opt_in_run_default_scope_without_commands_keeps_repo_clean(
    git_repo: Path,
    tmp_path: Path,
    *,
    command_name: str,
    objective: str,
    decisions: str,
    next_step: str,
) -> None:
    """Assert `<command> --run` is non-mutating when no commands are recorded.

    Args:
        git_repo: Repository path to inspect for mutations.
        tmp_path: Temporary path used for Dockyard home.
        command_name: Dockyard command token (resume/r/undock).
        objective: Checkpoint objective text for setup save.
        decisions: Checkpoint decisions text for setup save.
        next_step: Checkpoint next-step text for setup save.
    """
    _assert_opt_in_run_without_commands_keeps_repo_clean(
        git_repo,
        tmp_path,
        run_command=["python3", "-m", "dockyard", command_name, "--run"],
        run_cwd=git_repo,
        objective=objective,
        decisions=decisions,
        next_step=next_step,
    )


def _assert_opt_in_run_default_scope_mutates_repo(
    git_repo: Path,
    tmp_path: Path,
    *,
    command_name: str,
    marker_name: str,
    objective: str,
    decisions: str,
    next_step: str,
) -> None:
    """Assert `<command> --run` mutates repository in current repo scope.

    Args:
        git_repo: Repository path where mutation should occur.
        tmp_path: Temporary path used for Dockyard home.
        command_name: Dockyard command token (resume/r/undock).
        marker_name: Marker filename expected in git status after run.
        objective: Checkpoint objective text for setup save.
        decisions: Checkpoint decisions text for setup save.
        next_step: Checkpoint next-step text for setup save.
    """
    _assert_opt_in_run_mutates_repo(
        git_repo,
        tmp_path,
        run_command=["python3", "-m", "dockyard", command_name, "--run"],
        run_cwd=git_repo,
        marker_name=marker_name,
        objective=objective,
        decisions=decisions,
        next_step=next_step,
    )


def _assert_opt_in_run_without_commands_keeps_repo_clean(
    git_repo: Path,
    tmp_path: Path,
    *,
    run_command: list[str],
    run_cwd: Path,
    objective: str,
    decisions: str,
    next_step: str,
) -> None:
    """Assert explicit run mode with no commands leaves repo unchanged.

    Args:
        git_repo: Repository path to inspect for mutations.
        tmp_path: Temporary path used for Dockyard home.
        run_command: Dockyard CLI command to execute (must include ``--run``).
        run_cwd: Working directory from which to execute ``run_command``.
        objective: Checkpoint objective text for setup save.
        decisions: Checkpoint decisions text for setup save.
        next_step: Checkpoint next-step text for setup save.
    """
    env = _dockyard_env(tmp_path)
    _save_checkpoint(
        git_repo,
        env,
        objective=objective,
        decisions=decisions,
        next_step=next_step,
        risks="none",
        command=None,
    )
    _assert_repo_clean(git_repo)
    _run(run_command, cwd=run_cwd, env=env)
    _assert_repo_clean(git_repo)


def _assert_opt_in_run_with_branch_without_commands_keeps_repo_clean(
    git_repo: Path,
    tmp_path: Path,
    *,
    command_name: str,
    objective: str,
    decisions: str,
    next_step: str,
) -> None:
    """Assert `<command> --branch <trimmed_branch> --run` is non-mutating without commands.

    Args:
        git_repo: Repository path to inspect for mutations.
        tmp_path: Temporary path used for Dockyard home.
        command_name: Dockyard command token (resume/r/undock).
        objective: Checkpoint objective text for setup save.
        decisions: Checkpoint decisions text for setup save.
        next_step: Checkpoint next-step text for setup save.
    """
    base_branch = _current_branch(git_repo)
    _assert_opt_in_run_without_commands_keeps_repo_clean(
        git_repo,
        tmp_path,
        run_command=[
            "python3",
            "-m",
            "dockyard",
            command_name,
            "--branch",
            f"  {base_branch}  ",
            "--run",
        ],
        run_cwd=git_repo,
        objective=objective,
        decisions=decisions,
        next_step=next_step,
    )


def _assert_opt_in_run_with_trimmed_berth_without_commands_keeps_repo_clean(
    git_repo: Path,
    tmp_path: Path,
    *,
    command_name: str,
    objective: str,
    decisions: str,
    next_step: str,
) -> None:
    """Assert `<command> <trimmed_berth> --run` is non-mutating without commands.

    Args:
        git_repo: Repository path to inspect for mutations.
        tmp_path: Temporary path used for Dockyard home.
        command_name: Dockyard command token (resume/r/undock).
        objective: Checkpoint objective text for setup save.
        decisions: Checkpoint decisions text for setup save.
        next_step: Checkpoint next-step text for setup save.
    """
    _assert_opt_in_run_without_commands_keeps_repo_clean(
        git_repo,
        tmp_path,
        run_command=["python3", "-m", "dockyard", command_name, f"  {git_repo.name}  ", "--run"],
        run_cwd=tmp_path,
        objective=objective,
        decisions=decisions,
        next_step=next_step,
    )


def _assert_opt_in_run_with_trimmed_berth_and_branch_without_commands_keeps_repo_clean(
    git_repo: Path,
    tmp_path: Path,
    *,
    command_name: str,
    objective: str,
    decisions: str,
    next_step: str,
) -> None:
    """Assert `<command> <trimmed_berth> --branch <trimmed_branch> --run` is non-mutating.

    Args:
        git_repo: Repository path to inspect for mutations.
        tmp_path: Temporary path used for Dockyard home.
        command_name: Dockyard command token (resume/r/undock).
        objective: Checkpoint objective text for setup save.
        decisions: Checkpoint decisions text for setup save.
        next_step: Checkpoint next-step text for setup save.
    """
    base_branch = _current_branch(git_repo)
    _assert_opt_in_run_without_commands_keeps_repo_clean(
        git_repo,
        tmp_path,
        run_command=[
            "python3",
            "-m",
            "dockyard",
            command_name,
            f"  {git_repo.name}  ",
            "--branch",
            f"  {base_branch}  ",
            "--run",
        ],
        run_cwd=tmp_path,
        objective=objective,
        decisions=decisions,
        next_step=next_step,
    )


def _resume_read_variants(
    command_name: str,
    *,
    berth: str | None = None,
    branch: str | None = None,
    include_json: bool = True,
    include_handoff: bool = True,
) -> list[list[str]]:
    """Build read-only resume command variants for a command token.

    Args:
        command_name: Dockyard command token (resume/r/undock).
        berth: Optional berth argument to target.
        branch: Optional branch argument to target.
        include_json: Whether to include ``--json`` variant for base command.
        include_handoff: Whether to include ``--handoff`` variant for base command.

    Returns:
        Command argument matrix prefixed with ``python3 -m dockyard``.
    """
    base_command = ["python3", "-m", "dockyard", command_name]
    if berth is not None:
        base_command.append(berth)

    commands = [base_command.copy()]
    if include_json:
        commands.append([*base_command, "--json"])
    if include_handoff:
        commands.append([*base_command, "--handoff"])
    if branch is not None:
        branch_command = [*base_command, "--branch", branch]
        commands.append(branch_command)
        if include_json:
            commands.append([*branch_command, "--json"])
        if include_handoff:
            commands.append([*branch_command, "--handoff"])
    return commands


def _assert_resume_read_paths_do_not_execute_saved_commands(
    git_repo: Path,
    tmp_path: Path,
    *,
    marker_name: str,
    objective: str,
    decisions: str,
    next_step: str,
    commands: list[list[str]],
    run_cwd: Path,
) -> None:
    """Assert resume read paths never execute stored resume commands.

    Args:
        git_repo: Repository under test.
        tmp_path: Temporary path used for Dockyard home.
        marker_name: Marker filename expected to remain absent.
        objective: Checkpoint objective text.
        decisions: Checkpoint decisions text.
        next_step: Checkpoint next-step text.
        commands: Resume-path commands to execute.
        run_cwd: Working directory for command execution.
    """
    env = _dockyard_env(tmp_path)
    marker = git_repo / marker_name
    marker_command = f"touch {marker}"

    _save_checkpoint(
        git_repo,
        env,
        objective=objective,
        decisions=decisions,
        next_step=next_step,
        risks="none",
        command=marker_command,
    )

    assert not marker.exists()
    _assert_repo_clean(git_repo)
    _run_commands(commands, cwd=run_cwd, env=env)
    assert not marker.exists()
    _assert_repo_clean(git_repo)


def _assert_review_link_commands_do_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    *,
    objective: str,
    decisions: str,
    next_step: str,
    run_cwd: Path,
    metadata_commands: list[list[str]],
    review_add_command: list[str],
) -> None:
    """Assert review/link metadata commands keep project repo unchanged.

    Args:
        git_repo: Repository under test.
        tmp_path: Temporary path used for Dockyard home.
        objective: Checkpoint objective text.
        decisions: Checkpoint decisions text.
        next_step: Checkpoint next-step text.
        run_cwd: Working directory for metadata command execution.
        metadata_commands: Metadata commands to run before review creation.
        review_add_command: Review-add command used to create a review item.
    """
    env = _dockyard_env(tmp_path)
    _save_checkpoint(
        git_repo,
        env,
        objective=objective,
        decisions=decisions,
        next_step=next_step,
        risks="none",
    )

    _assert_repo_clean(git_repo)
    _run_commands(metadata_commands, cwd=run_cwd, env=env)
    review_output = _run(review_add_command, cwd=run_cwd, env=env)
    review_match = re.search(r"rev_[a-f0-9]+", review_output)
    assert review_match is not None
    review_id = review_match.group(0)
    _run(["python3", "-m", "dockyard", "review", "open", review_id], cwd=run_cwd, env=env)
    _run(["python3", "-m", "dockyard", "review", "done", review_id], cwd=run_cwd, env=env)
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize(
    (
        "command_name",
        "objective",
        "decisions",
        "next_step",
        "risks",
        "resume_command",
        "build_command",
    ),
    [
        (
            "save",
            "Checkpoint objective",
            "Decision text",
            "Do another thing",
            "Review infra carefully",
            "pytest -q",
            "python -m build",
        ),
        (
            "s",
            "Alias s no-prompt non-interference objective",
            "Alias s no-prompt non-interference decisions",
            "run resume",
            "none",
            "echo noop",
            "echo build",
        ),
        (
            "dock",
            "Dock alias save objective",
            "Dock alias save decisions",
            "Run resume",
            "none",
            "echo noop",
            "echo build",
        ),
    ],
    ids=["save", "s_alias", "dock_alias"],
)
def test_save_no_prompt_flows_do_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
    objective: str,
    decisions: str,
    next_step: str,
    risks: str,
    resume_command: str,
    build_command: str,
) -> None:
    """No-prompt save flows should not alter tracked files or git index."""
    env = _dockyard_env(tmp_path)
    _assert_repo_clean(git_repo)
    _run(
        [
            "python3",
            "-m",
            "dockyard",
            command_name,
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
            resume_command,
            "--tests-run",
            "--tests-command",
            "pytest -q",
            "--build-ok",
            "--build-command",
            build_command,
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
    env = _dockyard_env(tmp_path)
    base_branch = _current_branch(git_repo)

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
    commands = [
        *_resume_read_variants("resume"),
        *_resume_read_variants("r", include_json=False, include_handoff=False),
        *_resume_read_variants("undock", include_json=False, include_handoff=False),
    ]
    _assert_resume_read_paths_do_not_execute_saved_commands(
        git_repo,
        tmp_path,
        marker_name="dockyard_resume_should_not_run.txt",
        objective="Resume command safety baseline",
        decisions="Ensure resume read paths do not execute stored commands",
        next_step="Inspect resume output",
        commands=commands,
        run_cwd=git_repo,
    )


def test_resume_alias_berth_read_paths_do_not_execute_saved_commands(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Berth-targeted alias read paths must not execute stored commands."""
    base_branch = _current_branch(git_repo)
    commands = [
        *_resume_read_variants("r", berth=git_repo.name, branch=base_branch),
        *_resume_read_variants("undock", berth=git_repo.name, branch=base_branch),
    ]
    _assert_resume_read_paths_do_not_execute_saved_commands(
        git_repo,
        tmp_path,
        marker_name="dockyard_alias_berth_resume_should_not_run.txt",
        objective="Alias berth command safety baseline",
        decisions="Ensure alias berth read paths do not execute stored commands",
        next_step="Inspect alias berth resume output",
        commands=commands,
        run_cwd=tmp_path,
    )


def test_resume_alias_trimmed_berth_read_paths_do_not_execute_saved_commands(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Trimmed berth/branch alias read paths must not execute stored commands."""
    base_branch = _current_branch(git_repo)
    trimmed_berth = f"  {git_repo.name}  "
    trimmed_branch = f"  {base_branch}  "
    commands = [
        *_resume_read_variants("r", berth=trimmed_berth, branch=trimmed_branch),
        *_resume_read_variants("undock", berth=trimmed_berth, branch=trimmed_branch),
    ]
    _assert_resume_read_paths_do_not_execute_saved_commands(
        git_repo,
        tmp_path,
        marker_name="dockyard_alias_trimmed_resume_should_not_run.txt",
        objective="Alias trimmed berth command safety baseline",
        decisions="Ensure trimmed alias berth read paths do not execute stored commands",
        next_step="Inspect trimmed alias berth resume output",
        commands=commands,
        run_cwd=tmp_path,
    )


def test_resume_explicit_trimmed_berth_read_paths_do_not_execute_saved_commands(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Trimmed berth/branch primary resume paths must never execute commands."""
    base_branch = _current_branch(git_repo)
    trimmed_berth = f"  {git_repo.name}  "
    trimmed_branch = f"  {base_branch}  "
    _assert_resume_read_paths_do_not_execute_saved_commands(
        git_repo,
        tmp_path,
        marker_name="dockyard_primary_trimmed_resume_should_not_run.txt",
        objective="Primary trimmed berth command safety baseline",
        decisions="Ensure trimmed primary berth read paths do not execute commands",
        next_step="Inspect trimmed primary berth resume output",
        commands=_resume_read_variants("resume", berth=trimmed_berth, branch=trimmed_branch),
        run_cwd=tmp_path,
    )


def test_review_and_link_commands_do_not_modify_repo(git_repo: Path, tmp_path: Path) -> None:
    """Dockyard metadata mutations must not alter repository working tree."""
    _assert_review_link_commands_do_not_modify_repo(
        git_repo,
        tmp_path,
        objective="Mutation command baseline",
        decisions="Validate review/link non-interference",
        next_step="Run link and review commands",
        run_cwd=git_repo,
        metadata_commands=[
            ["python3", "-m", "dockyard", "link", "https://example.com/non-interference"],
        ],
        review_add_command=[
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
    )


def test_review_and_link_root_override_commands_do_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Root/override metadata mutations must not alter repository tree/index."""
    base_branch = _current_branch(git_repo)
    _assert_review_link_commands_do_not_modify_repo(
        git_repo,
        tmp_path,
        objective="Root override mutation baseline",
        decisions="Validate root override review/link non-interference",
        next_step="Run root override metadata commands",
        run_cwd=tmp_path,
        metadata_commands=[
            [
                "python3",
                "-m",
                "dockyard",
                "link",
                "https://example.com/non-interference-root-override",
                "--root",
                str(git_repo),
            ],
            ["python3", "-m", "dockyard", "links", "--root", str(git_repo)],
        ],
        review_add_command=[
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
    )


@pytest.mark.parametrize(
    ("command_name", "script_name", "decisions_text", "objective"),
    [
        (
            "save",
            "editor.sh",
            "Editor decisions for non-interference",
            "Editor non-interference objective",
        ),
        (
            "s",
            "alias_s_editor.sh",
            "Alias s editor decisions for non-interference",
            "Alias s editor non-interference objective",
        ),
        (
            "dock",
            "alias_dock_editor.sh",
            "Alias dock editor decisions for non-interference",
            "Alias dock editor non-interference objective",
        ),
    ],
    ids=["save", "s_alias", "dock_alias"],
)
def test_save_editor_flows_do_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
    script_name: str,
    decisions_text: str,
    objective: str,
) -> None:
    """Save/editor flows should not alter project working tree/index."""
    env = _dockyard_env(tmp_path)
    _configure_editor(
        env=env,
        tmp_path=tmp_path,
        script_name=script_name,
        decisions_text=decisions_text,
    )

    _assert_repo_clean(git_repo)
    _run(
        [
            "python3",
            "-m",
            "dockyard",
            command_name,
            "--root",
            str(git_repo),
            "--editor",
            "--no-prompt",
            "--objective",
            objective,
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


@pytest.mark.parametrize(
    ("command_name", "template_name", "objective"),
    [
        ("save", "save_template.json", "Template non-interference objective"),
        ("s", "save_alias_s_template.json", "Template alias s non-interference objective"),
        ("dock", "save_alias_dock_template.json", "Template alias dock non-interference objective"),
    ],
    ids=["save", "s_alias", "dock_alias"],
)
def test_save_template_flows_do_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
    template_name: str,
    objective: str,
) -> None:
    """Save/template flows should not alter project working tree/index."""
    env = _dockyard_env(tmp_path)
    template_path = tmp_path / template_name
    _write_non_interference_template(template_path=template_path, objective=objective)

    _assert_repo_clean(git_repo)
    _run(
        [
            "python3",
            "-m",
            "dockyard",
            command_name,
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


def test_bare_dock_command_does_not_modify_repo(git_repo: Path, tmp_path: Path) -> None:
    """Bare dock command (harbor view) should not alter repo state."""
    env = _dockyard_env(tmp_path)

    _assert_repo_clean(git_repo)

    _run(["python3", "-m", "dockyard"], cwd=git_repo, env=env)

    _assert_repo_clean(git_repo)


@pytest.mark.parametrize(
    ("command_name", "objective", "decisions", "next_step"),
    [
        (
            "resume",
            "Resume run no-commands baseline",
            "Verify resume --run no-op path remains non-mutating",
            "run resume --run",
        ),
        (
            "r",
            "Resume alias run no-commands baseline",
            "Verify r --run no-op path remains non-mutating",
            "run r --run",
        ),
        (
            "undock",
            "Undock alias run no-commands baseline",
            "Verify undock --run no-op path remains non-mutating",
            "run undock --run",
        ),
    ],
    ids=["resume", "r_alias", "undock_alias"],
)
def test_run_default_scope_without_commands_keeps_repo_clean(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
    objective: str,
    decisions: str,
    next_step: str,
) -> None:
    """`<command> --run` with no commands should remain non-mutating."""
    _assert_opt_in_run_default_scope_without_commands_keeps_repo_clean(
        git_repo,
        tmp_path,
        command_name=command_name,
        objective=objective,
        decisions=decisions,
        next_step=next_step,
    )


@pytest.mark.parametrize(
    ("command_name", "objective", "decisions", "next_step"),
    [
        (
            "resume",
            "Resume berth run no-commands baseline",
            "Verify resume <berth> --run no-op path remains non-mutating",
            "run resume <berth> --run",
        ),
        (
            "r",
            "Resume alias berth run no-commands baseline",
            "Verify r <berth> --run no-op path remains non-mutating",
            "run r <berth> --run",
        ),
        (
            "undock",
            "Undock alias berth run no-commands baseline",
            "Verify undock <berth> --run no-op path remains non-mutating",
            "run undock <berth> --run",
        ),
    ],
    ids=["resume", "r_alias", "undock_alias"],
)
def test_run_trimmed_berth_without_commands_keeps_repo_clean(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
    objective: str,
    decisions: str,
    next_step: str,
) -> None:
    """`<command> <berth> --run` with no commands should remain non-mutating."""
    _assert_opt_in_run_with_trimmed_berth_without_commands_keeps_repo_clean(
        git_repo,
        tmp_path,
        command_name=command_name,
        objective=objective,
        decisions=decisions,
        next_step=next_step,
    )


@pytest.mark.parametrize(
    ("command_name", "objective", "decisions", "next_step"),
    [
        (
            "resume",
            "Resume branch run no-commands baseline",
            "Verify resume --branch <name> --run no-op path is non-mutating",
            "run resume --branch <name> --run",
        ),
        (
            "r",
            "Resume alias branch run no-commands baseline",
            "Verify r --branch <name> --run no-op path is non-mutating",
            "run r --branch <name> --run",
        ),
        (
            "undock",
            "Undock alias branch run no-commands baseline",
            "Verify undock --branch <name> --run no-op path is non-mutating",
            "run undock --branch <name> --run",
        ),
    ],
    ids=["resume", "r_alias", "undock_alias"],
)
def test_run_branch_scope_without_commands_keeps_repo_clean(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
    objective: str,
    decisions: str,
    next_step: str,
) -> None:
    """`<command> --branch <name> --run` without commands should not mutate."""
    _assert_opt_in_run_with_branch_without_commands_keeps_repo_clean(
        git_repo,
        tmp_path,
        command_name=command_name,
        objective=objective,
        decisions=decisions,
        next_step=next_step,
    )


@pytest.mark.parametrize(
    ("command_name", "objective", "decisions", "next_step"),
    [
        (
            "resume",
            "Resume berth+branch run no-commands baseline",
            "Verify resume <berth> --branch <name> --run no-op is non-mutating",
            "run resume <berth> --branch <name> --run",
        ),
        (
            "r",
            "Resume alias berth+branch run no-commands baseline",
            "Verify r <berth> --branch <name> --run no-op is non-mutating",
            "run r <berth> --branch <name> --run",
        ),
        (
            "undock",
            "Undock alias berth+branch run no-commands baseline",
            "Verify undock <berth> --branch <name> --run no-op is non-mutating",
            "run undock <berth> --branch <name> --run",
        ),
    ],
    ids=["resume", "r_alias", "undock_alias"],
)
def test_run_trimmed_berth_branch_without_commands_keeps_repo_clean(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
    objective: str,
    decisions: str,
    next_step: str,
) -> None:
    """`<command> <berth> --branch <name> --run` no-command path is read-only."""
    _assert_opt_in_run_with_trimmed_berth_and_branch_without_commands_keeps_repo_clean(
        git_repo,
        tmp_path,
        command_name=command_name,
        objective=objective,
        decisions=decisions,
        next_step=next_step,
    )


@pytest.mark.parametrize(
    ("command_name", "marker_name", "objective", "decisions", "next_step"),
    [
        (
            "resume",
            "resume_run_opt_in_marker.txt",
            "Resume run opt-in mutation baseline",
            "Verify explicit --run path may execute mutating commands",
            "run resume --run",
        ),
        (
            "r",
            "resume_alias_run_opt_in_marker.txt",
            "Resume alias run opt-in mutation baseline",
            "Verify r --run may execute mutating commands",
            "run r --run",
        ),
        (
            "undock",
            "undock_alias_run_opt_in_marker.txt",
            "Undock alias run opt-in mutation baseline",
            "Verify undock --run may execute mutating commands",
            "run undock --run",
        ),
    ],
    ids=["resume", "r_alias", "undock_alias"],
)
def test_run_default_scope_opt_in_can_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
    marker_name: str,
    objective: str,
    decisions: str,
    next_step: str,
) -> None:
    """`<command> --run` may mutate repository when explicitly opted-in."""
    _assert_opt_in_run_default_scope_mutates_repo(
        git_repo,
        tmp_path,
        command_name=command_name,
        marker_name=marker_name,
        objective=objective,
        decisions=decisions,
        next_step=next_step,
    )


@pytest.mark.parametrize(
    ("command_name", "marker_name", "objective", "decisions", "next_step"),
    [
        (
            "resume",
            "resume_run_with_branch_opt_in_marker.txt",
            "Resume branch run opt-in mutation baseline",
            "Verify resume --branch <name> --run may execute mutating commands",
            "run resume --branch <name> --run",
        ),
        (
            "r",
            "resume_alias_run_with_branch_opt_in_marker.txt",
            "Resume alias branch run opt-in mutation baseline",
            "Verify r --branch <name> --run may execute mutating commands",
            "run r --branch <name> --run",
        ),
        (
            "undock",
            "undock_alias_run_with_branch_opt_in_marker.txt",
            "Undock alias branch run opt-in mutation baseline",
            "Verify undock --branch <name> --run may execute mutating commands",
            "run undock --branch <name> --run",
        ),
    ],
    ids=["resume", "r_alias", "undock_alias"],
)
def test_run_branch_scope_opt_in_can_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
    marker_name: str,
    objective: str,
    decisions: str,
    next_step: str,
) -> None:
    """`<command> --branch <name> --run` may mutate when explicitly opted-in."""
    _assert_opt_in_run_with_branch_mutates_repo(
        git_repo,
        tmp_path,
        command_name=command_name,
        marker_name=marker_name,
        objective=objective,
        decisions=decisions,
        next_step=next_step,
    )


@pytest.mark.parametrize(
    ("command_name", "marker_name", "objective", "decisions", "next_step"),
    [
        (
            "resume",
            "resume_run_with_berth_opt_in_marker.txt",
            "Resume berth run opt-in mutation baseline",
            "Verify resume <berth> --run may execute mutating commands",
            "run resume <berth> --run",
        ),
        (
            "r",
            "resume_alias_run_with_berth_opt_in_marker.txt",
            "Resume alias berth run opt-in mutation baseline",
            "Verify r <berth> --run may execute mutating commands",
            "run r <berth> --run",
        ),
        (
            "undock",
            "undock_alias_run_opt_in_marker.txt",
            "Undock alias run opt-in mutation baseline",
            "Verify undock --run with berth may execute mutating commands",
            "run undock <berth> --run",
        ),
    ],
    ids=["resume", "r_alias", "undock_alias"],
)
def test_run_trimmed_berth_scope_opt_in_can_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
    marker_name: str,
    objective: str,
    decisions: str,
    next_step: str,
) -> None:
    """`<command> <berth> --run` may mutate when explicitly opted-in."""
    _assert_opt_in_run_with_trimmed_berth_mutates_repo(
        git_repo,
        tmp_path,
        command_name=command_name,
        marker_name=marker_name,
        objective=objective,
        decisions=decisions,
        next_step=next_step,
    )


@pytest.mark.parametrize(
    ("command_name", "marker_name", "objective", "decisions", "next_step"),
    [
        (
            "resume",
            "resume_run_with_berth_branch_opt_in_marker.txt",
            "Resume berth+branch run opt-in mutation baseline",
            "Verify resume <berth> --branch <branch> --run may mutate repo",
            "run resume <berth> --branch <branch> --run",
        ),
        (
            "r",
            "resume_alias_run_with_berth_branch_opt_in_marker.txt",
            "Resume alias berth+branch run opt-in mutation baseline",
            "Verify r <berth> --branch <branch> --run may mutate repo",
            "run r <berth> --branch <branch> --run",
        ),
        (
            "undock",
            "undock_alias_run_with_berth_branch_opt_in_marker.txt",
            "Undock alias berth+branch run opt-in mutation baseline",
            "Verify undock <berth> --branch <branch> --run may mutate repo",
            "run undock <berth> --branch <branch> --run",
        ),
    ],
    ids=["resume", "r_alias", "undock_alias"],
)
def test_run_trimmed_berth_branch_scope_opt_in_can_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
    marker_name: str,
    objective: str,
    decisions: str,
    next_step: str,
) -> None:
    """`<command> <berth> --branch <branch> --run` may mutate when opted-in."""
    _assert_opt_in_run_with_trimmed_berth_and_branch_mutates_repo(
        git_repo,
        tmp_path,
        command_name=command_name,
        marker_name=marker_name,
        objective=objective,
        decisions=decisions,
        next_step=next_step,
    )
