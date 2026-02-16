"""Tests ensuring Dockyard does not mutate project repos by default."""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Literal

import pytest

CommandMatrix = list[list[str]]
RunCommand = list[str]
MetadataCommandBuilder = Callable[[Path, str], CommandMatrix]
ReviewAddCommandBuilder = Callable[[Path, str], list[str]]
RunCwdKind = Literal["repo", "tmp"]
SAVE_COMMAND_IDS = ["save", "s_alias", "dock_alias"]
RUN_SCOPE_IDS_DEFAULT_BERTH_BRANCH = [
    "resume_default",
    "r_default",
    "undock_default",
    "resume_berth",
    "r_berth",
    "undock_berth",
    "resume_branch",
    "r_branch",
    "undock_branch",
    "resume_berth_branch",
    "r_berth_branch",
    "undock_berth_branch",
]
RUN_SCOPE_IDS_DEFAULT_BRANCH_BERTH = [
    "resume_default",
    "r_default",
    "undock_default",
    "resume_branch",
    "r_branch",
    "undock_branch",
    "resume_berth",
    "r_berth",
    "undock_berth",
    "resume_berth_branch",
    "r_berth_branch",
    "undock_berth_branch",
]


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


def _run_commands(commands: CommandMatrix, cwd: Path, env: dict[str, str]) -> None:
    """Run a sequence of commands in a shared working directory.

    Args:
        commands: Commands to execute in order.
        cwd: Working directory used for all commands.
        env: Environment variables for subprocess execution.
    """
    for command in commands:
        _run(command, cwd=cwd, env=env)


def _resolve_run_cwd(git_repo: Path, tmp_path: Path, run_cwd_kind: RunCwdKind) -> Path:
    """Resolve command working directory from run-scope selector."""
    return git_repo if run_cwd_kind == "repo" else tmp_path


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


def _build_opt_in_run_command(
    *,
    command_name: str,
    git_repo: Path,
    branch: str | None = None,
    include_berth: bool = False,
) -> RunCommand:
    """Build dockyard opt-in run command for non-interference checks."""
    run_command = ["python3", "-m", "dockyard", command_name]
    if include_berth:
        run_command.append(f"  {git_repo.name}  ")
    if branch is not None:
        run_command.extend(["--branch", f"  {branch}  "])
    run_command.append("--run")
    return run_command


def _seed_opt_in_checkpoint(
    git_repo: Path,
    tmp_path: Path,
    *,
    objective: str,
    decisions: str,
    next_step: str,
    command: str | None,
) -> dict[str, str]:
    """Create opt-in checkpoint seed and return configured environment."""
    env = _dockyard_env(tmp_path)
    _save_checkpoint(
        git_repo,
        env,
        objective=objective,
        decisions=decisions,
        next_step=next_step,
        risks="none",
        command=command,
    )
    return env


def _assert_opt_in_run_mutates_repo(
    git_repo: Path,
    tmp_path: Path,
    *,
    run_command: RunCommand,
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
    marker = git_repo / marker_name

    env = _seed_opt_in_checkpoint(
        git_repo,
        tmp_path,
        objective=objective,
        decisions=decisions,
        next_step=next_step,
        command=f"touch {marker}",
    )
    assert not marker.exists()
    _assert_repo_clean(git_repo)

    _run(run_command, cwd=run_cwd, env=env)

    assert marker.exists()
    status_after = _run(["git", "status", "--porcelain"], cwd=git_repo)
    assert marker_name in status_after


def _assert_opt_in_run_without_commands_keeps_repo_clean(
    git_repo: Path,
    tmp_path: Path,
    *,
    run_command: RunCommand,
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
    env = _seed_opt_in_checkpoint(
        git_repo,
        tmp_path,
        objective=objective,
        decisions=decisions,
        next_step=next_step,
        command=None,
    )
    _assert_repo_clean(git_repo)
    _run(run_command, cwd=run_cwd, env=env)
    _assert_repo_clean(git_repo)


def _assert_opt_in_run_without_commands_for_scope(
    git_repo: Path,
    tmp_path: Path,
    *,
    command_name: str,
    include_berth: bool,
    include_branch: bool,
    run_cwd_kind: RunCwdKind,
    objective: str,
    decisions: str,
    next_step: str,
) -> None:
    """Assert no-command opt-in run path is non-mutating for a scope variant."""
    branch = _current_branch(git_repo) if include_branch else None
    _assert_opt_in_run_without_commands_keeps_repo_clean(
        git_repo,
        tmp_path,
        run_command=_build_opt_in_run_command(
            command_name=command_name,
            git_repo=git_repo,
            branch=branch,
            include_berth=include_berth,
        ),
        run_cwd=_resolve_run_cwd(git_repo, tmp_path, run_cwd_kind),
        objective=objective,
        decisions=decisions,
        next_step=next_step,
    )


def _assert_opt_in_run_mutates_for_scope(
    git_repo: Path,
    tmp_path: Path,
    *,
    command_name: str,
    include_berth: bool,
    include_branch: bool,
    run_cwd_kind: RunCwdKind,
    marker_name: str,
    objective: str,
    decisions: str,
    next_step: str,
) -> None:
    """Assert opt-in run path may mutate repo for a scope variant."""
    branch = _current_branch(git_repo) if include_branch else None
    _assert_opt_in_run_mutates_repo(
        git_repo,
        tmp_path,
        run_command=_build_opt_in_run_command(
            command_name=command_name,
            git_repo=git_repo,
            branch=branch,
            include_berth=include_berth,
        ),
        run_cwd=_resolve_run_cwd(git_repo, tmp_path, run_cwd_kind),
        marker_name=marker_name,
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
) -> CommandMatrix:
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
    commands: CommandMatrix,
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


def _build_resume_read_commands_in_repo(git_repo: Path) -> CommandMatrix:
    """Build in-repo resume read-only command matrix."""
    return [
        *_resume_read_variants("resume"),
        *_resume_read_variants("r", include_json=False, include_handoff=False),
        *_resume_read_variants("undock", include_json=False, include_handoff=False),
    ]


def _build_resume_read_commands_alias_berth(git_repo: Path) -> CommandMatrix:
    """Build berth-targeted alias resume read-only command matrix."""
    base_branch = _current_branch(git_repo)
    return [
        *_resume_read_variants("r", berth=git_repo.name, branch=base_branch),
        *_resume_read_variants("undock", berth=git_repo.name, branch=base_branch),
    ]


def _build_resume_read_commands_alias_trimmed_berth(git_repo: Path) -> CommandMatrix:
    """Build trimmed berth/branch alias resume read-only command matrix."""
    base_branch = _current_branch(git_repo)
    trimmed_berth = f"  {git_repo.name}  "
    trimmed_branch = f"  {base_branch}  "
    return [
        *_resume_read_variants("r", berth=trimmed_berth, branch=trimmed_branch),
        *_resume_read_variants("undock", berth=trimmed_berth, branch=trimmed_branch),
    ]


def _build_resume_read_commands_primary_trimmed_berth(git_repo: Path) -> CommandMatrix:
    """Build trimmed berth/branch primary resume read-only command matrix."""
    base_branch = _current_branch(git_repo)
    trimmed_berth = f"  {git_repo.name}  "
    trimmed_branch = f"  {base_branch}  "
    return _resume_read_variants("resume", berth=trimmed_berth, branch=trimmed_branch)


def _assert_review_link_commands_do_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    *,
    objective: str,
    decisions: str,
    next_step: str,
    run_cwd: Path,
    metadata_commands: CommandMatrix,
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


def _build_metadata_commands_in_repo(_git_repo: Path, _base_branch: str) -> CommandMatrix:
    """Build in-repo review/link metadata command list."""
    return [["python3", "-m", "dockyard", "link", "https://example.com/non-interference"]]


def _build_metadata_commands_root_override(git_repo: Path, _base_branch: str) -> CommandMatrix:
    """Build root-override review/link metadata command list."""
    return [
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
    ]


def _build_review_add_command_in_repo(_git_repo: Path, _base_branch: str) -> list[str]:
    """Build in-repo review-add command."""
    return [
        "python3",
        "-m",
        "dockyard",
        "review",
        "add",
        "--reason",
        "manual",
        "--severity",
        "low",
    ]


def _build_review_add_command_root_override(git_repo: Path, base_branch: str) -> list[str]:
    """Build root-override review-add command."""
    return [
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
    ]


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
    ids=SAVE_COMMAND_IDS,
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


def _build_in_repo_read_only_commands(base_branch: str) -> CommandMatrix:
    """Build in-repo read-only command matrix for non-interference checks."""
    return [
        ["python3", "-m", "dockyard", "resume"],
        ["python3", "-m", "dockyard", "resume", "--json"],
        ["python3", "-m", "dockyard", "resume", "--handoff"],
        ["python3", "-m", "dockyard", "resume", "--branch", base_branch],
        ["python3", "-m", "dockyard", "r"],
        ["python3", "-m", "dockyard", "undock"],
        ["python3", "-m", "dockyard", "links"],
    ]


def _build_dashboard_read_commands(
    command_name: str,
    *,
    include_non_json_tag_combo: bool = False,
) -> CommandMatrix:
    """Build ls/harbor read-only command matrix."""
    commands: CommandMatrix = [
        ["python3", "-m", "dockyard", command_name],
        ["python3", "-m", "dockyard", command_name, "--json"],
        ["python3", "-m", "dockyard", command_name, "--limit", "1", "--json"],
        ["python3", "-m", "dockyard", command_name, "--stale", "0", "--json"],
        ["python3", "-m", "dockyard", command_name, "--tag", "baseline", "--json"],
        [
            "python3",
            "-m",
            "dockyard",
            command_name,
            "--tag",
            "baseline",
            "--stale",
            "0",
            "--limit",
            "1",
            "--json",
        ],
    ]
    if include_non_json_tag_combo:
        commands.append(
            [
                "python3",
                "-m",
                "dockyard",
                command_name,
                "--tag",
                "baseline",
                "--stale",
                "0",
                "--limit",
                "1",
            ],
        )
    return commands


def _build_search_read_commands(command_name: str, repo_name: str, base_branch: str) -> CommandMatrix:
    """Build search/f read-only command matrix."""
    commands: CommandMatrix = [
        ["python3", "-m", "dockyard", command_name, "baseline"],
        ["python3", "-m", "dockyard", command_name, "baseline", "--json"],
        ["python3", "-m", "dockyard", command_name, "baseline", "--tag", "baseline"],
        ["python3", "-m", "dockyard", command_name, "baseline", "--tag", "missing-tag"],
        ["python3", "-m", "dockyard", command_name, "baseline", "--repo", repo_name],
        ["python3", "-m", "dockyard", command_name, "baseline", "--branch", base_branch],
        [
            "python3",
            "-m",
            "dockyard",
            command_name,
            "baseline",
            "--tag",
            "baseline",
            "--branch",
            base_branch,
        ],
        [
            "python3",
            "-m",
            "dockyard",
            command_name,
            "baseline",
            "--tag",
            "baseline",
            "--branch",
            base_branch,
            "--json",
        ],
        [
            "python3",
            "-m",
            "dockyard",
            command_name,
            "baseline",
            "--tag",
            "baseline",
            "--repo",
            repo_name,
            "--json",
        ],
        [
            "python3",
            "-m",
            "dockyard",
            command_name,
            "baseline",
            "--tag",
            "baseline",
            "--repo",
            repo_name,
            "--branch",
            base_branch,
            "--json",
        ],
        [
            "python3",
            "-m",
            "dockyard",
            command_name,
            "baseline",
            "--repo",
            repo_name,
            "--branch",
            base_branch,
            "--json",
        ],
    ]
    if command_name == "f":
        commands.extend(
            [
                ["python3", "-m", "dockyard", command_name, "baseline", "--repo", repo_name, "--json"],
                ["python3", "-m", "dockyard", command_name, "baseline", "--branch", base_branch, "--json"],
                [
                    "python3",
                    "-m",
                    "dockyard",
                    command_name,
                    "baseline",
                    "--tag",
                    "baseline",
                    "--repo",
                    repo_name,
                ],
                [
                    "python3",
                    "-m",
                    "dockyard",
                    command_name,
                    "baseline",
                    "--tag",
                    "baseline",
                    "--repo",
                    repo_name,
                    "--branch",
                    base_branch,
                ],
            ],
        )
    return commands


def _build_outside_repo_read_only_commands(repo_name: str, base_branch: str) -> CommandMatrix:
    """Build outside-repo read-only command matrix for non-interference checks."""
    return [
        *_resume_read_variants("resume", berth=repo_name, branch=base_branch),
        *_build_dashboard_read_commands("ls"),
        *_build_dashboard_read_commands("harbor", include_non_json_tag_combo=True),
        *_build_search_read_commands("search", repo_name, base_branch),
        *_build_search_read_commands("f", repo_name, base_branch),
        ["python3", "-m", "dockyard", "review"],
        ["python3", "-m", "dockyard", "review", "list"],
        ["python3", "-m", "dockyard", "review", "--all"],
        ["python3", "-m", "dockyard", "review", "list", "--all"],
    ]


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

    _run_commands(_build_in_repo_read_only_commands(base_branch), cwd=git_repo, env=env)
    _run_commands(
        _build_outside_repo_read_only_commands(repo_name=git_repo.name, base_branch=base_branch),
        cwd=tmp_path,
        env=env,
    )

    _assert_repo_clean(git_repo)


@pytest.mark.parametrize(
    ("marker_name", "objective", "decisions", "next_step", "commands_builder", "run_cwd_kind"),
    [
        (
            "dockyard_resume_should_not_run.txt",
            "Resume command safety baseline",
            "Ensure resume read paths do not execute stored commands",
            "Inspect resume output",
            _build_resume_read_commands_in_repo,
            "repo",
        ),
        (
            "dockyard_alias_berth_resume_should_not_run.txt",
            "Alias berth command safety baseline",
            "Ensure alias berth read paths do not execute stored commands",
            "Inspect alias berth resume output",
            _build_resume_read_commands_alias_berth,
            "tmp",
        ),
        (
            "dockyard_alias_trimmed_resume_should_not_run.txt",
            "Alias trimmed berth command safety baseline",
            "Ensure trimmed alias berth read paths do not execute stored commands",
            "Inspect trimmed alias berth resume output",
            _build_resume_read_commands_alias_trimmed_berth,
            "tmp",
        ),
        (
            "dockyard_primary_trimmed_resume_should_not_run.txt",
            "Primary trimmed berth command safety baseline",
            "Ensure trimmed primary berth read paths do not execute commands",
            "Inspect trimmed primary berth resume output",
            _build_resume_read_commands_primary_trimmed_berth,
            "tmp",
        ),
    ],
    ids=["in_repo_default", "alias_berth", "alias_trimmed_berth", "primary_trimmed_berth"],
)
def test_resume_read_paths_do_not_execute_saved_commands(
    git_repo: Path,
    tmp_path: Path,
    marker_name: str,
    objective: str,
    decisions: str,
    next_step: str,
    commands_builder: Callable[[Path], CommandMatrix],
    run_cwd_kind: RunCwdKind,
) -> None:
    """Resume read-only path variants must never execute stored commands."""
    _assert_resume_read_paths_do_not_execute_saved_commands(
        git_repo,
        tmp_path,
        marker_name=marker_name,
        objective=objective,
        decisions=decisions,
        next_step=next_step,
        commands=commands_builder(git_repo),
        run_cwd=_resolve_run_cwd(git_repo, tmp_path, run_cwd_kind),
    )


@pytest.mark.parametrize(
    (
        "objective",
        "decisions",
        "next_step",
        "run_cwd_kind",
        "metadata_builder",
        "review_add_builder",
    ),
    [
        (
            "Mutation command baseline",
            "Validate review/link non-interference",
            "Run link and review commands",
            "repo",
            _build_metadata_commands_in_repo,
            _build_review_add_command_in_repo,
        ),
        (
            "Root override mutation baseline",
            "Validate root override review/link non-interference",
            "Run root override metadata commands",
            "tmp",
            _build_metadata_commands_root_override,
            _build_review_add_command_root_override,
        ),
    ],
    ids=["in_repo", "root_override"],
)
def test_review_and_link_commands_do_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    objective: str,
    decisions: str,
    next_step: str,
    run_cwd_kind: RunCwdKind,
    metadata_builder: MetadataCommandBuilder,
    review_add_builder: ReviewAddCommandBuilder,
) -> None:
    """Review/link metadata paths must not alter repository tree/index."""
    base_branch = _current_branch(git_repo)
    _assert_review_link_commands_do_not_modify_repo(
        git_repo,
        tmp_path,
        objective=objective,
        decisions=decisions,
        next_step=next_step,
        run_cwd=_resolve_run_cwd(git_repo, tmp_path, run_cwd_kind),
        metadata_commands=metadata_builder(git_repo, base_branch),
        review_add_command=review_add_builder(git_repo, base_branch),
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
    ids=SAVE_COMMAND_IDS,
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
    ids=SAVE_COMMAND_IDS,
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
    (
        "command_name",
        "include_berth",
        "include_branch",
        "run_cwd_kind",
        "objective",
        "decisions",
        "next_step",
    ),
    [
        (
            "resume",
            False,
            False,
            "repo",
            "Resume run no-commands baseline",
            "Verify resume --run no-op path remains non-mutating",
            "run resume --run",
        ),
        (
            "r",
            False,
            False,
            "repo",
            "Resume alias run no-commands baseline",
            "Verify r --run no-op path remains non-mutating",
            "run r --run",
        ),
        (
            "undock",
            False,
            False,
            "repo",
            "Undock alias run no-commands baseline",
            "Verify undock --run no-op path remains non-mutating",
            "run undock --run",
        ),
        (
            "resume",
            True,
            False,
            "tmp",
            "Resume berth run no-commands baseline",
            "Verify resume <berth> --run no-op path remains non-mutating",
            "run resume <berth> --run",
        ),
        (
            "r",
            True,
            False,
            "tmp",
            "Resume alias berth run no-commands baseline",
            "Verify r <berth> --run no-op path remains non-mutating",
            "run r <berth> --run",
        ),
        (
            "undock",
            True,
            False,
            "tmp",
            "Undock alias berth run no-commands baseline",
            "Verify undock <berth> --run no-op path remains non-mutating",
            "run undock <berth> --run",
        ),
        (
            "resume",
            False,
            True,
            "repo",
            "Resume branch run no-commands baseline",
            "Verify resume --branch <name> --run no-op path is non-mutating",
            "run resume --branch <name> --run",
        ),
        (
            "r",
            False,
            True,
            "repo",
            "Resume alias branch run no-commands baseline",
            "Verify r --branch <name> --run no-op path is non-mutating",
            "run r --branch <name> --run",
        ),
        (
            "undock",
            False,
            True,
            "repo",
            "Undock alias branch run no-commands baseline",
            "Verify undock --branch <name> --run no-op path is non-mutating",
            "run undock --branch <name> --run",
        ),
        (
            "resume",
            True,
            True,
            "tmp",
            "Resume berth+branch run no-commands baseline",
            "Verify resume <berth> --branch <name> --run no-op is non-mutating",
            "run resume <berth> --branch <name> --run",
        ),
        (
            "r",
            True,
            True,
            "tmp",
            "Resume alias berth+branch run no-commands baseline",
            "Verify r <berth> --branch <name> --run no-op is non-mutating",
            "run r <berth> --branch <name> --run",
        ),
        (
            "undock",
            True,
            True,
            "tmp",
            "Undock alias berth+branch run no-commands baseline",
            "Verify undock <berth> --branch <name> --run no-op is non-mutating",
            "run undock <berth> --branch <name> --run",
        ),
    ],
    ids=RUN_SCOPE_IDS_DEFAULT_BERTH_BRANCH,
)
def test_run_scopes_without_commands_keep_repo_clean(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
    include_berth: bool,
    include_branch: bool,
    run_cwd_kind: RunCwdKind,
    objective: str,
    decisions: str,
    next_step: str,
) -> None:
    """No-command run scopes should remain non-mutating."""
    _assert_opt_in_run_without_commands_for_scope(
        git_repo,
        tmp_path,
        command_name=command_name,
        include_berth=include_berth,
        include_branch=include_branch,
        run_cwd_kind=run_cwd_kind,
        objective=objective,
        decisions=decisions,
        next_step=next_step,
    )


@pytest.mark.parametrize(
    (
        "command_name",
        "include_berth",
        "include_branch",
        "run_cwd_kind",
        "marker_name",
        "objective",
        "decisions",
        "next_step",
    ),
    [
        (
            "resume",
            False,
            False,
            "repo",
            "resume_run_opt_in_marker.txt",
            "Resume run opt-in mutation baseline",
            "Verify explicit --run path may execute mutating commands",
            "run resume --run",
        ),
        (
            "r",
            False,
            False,
            "repo",
            "resume_alias_run_opt_in_marker.txt",
            "Resume alias run opt-in mutation baseline",
            "Verify r --run may execute mutating commands",
            "run r --run",
        ),
        (
            "undock",
            False,
            False,
            "repo",
            "undock_alias_run_opt_in_marker.txt",
            "Undock alias run opt-in mutation baseline",
            "Verify undock --run may execute mutating commands",
            "run undock --run",
        ),
        (
            "resume",
            False,
            True,
            "repo",
            "resume_run_with_branch_opt_in_marker.txt",
            "Resume branch run opt-in mutation baseline",
            "Verify resume --branch <name> --run may execute mutating commands",
            "run resume --branch <name> --run",
        ),
        (
            "r",
            False,
            True,
            "repo",
            "resume_alias_run_with_branch_opt_in_marker.txt",
            "Resume alias branch run opt-in mutation baseline",
            "Verify r --branch <name> --run may execute mutating commands",
            "run r --branch <name> --run",
        ),
        (
            "undock",
            False,
            True,
            "repo",
            "undock_alias_run_with_branch_opt_in_marker.txt",
            "Undock alias branch run opt-in mutation baseline",
            "Verify undock --branch <name> --run may execute mutating commands",
            "run undock --branch <name> --run",
        ),
        (
            "resume",
            True,
            False,
            "tmp",
            "resume_run_with_berth_opt_in_marker.txt",
            "Resume berth run opt-in mutation baseline",
            "Verify resume <berth> --run may execute mutating commands",
            "run resume <berth> --run",
        ),
        (
            "r",
            True,
            False,
            "tmp",
            "resume_alias_run_with_berth_opt_in_marker.txt",
            "Resume alias berth run opt-in mutation baseline",
            "Verify r <berth> --run may execute mutating commands",
            "run r <berth> --run",
        ),
        (
            "undock",
            True,
            False,
            "tmp",
            "undock_alias_run_opt_in_marker.txt",
            "Undock alias run opt-in mutation baseline",
            "Verify undock --run with berth may execute mutating commands",
            "run undock <berth> --run",
        ),
        (
            "resume",
            True,
            True,
            "tmp",
            "resume_run_with_berth_branch_opt_in_marker.txt",
            "Resume berth+branch run opt-in mutation baseline",
            "Verify resume <berth> --branch <branch> --run may mutate repo",
            "run resume <berth> --branch <branch> --run",
        ),
        (
            "r",
            True,
            True,
            "tmp",
            "resume_alias_run_with_berth_branch_opt_in_marker.txt",
            "Resume alias berth+branch run opt-in mutation baseline",
            "Verify r <berth> --branch <branch> --run may mutate repo",
            "run r <berth> --branch <branch> --run",
        ),
        (
            "undock",
            True,
            True,
            "tmp",
            "undock_alias_run_with_berth_branch_opt_in_marker.txt",
            "Undock alias berth+branch run opt-in mutation baseline",
            "Verify undock <berth> --branch <branch> --run may mutate repo",
            "run undock <berth> --branch <branch> --run",
        ),
    ],
    ids=RUN_SCOPE_IDS_DEFAULT_BRANCH_BERTH,
)
def test_run_scopes_opt_in_can_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
    include_berth: bool,
    include_branch: bool,
    run_cwd_kind: RunCwdKind,
    marker_name: str,
    objective: str,
    decisions: str,
    next_step: str,
) -> None:
    """Opt-in run scopes may mutate repository as expected."""
    _assert_opt_in_run_mutates_for_scope(
        git_repo,
        tmp_path,
        command_name=command_name,
        include_berth=include_berth,
        include_branch=include_branch,
        run_cwd_kind=run_cwd_kind,
        marker_name=marker_name,
        objective=objective,
        decisions=decisions,
        next_step=next_step,
    )
