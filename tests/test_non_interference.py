"""Tests ensuring Dockyard does not mutate project repos by default."""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal

import pytest

CommandMatrix = list[list[str]]
RunCommand = list[str]
ResumeReadCommandBuilder = Callable[[Path], CommandMatrix]
MetadataCommandBuilder = Callable[[Path, str], CommandMatrix]
ReviewAddCommandBuilder = Callable[[Path, str], list[str]]
RunCwdKind = Literal["repo", "tmp"]
RunScopeCase = tuple[str, bool, bool, RunCwdKind, str]
RunScopeVariant = tuple[str, bool, bool, RunCwdKind]
SaveCommandCase = tuple[str, str, str]
ResumeReadPathCase = tuple[str, str, str, ResumeReadCommandBuilder, RunCwdKind]
MetadataScopeCase = tuple[str, str, RunCwdKind, MetadataCommandBuilder, ReviewAddCommandBuilder]
ResumeReadPathScenario = tuple[str, str, str, str, ResumeReadCommandBuilder, RunCwdKind]
MetadataScopeScenario = tuple[str, str, str, RunCwdKind, MetadataCommandBuilder, ReviewAddCommandBuilder]
SAVE_COMMAND_CASES: tuple[SaveCommandCase, ...] = (
    ("save", "save", "save"),
    ("s", "alias_s", "s_alias"),
    ("dock", "alias_dock", "dock_alias"),
)
SAVE_COMMAND_IDS: tuple[str, ...] = tuple(case[2] for case in SAVE_COMMAND_CASES)
RUN_SCOPE_COMMANDS: tuple[str, ...] = ("resume", "r", "undock")
RUN_SCOPE_COMMAND_ORDER = {name: index for index, name in enumerate(RUN_SCOPE_COMMANDS)}
RUN_SCOPE_COMMAND_LABELS = {"resume": "resume", "r": "resume alias", "undock": "undock alias"}
RUN_SCOPE_VARIANTS_DEFAULT_BERTH_BRANCH: tuple[RunScopeVariant, ...] = (
    ("default", False, False, "repo"),
    ("berth", True, False, "tmp"),
    ("branch", False, True, "repo"),
    ("berth_branch", True, True, "tmp"),
)


def _run_scope_branch_before_berth_sort_key(case: RunScopeCase) -> tuple[int, int]:
    """Return sort key that prioritizes branch-only scopes before berth-only.

    Args:
        case: Run-scope metadata tuple.

    Returns:
        Tuple sorted by scope family then command ordering.
    """
    command_name, include_berth, include_branch, _run_cwd_kind, _scope_id = case
    if not include_berth and not include_branch:
        scope_rank = 0
    elif include_branch and not include_berth:
        scope_rank = 1
    elif include_berth and not include_branch:
        scope_rank = 2
    else:
        scope_rank = 3
    return (scope_rank, RUN_SCOPE_COMMAND_ORDER[command_name])


RUN_SCOPE_CASES_DEFAULT_BERTH_BRANCH: tuple[RunScopeCase, ...] = tuple(
    (
        command_name,
        include_berth,
        include_branch,
        run_cwd_kind,
        f"{command_name}_{variant_id}",
    )
    for variant_id, include_berth, include_branch, run_cwd_kind in RUN_SCOPE_VARIANTS_DEFAULT_BERTH_BRANCH
    for command_name in RUN_SCOPE_COMMANDS
)
RUN_SCOPE_CASES_DEFAULT_BRANCH_BERTH: tuple[RunScopeCase, ...] = tuple(
    sorted(
        RUN_SCOPE_CASES_DEFAULT_BERTH_BRANCH,
        key=_run_scope_branch_before_berth_sort_key,
    ),
)
RunNoCommandScenario = tuple[str, bool, bool, RunCwdKind, str, str, str]
RunOptInMutationScenario = tuple[str, bool, bool, RunCwdKind, str, str, str, str]
SaveNoPromptScenario = tuple[str, str, str, str, str, str, str]
SaveEditorScenario = tuple[str, str, str, str]
SaveTemplateScenario = tuple[str, str, str]


def _scope_label(scope_id: str) -> str:
    """Return human-readable scope label derived from scope ID."""
    return scope_id.replace("_", " ")


def _run_scope_descriptor(include_berth: bool, include_branch: bool) -> str:
    """Return scope descriptor text for run-scenario metadata strings."""
    if include_berth and include_branch:
        return "berth+branch"
    if include_berth:
        return "berth"
    if include_branch:
        return "branch"
    return "default"


def _scope_ids(cases: Sequence[RunScopeCase]) -> tuple[str, ...]:
    """Return pytest ID labels derived from run-scope metadata."""
    return tuple(case[4] for case in cases)


RUN_SCOPE_IDS_DEFAULT_BERTH_BRANCH: tuple[str, ...] = _scope_ids(RUN_SCOPE_CASES_DEFAULT_BERTH_BRANCH)
RUN_SCOPE_IDS_DEFAULT_BRANCH_BERTH: tuple[str, ...] = _scope_ids(RUN_SCOPE_CASES_DEFAULT_BRANCH_BERTH)


def _build_no_command_run_scope_scenarios(cases: Sequence[RunScopeCase]) -> list[RunNoCommandScenario]:
    """Build no-command run-scope scenarios from shared scope metadata.

    Args:
        cases: Scope metadata tuples containing command/scope configuration.

    Returns:
        Parameter tuples for no-command run-scope tests.
    """
    scenarios: list[RunNoCommandScenario] = []
    for command_name, include_berth, include_branch, run_cwd_kind, scope_id in cases:
        command_label = RUN_SCOPE_COMMAND_LABELS[command_name]
        scope_descriptor = _run_scope_descriptor(include_berth, include_branch)
        scenarios.append(
            (
                command_name,
                include_berth,
                include_branch,
                run_cwd_kind,
                f"{command_label} {scope_descriptor} run no-commands baseline",
                f"Verify {command_label} {scope_descriptor} --run no-op path remains non-mutating",
                f"run {command_label} {scope_descriptor} --run",
            ),
        )
    return scenarios


def _build_opt_in_mutation_run_scope_scenarios(
    cases: Sequence[RunScopeCase],
) -> list[RunOptInMutationScenario]:
    """Build opt-in mutation run-scope scenarios from shared scope metadata.

    Args:
        cases: Scope metadata tuples containing command/scope configuration.

    Returns:
        Parameter tuples for opt-in mutation run-scope tests.
    """
    scenarios: list[RunOptInMutationScenario] = []
    for command_name, include_berth, include_branch, run_cwd_kind, scope_id in cases:
        command_label = RUN_SCOPE_COMMAND_LABELS[command_name]
        scope_descriptor = _run_scope_descriptor(include_berth, include_branch)
        scenarios.append(
            (
                command_name,
                include_berth,
                include_branch,
                run_cwd_kind,
                f"{scope_id}_opt_in_marker.txt",
                f"{command_label} {scope_descriptor} opt-in mutation baseline",
                f"Verify {command_label} {scope_descriptor} --run may execute mutating commands",
                f"run {command_label} {scope_descriptor} --run",
            ),
        )
    return scenarios


def _build_save_no_prompt_scenarios(cases: Sequence[SaveCommandCase]) -> list[SaveNoPromptScenario]:
    """Build no-prompt save scenarios from shared command metadata.

    Args:
        cases: Save command metadata tuples.

    Returns:
        Parameter tuples for no-prompt save non-interference tests.
    """
    scenarios: list[SaveNoPromptScenario] = []
    for command_name, case_label, _case_id in cases:
        scenarios.append(
            (
                command_name,
                f"{case_label} no-prompt objective",
                f"{case_label} no-prompt decisions",
                f"run {case_label} resume",
                "none",
                f"echo {case_label}-resume",
                f"echo {case_label}-build",
            ),
        )
    return scenarios


def _build_save_editor_scenarios(cases: Sequence[SaveCommandCase]) -> list[SaveEditorScenario]:
    """Build save/editor scenarios from shared command metadata.

    Args:
        cases: Save command metadata tuples.

    Returns:
        Parameter tuples for save/editor non-interference tests.
    """
    scenarios: list[SaveEditorScenario] = []
    for command_name, case_label, _case_id in cases:
        scenarios.append(
            (
                command_name,
                f"{case_label}_editor.sh",
                f"{case_label} editor decisions for non-interference",
                f"{case_label} editor non-interference objective",
            ),
        )
    return scenarios


def _build_save_template_scenarios(cases: Sequence[SaveCommandCase]) -> list[SaveTemplateScenario]:
    """Build save/template scenarios from shared command metadata.

    Args:
        cases: Save command metadata tuples.

    Returns:
        Parameter tuples for save/template non-interference tests.
    """
    scenarios: list[SaveTemplateScenario] = []
    for command_name, case_label, _case_id in cases:
        scenarios.append(
            (
                command_name,
                f"{case_label}_template.json",
                f"{case_label} template non-interference objective",
            ),
        )
    return scenarios


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


def _build_resume_read_path_scenarios(
    cases: Sequence[ResumeReadPathCase],
) -> list[ResumeReadPathScenario]:
    """Build resume-read non-interference scenarios from shared case metadata.

    Args:
        cases: Resume-read case metadata tuples.

    Returns:
        Parameter tuples for resume-read non-interference test coverage.
    """
    scenarios: list[ResumeReadPathScenario] = []
    for _case_id, scope_label, marker_name, commands_builder, run_cwd_kind in cases:
        scenarios.append(
            (
                marker_name,
                f"{scope_label} command safety baseline",
                f"Ensure {scope_label} read paths do not execute stored commands",
                f"Inspect {scope_label} resume output",
                commands_builder,
                run_cwd_kind,
            ),
        )
    return scenarios


def _build_metadata_scope_scenarios(cases: Sequence[MetadataScopeCase]) -> list[MetadataScopeScenario]:
    """Build metadata-scope non-interference scenarios from shared cases.

    Args:
        cases: Metadata-scope case metadata tuples.

    Returns:
        Parameter tuples for metadata-scope non-interference tests.
    """
    scenarios: list[MetadataScopeScenario] = []
    for _case_id, scope_label, run_cwd_kind, metadata_builder, review_add_builder in cases:
        scenarios.append(
            (
                f"{scope_label} mutation command baseline",
                f"Validate {scope_label} review/link non-interference",
                f"Run {scope_label} metadata commands",
                run_cwd_kind,
                metadata_builder,
                review_add_builder,
            ),
        )
    return scenarios


RESUME_READ_PATH_CASES: tuple[ResumeReadPathCase, ...] = (
    (
        "in_repo_default",
        "in-repo default",
        "dockyard_resume_should_not_run.txt",
        _build_resume_read_commands_in_repo,
        "repo",
    ),
    (
        "alias_berth",
        "alias berth",
        "dockyard_alias_berth_resume_should_not_run.txt",
        _build_resume_read_commands_alias_berth,
        "tmp",
    ),
    (
        "alias_trimmed_berth",
        "alias trimmed berth",
        "dockyard_alias_trimmed_resume_should_not_run.txt",
        _build_resume_read_commands_alias_trimmed_berth,
        "tmp",
    ),
    (
        "primary_trimmed_berth",
        "primary trimmed berth",
        "dockyard_primary_trimmed_resume_should_not_run.txt",
        _build_resume_read_commands_primary_trimmed_berth,
        "tmp",
    ),
)
RESUME_READ_PATH_IDS: tuple[str, ...] = tuple(case[0] for case in RESUME_READ_PATH_CASES)

METADATA_SCOPE_CASES: tuple[MetadataScopeCase, ...] = (
    ("in_repo", "in-repo", "repo", _build_metadata_commands_in_repo, _build_review_add_command_in_repo),
    (
        "root_override",
        "root override",
        "tmp",
        _build_metadata_commands_root_override,
        _build_review_add_command_root_override,
    ),
)
METADATA_SCOPE_IDS: tuple[str, ...] = tuple(case[0] for case in METADATA_SCOPE_CASES)


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
    _build_save_no_prompt_scenarios(SAVE_COMMAND_CASES),
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
    _build_resume_read_path_scenarios(RESUME_READ_PATH_CASES),
    ids=RESUME_READ_PATH_IDS,
)
def test_resume_read_paths_do_not_execute_saved_commands(
    git_repo: Path,
    tmp_path: Path,
    marker_name: str,
    objective: str,
    decisions: str,
    next_step: str,
    commands_builder: ResumeReadCommandBuilder,
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
    _build_metadata_scope_scenarios(METADATA_SCOPE_CASES),
    ids=METADATA_SCOPE_IDS,
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
    _build_save_editor_scenarios(SAVE_COMMAND_CASES),
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
    _build_save_template_scenarios(SAVE_COMMAND_CASES),
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
    _build_no_command_run_scope_scenarios(RUN_SCOPE_CASES_DEFAULT_BERTH_BRANCH),
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
    _build_opt_in_mutation_run_scope_scenarios(RUN_SCOPE_CASES_DEFAULT_BRANCH_BERTH),
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
