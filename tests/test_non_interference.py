"""Tests ensuring Dockyard does not mutate project repos by default."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal

import pytest

from tests.metadata_utils import case_ids, pair_scope_cases_with_context

RunCommand = Sequence[str]
CommandMatrix = list[RunCommand]
ResumeReadCommandBuilder = Callable[[Path], CommandMatrix]
MetadataCommandBuilder = Callable[[Path, str], CommandMatrix]
ReviewAddCommandBuilder = Callable[[Path, str], RunCommand]
RunCwdKind = Literal["repo", "tmp"]
RunCommandName = Literal["resume", "r", "undock"]
SaveCommandName = Literal["save", "s", "dock"]
DashboardCommandName = Literal["ls", "harbor"]
SearchCommandName = Literal["search", "f"]
RunScopeVariantId = Literal["default", "berth", "branch", "berth_branch"]
DOCKYARD_COMMAND_PREFIX: tuple[str, ...] = ("python3", "-m", "dockyard")


@dataclass(frozen=True)
class RunScopeCaseMeta:
    """Metadata describing a command scoped run scenario."""

    command_name: RunCommandName
    include_berth: bool
    include_branch: bool
    run_cwd_kind: RunCwdKind
    variant_id: RunScopeVariantId
    case_id: str


@dataclass(frozen=True)
class RunScopeContextMeta:
    """Rendered context metadata for a run-scope scenario."""

    command_label: str
    scope_descriptor: str

    @property
    def phrase(self) -> str:
        """Return combined command/scope phrase for scenario text."""
        return f"{self.command_label} {self.scope_descriptor}"


@dataclass(frozen=True)
class SaveCommandMeta:
    """Metadata describing a save command token."""

    name: SaveCommandName
    slug: str
    case_id: str


@dataclass(frozen=True)
class RunScopeCommandMeta:
    """Metadata describing a run-capable command token."""

    name: RunCommandName
    label: str


@dataclass(frozen=True)
class RunScopeVariantMeta:
    """Metadata describing a run-scope variant."""

    variant_id: RunScopeVariantId
    include_berth: bool
    include_branch: bool
    run_cwd_kind: RunCwdKind
    descriptor: str
    sort_rank: int


@dataclass(frozen=True)
class ResumeReadPathMeta:
    """Metadata describing a resume read-path non-interference case."""

    case_id: str
    scope_label: str
    marker_name: str
    commands_builder: ResumeReadCommandBuilder
    run_cwd_kind: RunCwdKind


@dataclass(frozen=True)
class MetadataScopeMeta:
    """Metadata describing a review/link metadata non-interference case."""

    case_id: str
    scope_label: str
    run_cwd_kind: RunCwdKind
    metadata_builder: MetadataCommandBuilder
    review_add_builder: ReviewAddCommandBuilder


@dataclass(frozen=True)
class ResumeReadPathScenarioMeta:
    """Rendered scenario metadata for resume read-path tests."""

    case_id: str
    marker_name: str
    objective: str
    decisions: str
    next_step: str
    commands_builder: ResumeReadCommandBuilder
    run_cwd_kind: RunCwdKind


@dataclass(frozen=True)
class MetadataScopeScenarioMeta:
    """Rendered scenario metadata for review/link non-interference tests."""

    case_id: str
    objective: str
    decisions: str
    next_step: str
    run_cwd_kind: RunCwdKind
    metadata_builder: MetadataCommandBuilder
    review_add_builder: ReviewAddCommandBuilder


@dataclass(frozen=True)
class DashboardReadVariantMeta:
    """Metadata describing a dashboard read-command argument suffix."""

    args_suffix: tuple[str, ...]
    include_only_when_requested: bool = False


@dataclass(frozen=True)
class SearchReadVariantMeta:
    """Metadata describing a search read-command argument suffix."""

    args_suffix_template: tuple[str, ...]


SAVE_COMMAND_CASES: tuple[SaveCommandMeta, ...] = (
    SaveCommandMeta("save", "save", "save"),
    SaveCommandMeta("s", "alias_s", "s_alias"),
    SaveCommandMeta("dock", "alias_dock", "dock_alias"),
)
RUN_SCOPE_COMMAND_CASES: tuple[RunScopeCommandMeta, ...] = (
    RunScopeCommandMeta("resume", "resume"),
    RunScopeCommandMeta("r", "resume alias"),
    RunScopeCommandMeta("undock", "undock alias"),
)
RUN_SCOPE_COMMANDS: tuple[RunCommandName, ...] = tuple(case.name for case in RUN_SCOPE_COMMAND_CASES)
RUN_SCOPE_COMMAND_ORDER: Mapping[RunCommandName, int] = MappingProxyType(
    {name: index for index, name in enumerate(RUN_SCOPE_COMMANDS)}
)
RUN_SCOPE_COMMAND_LABELS: Mapping[RunCommandName, str] = MappingProxyType(
    {case.name: case.label for case in RUN_SCOPE_COMMAND_CASES}
)
RUN_SCOPE_VARIANTS_DEFAULT_BERTH_BRANCH: tuple[RunScopeVariantMeta, ...] = (
    RunScopeVariantMeta("default", False, False, "repo", "default", 0),
    RunScopeVariantMeta("berth", True, False, "tmp", "berth", 2),
    RunScopeVariantMeta("branch", False, True, "repo", "branch", 1),
    RunScopeVariantMeta("berth_branch", True, True, "tmp", "berth+branch", 3),
)
RUN_SCOPE_DESCRIPTOR_BY_FLAGS: Mapping[tuple[bool, bool], str] = MappingProxyType(
    {
        (variant.include_berth, variant.include_branch): variant.descriptor
        for variant in RUN_SCOPE_VARIANTS_DEFAULT_BERTH_BRANCH
    }
)
RUN_SCOPE_VARIANT_RANK: Mapping[RunScopeVariantId, int] = MappingProxyType(
    {variant.variant_id: variant.sort_rank for variant in RUN_SCOPE_VARIANTS_DEFAULT_BERTH_BRANCH}
)
NON_INTERFERENCE_LINK_URL = "https://example.com/non-interference"
NON_INTERFERENCE_ROOT_OVERRIDE_LINK_URL = "https://example.com/non-interference-root-override"
SEARCH_REPO_PLACEHOLDER = "{repo_name}"
SEARCH_BRANCH_PLACEHOLDER = "{base_branch}"
DASHBOARD_READ_VARIANTS: tuple[DashboardReadVariantMeta, ...] = (
    DashboardReadVariantMeta(()),
    DashboardReadVariantMeta(("--json",)),
    DashboardReadVariantMeta(("--tag", "missing-tag", "--json")),
    DashboardReadVariantMeta(("--tag", "missing-tag", "--limit", "1", "--json")),
    DashboardReadVariantMeta(("--tag", "baseline", "--limit", "1", "--json")),
    DashboardReadVariantMeta(("--limit", "1", "--json")),
    DashboardReadVariantMeta(("--stale", "0", "--json")),
    DashboardReadVariantMeta(("--tag", "baseline", "--json")),
    DashboardReadVariantMeta(("--tag", "baseline", "--stale", "0", "--limit", "1", "--json")),
    DashboardReadVariantMeta(
        ("--tag", "baseline", "--limit", "1"),
        include_only_when_requested=True,
    ),
    DashboardReadVariantMeta(
        ("--tag", "missing-tag"),
        include_only_when_requested=True,
    ),
    DashboardReadVariantMeta(
        ("--tag", "missing-tag", "--limit", "1"),
        include_only_when_requested=True,
    ),
    DashboardReadVariantMeta(
        ("--tag", "baseline", "--stale", "0", "--limit", "1"),
        include_only_when_requested=True,
    ),
)
SEARCH_READ_VARIANTS: tuple[SearchReadVariantMeta, ...] = (
    SearchReadVariantMeta(("baseline",)),
    SearchReadVariantMeta(("definitely-no-match",)),
    SearchReadVariantMeta(("security/path",)),
    SearchReadVariantMeta(("baseline", "--json")),
    SearchReadVariantMeta(("security/path", "--json")),
    SearchReadVariantMeta(("security/path", "--tag", "baseline", "--limit", "1")),
    SearchReadVariantMeta(("security/path", "--tag", "baseline", "--limit", "1", "--json")),
    SearchReadVariantMeta(("baseline", "--tag", "baseline")),
    SearchReadVariantMeta(("baseline", "--tag", "missing-tag")),
    SearchReadVariantMeta(("baseline", "--tag", "baseline", "--limit", "1")),
    SearchReadVariantMeta(("baseline", "--tag", "baseline", "--limit", "1", "--json")),
    SearchReadVariantMeta(("baseline", "--repo", "missing-berth")),
    SearchReadVariantMeta(("baseline", "--branch", "missing/branch")),
    SearchReadVariantMeta(("baseline", "--branch", "missing/branch", "--limit", "1")),
    SearchReadVariantMeta(("baseline", "--branch", "missing/branch", "--limit", "1", "--json")),
    SearchReadVariantMeta(("baseline", "--repo", "missing-berth", "--branch", "missing/branch")),
    SearchReadVariantMeta(("baseline", "--repo", "missing-berth", "--branch", "missing/branch", "--limit", "1")),
    SearchReadVariantMeta(
        ("baseline", "--repo", "missing-berth", "--branch", "missing/branch", "--limit", "1", "--json")
    ),
    SearchReadVariantMeta(("baseline", "--repo", SEARCH_REPO_PLACEHOLDER)),
    SearchReadVariantMeta(("baseline", "--branch", SEARCH_BRANCH_PLACEHOLDER)),
    SearchReadVariantMeta(
        ("baseline", "--tag", "baseline", "--branch", SEARCH_BRANCH_PLACEHOLDER),
    ),
    SearchReadVariantMeta(("baseline", "--tag", "baseline", "--branch", "missing/branch")),
    SearchReadVariantMeta(
        ("baseline", "--tag", "baseline", "--branch", SEARCH_BRANCH_PLACEHOLDER, "--json"),
    ),
    SearchReadVariantMeta(("baseline", "--tag", "baseline", "--repo", "missing-berth")),
    SearchReadVariantMeta(("baseline", "--tag", "baseline", "--repo", "missing-berth", "--limit", "1")),
    SearchReadVariantMeta(("baseline", "--tag", "baseline", "--repo", "missing-berth", "--limit", "1", "--json")),
    SearchReadVariantMeta(("baseline", "--tag", "baseline", "--repo", SEARCH_REPO_PLACEHOLDER)),
    SearchReadVariantMeta(("baseline", "--tag", "baseline", "--repo", "missing-berth", "--branch", "missing/branch")),
    SearchReadVariantMeta(("baseline", "--tag", "baseline", "--repo", SEARCH_REPO_PLACEHOLDER, "--json")),
    SearchReadVariantMeta(
        (
            "baseline",
            "--tag",
            "baseline",
            "--repo",
            SEARCH_REPO_PLACEHOLDER,
            "--branch",
            SEARCH_BRANCH_PLACEHOLDER,
        ),
    ),
    SearchReadVariantMeta(
        (
            "baseline",
            "--tag",
            "baseline",
            "--repo",
            SEARCH_REPO_PLACEHOLDER,
            "--branch",
            SEARCH_BRANCH_PLACEHOLDER,
            "--limit",
            "1",
        ),
    ),
    SearchReadVariantMeta(
        (
            "baseline",
            "--tag",
            "baseline",
            "--repo",
            SEARCH_REPO_PLACEHOLDER,
            "--branch",
            SEARCH_BRANCH_PLACEHOLDER,
            "--json",
        ),
    ),
    SearchReadVariantMeta(
        (
            "baseline",
            "--tag",
            "baseline",
            "--repo",
            SEARCH_REPO_PLACEHOLDER,
            "--branch",
            SEARCH_BRANCH_PLACEHOLDER,
            "--limit",
            "1",
            "--json",
        ),
    ),
    SearchReadVariantMeta(("baseline", "--repo", SEARCH_REPO_PLACEHOLDER, "--branch", SEARCH_BRANCH_PLACEHOLDER)),
    SearchReadVariantMeta(("baseline", "--repo", SEARCH_REPO_PLACEHOLDER, "--branch", SEARCH_BRANCH_PLACEHOLDER, "--json")),
    SearchReadVariantMeta(("security/path", "--repo", SEARCH_REPO_PLACEHOLDER, "--branch", SEARCH_BRANCH_PLACEHOLDER)),
    SearchReadVariantMeta(("security/path", "--repo", SEARCH_REPO_PLACEHOLDER, "--branch", SEARCH_BRANCH_PLACEHOLDER, "--json")),
    SearchReadVariantMeta(
        (
            "security/path",
            "--tag",
            "baseline",
            "--repo",
            SEARCH_REPO_PLACEHOLDER,
            "--branch",
            SEARCH_BRANCH_PLACEHOLDER,
        ),
    ),
    SearchReadVariantMeta(
        (
            "security/path",
            "--tag",
            "baseline",
            "--repo",
            SEARCH_REPO_PLACEHOLDER,
            "--branch",
            SEARCH_BRANCH_PLACEHOLDER,
            "--limit",
            "1",
        ),
    ),
    SearchReadVariantMeta(
        (
            "security/path",
            "--tag",
            "baseline",
            "--repo",
            SEARCH_REPO_PLACEHOLDER,
            "--branch",
            SEARCH_BRANCH_PLACEHOLDER,
            "--json",
        ),
    ),
    SearchReadVariantMeta(
        (
            "security/path",
            "--tag",
            "baseline",
            "--repo",
            SEARCH_REPO_PLACEHOLDER,
            "--branch",
            SEARCH_BRANCH_PLACEHOLDER,
            "--limit",
            "1",
            "--json",
        ),
    ),
)
SEARCH_ALIAS_EXTRA_READ_VARIANTS: tuple[SearchReadVariantMeta, ...] = (
    SearchReadVariantMeta(("baseline", "--repo", SEARCH_REPO_PLACEHOLDER)),
    SearchReadVariantMeta(("baseline", "--branch", SEARCH_BRANCH_PLACEHOLDER)),
    SearchReadVariantMeta(("baseline", "--repo", SEARCH_REPO_PLACEHOLDER, "--branch", SEARCH_BRANCH_PLACEHOLDER)),
    SearchReadVariantMeta(("baseline", "--repo", SEARCH_REPO_PLACEHOLDER, "--json")),
    SearchReadVariantMeta(("baseline", "--branch", SEARCH_BRANCH_PLACEHOLDER, "--json")),
    SearchReadVariantMeta(("baseline", "--tag", "baseline", "--repo", SEARCH_REPO_PLACEHOLDER)),
    SearchReadVariantMeta(
        (
            "baseline",
            "--tag",
            "baseline",
            "--repo",
            SEARCH_REPO_PLACEHOLDER,
            "--branch",
            SEARCH_BRANCH_PLACEHOLDER,
        ),
    ),
)


def _run_scope_branch_before_berth_sort_key(case: RunScopeCaseMeta) -> tuple[int, int]:
    """Return sort key that prioritizes branch-only scopes before berth-only.

    Args:
        case: Run-scope metadata entry.

    Returns:
        Tuple sorted by scope family then command ordering.
    """
    scope_rank = RUN_SCOPE_VARIANT_RANK[case.variant_id]
    return (scope_rank, RUN_SCOPE_COMMAND_ORDER[case.command_name])


RUN_SCOPE_CASES_DEFAULT_BERTH_BRANCH: tuple[RunScopeCaseMeta, ...] = tuple(
    RunScopeCaseMeta(
        command_name=command_name,
        include_berth=variant.include_berth,
        include_branch=variant.include_branch,
        run_cwd_kind=variant.run_cwd_kind,
        variant_id=variant.variant_id,
        case_id=f"{command_name}_{variant.variant_id}",
    )
    for variant in RUN_SCOPE_VARIANTS_DEFAULT_BERTH_BRANCH
    for command_name in RUN_SCOPE_COMMANDS
)
RUN_SCOPE_CASES_DEFAULT_BRANCH_BERTH: tuple[RunScopeCaseMeta, ...] = tuple(
    sorted(
        RUN_SCOPE_CASES_DEFAULT_BERTH_BRANCH,
        key=_run_scope_branch_before_berth_sort_key,
    ),
)


@dataclass(frozen=True)
class RunNoCommandScenarioMeta:
    """Rendered scenario metadata for no-command run scope tests."""

    case_id: str
    command_name: RunCommandName
    include_berth: bool
    include_branch: bool
    run_cwd_kind: RunCwdKind
    objective: str
    decisions: str
    next_step: str


@dataclass(frozen=True)
class RunOptInMutationScenarioMeta:
    """Rendered scenario metadata for opt-in mutation run scope tests."""

    case_id: str
    command_name: RunCommandName
    include_berth: bool
    include_branch: bool
    run_cwd_kind: RunCwdKind
    marker_name: str
    objective: str
    decisions: str
    next_step: str


@dataclass(frozen=True)
class SaveNoPromptScenarioMeta:
    """Rendered scenario metadata for no-prompt save tests."""

    case_id: str
    command_name: SaveCommandName
    objective: str
    decisions: str
    next_step: str
    risks: str
    resume_command: str
    build_command: str


@dataclass(frozen=True)
class SaveEditorScenarioMeta:
    """Rendered scenario metadata for save editor-mode tests."""

    case_id: str
    command_name: SaveCommandName
    script_name: str
    decisions_text: str
    objective: str


@dataclass(frozen=True)
class SaveTemplateScenarioMeta:
    """Rendered scenario metadata for save template-mode tests."""

    case_id: str
    command_name: SaveCommandName
    template_name: str
    objective: str


def _run_scope_descriptor(include_berth: bool, include_branch: bool) -> str:
    """Return scope descriptor text for run-scenario metadata strings."""
    return RUN_SCOPE_DESCRIPTOR_BY_FLAGS[(include_berth, include_branch)]


def _run_scope_context(
    command_name: RunCommandName,
    include_berth: bool,
    include_branch: bool,
) -> RunScopeContextMeta:
    """Return command label plus scope descriptor for scenario text."""
    return RunScopeContextMeta(
        command_label=RUN_SCOPE_COMMAND_LABELS[command_name],
        scope_descriptor=_run_scope_descriptor(include_berth, include_branch),
    )


def _build_no_command_run_scope_scenarios(
    cases: Sequence[RunScopeCaseMeta],
) -> tuple[RunNoCommandScenarioMeta, ...]:
    """Build no-command run-scope scenarios from shared scope metadata.

    Args:
        cases: Scope metadata entries containing command/scope configuration.

    Returns:
        Rendered case metadata rows for no-command run-scope tests.
    """
    return tuple(
        RunNoCommandScenarioMeta(
            case_id=case.case_id,
            command_name=case.command_name,
            include_berth=case.include_berth,
            include_branch=case.include_branch,
            run_cwd_kind=case.run_cwd_kind,
            objective=f"{context.phrase} run no-commands baseline",
            decisions=f"Verify {context.phrase} --run no-op path remains non-mutating",
            next_step=f"run {context.phrase} --run",
        )
        for case, context in pair_scope_cases_with_context(cases, context_builder=_run_scope_context)
    )


def _build_opt_in_mutation_run_scope_scenarios(
    cases: Sequence[RunScopeCaseMeta],
) -> tuple[RunOptInMutationScenarioMeta, ...]:
    """Build opt-in mutation run-scope scenarios from shared scope metadata.

    Args:
        cases: Scope metadata entries containing command/scope configuration.

    Returns:
        Rendered case metadata rows for opt-in mutation run-scope tests.
    """
    return tuple(
        RunOptInMutationScenarioMeta(
            case_id=case.case_id,
            command_name=case.command_name,
            include_berth=case.include_berth,
            include_branch=case.include_branch,
            run_cwd_kind=case.run_cwd_kind,
            marker_name=f"{case.case_id}_opt_in_marker.txt",
            objective=f"{context.phrase} opt-in mutation baseline",
            decisions=f"Verify {context.phrase} --run may execute mutating commands",
            next_step=f"run {context.phrase} --run",
        )
        for case, context in pair_scope_cases_with_context(cases, context_builder=_run_scope_context)
    )


def _build_save_no_prompt_scenarios(
    cases: Sequence[SaveCommandMeta],
) -> tuple[SaveNoPromptScenarioMeta, ...]:
    """Build no-prompt save scenarios from shared command metadata.

    Args:
        cases: Save command metadata entries.

    Returns:
        Rendered case metadata rows for no-prompt save non-interference tests.
    """
    return tuple(
        SaveNoPromptScenarioMeta(
            case_id=case.case_id,
            command_name=case.name,
            objective=f"{case.slug} no-prompt objective",
            decisions=f"{case.slug} no-prompt decisions",
            next_step=f"run {case.slug} resume",
            risks="none",
            resume_command=f"echo {case.slug}-resume",
            build_command=f"echo {case.slug}-build",
        )
        for case in cases
    )


def _build_save_editor_scenarios(cases: Sequence[SaveCommandMeta]) -> tuple[SaveEditorScenarioMeta, ...]:
    """Build save/editor scenarios from shared command metadata.

    Args:
        cases: Save command metadata entries.

    Returns:
        Rendered case metadata rows for save/editor non-interference tests.
    """
    return tuple(
        SaveEditorScenarioMeta(
            case_id=case.case_id,
            command_name=case.name,
            script_name=f"{case.slug}_editor.sh",
            decisions_text=f"{case.slug} editor decisions for non-interference",
            objective=f"{case.slug} editor non-interference objective",
        )
        for case in cases
    )


def _build_save_template_scenarios(cases: Sequence[SaveCommandMeta]) -> tuple[SaveTemplateScenarioMeta, ...]:
    """Build save/template scenarios from shared command metadata.

    Args:
        cases: Save command metadata entries.

    Returns:
        Rendered case metadata rows for save/template non-interference tests.
    """
    return tuple(
        SaveTemplateScenarioMeta(
            case_id=case.case_id,
            command_name=case.name,
            template_name=f"{case.slug}_template.json",
            objective=f"{case.slug} template non-interference objective",
        )
        for case in cases
    )


def _run(command: RunCommand, cwd: Path, env: dict[str, str] | None = None) -> str:
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


def _run_commands(commands: Sequence[RunCommand], cwd: Path, env: dict[str, str]) -> None:
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
    command_name: RunCommandName,
    git_repo: Path,
    branch: str | None = None,
    include_berth: bool = False,
) -> RunCommand:
    """Build dockyard opt-in run command for non-interference checks."""
    run_command = _dockyard_command(command_name)
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
    command_name: RunCommandName,
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
    command_name: RunCommandName,
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
    command_name: RunCommandName,
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
    base_command = _dockyard_command(command_name)
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


def test_build_opt_in_run_command_includes_optional_scope_selectors(tmp_path: Path) -> None:
    """Opt-in run command helper should include optional berth/branch selectors."""
    git_repo = tmp_path / "demo-repo"

    assert _build_opt_in_run_command(command_name="resume", git_repo=git_repo) == _dockyard_command(
        "resume",
        "--run",
    )
    assert _build_opt_in_run_command(command_name="resume", git_repo=git_repo, branch="main") == (
        _dockyard_command(
            "resume",
            "--branch",
            "  main  ",
            "--run",
        )
    )
    assert _build_opt_in_run_command(
        command_name="undock",
        git_repo=git_repo,
        include_berth=True,
    ) == _dockyard_command(
        "undock",
        "  demo-repo  ",
        "--run",
    )
    assert _build_opt_in_run_command(
        command_name="r",
        git_repo=git_repo,
        branch="main",
        include_berth=True,
    ) == _dockyard_command(
        "r",
        "  demo-repo  ",
        "--branch",
        "  main  ",
        "--run",
    )


def test_resume_read_variants_respects_json_handoff_and_branch_flags() -> None:
    """Resume variant builder should honor include-json/handoff and branch options."""
    assert _resume_read_variants(
        "resume",
        include_json=False,
        include_handoff=False,
    ) == [_dockyard_command("resume")]

    assert _resume_read_variants(
        "resume",
        berth="demo-repo",
        branch="main",
        include_json=False,
        include_handoff=True,
    ) == [
        _dockyard_command("resume", "demo-repo"),
        _dockyard_command("resume", "demo-repo", "--handoff"),
        _dockyard_command("resume", "demo-repo", "--branch", "main"),
        _dockyard_command("resume", "demo-repo", "--branch", "main", "--handoff"),
    ]

    assert _resume_read_variants(
        "resume",
        berth="demo-repo",
        branch="main",
        include_json=True,
        include_handoff=False,
    ) == [
        _dockyard_command("resume", "demo-repo"),
        _dockyard_command("resume", "demo-repo", "--json"),
        _dockyard_command("resume", "demo-repo", "--branch", "main"),
        _dockyard_command("resume", "demo-repo", "--branch", "main", "--json"),
    ]


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
    _run(_dockyard_command("review", "open", review_id), cwd=run_cwd, env=env)
    _run(_dockyard_command("review", "done", review_id), cwd=run_cwd, env=env)
    _assert_repo_clean(git_repo)


def _dockyard_command(*args: str) -> RunCommand:
    """Build a dockyard command with the shared Python module prefix."""
    return [*DOCKYARD_COMMAND_PREFIX, *args]


def test_dockyard_command_includes_shared_prefix() -> None:
    """Dockyard command helper should prepend shared Python module prefix."""
    assert _dockyard_command("review", "list") == [
        "python3",
        "-m",
        "dockyard",
        "review",
        "list",
    ]


def test_dockyard_command_supports_empty_suffix() -> None:
    """Dockyard command helper should support empty command suffix."""
    assert _dockyard_command() == ["python3", "-m", "dockyard"]


def test_dockyard_command_returns_fresh_list_each_call() -> None:
    """Dockyard command helper should return a fresh mutable list per call."""
    first = _dockyard_command("links")
    second = _dockyard_command("links")

    first.append("--json")
    assert second == ["python3", "-m", "dockyard", "links"]


def _build_link_command(url: str, *, root: Path | None = None) -> RunCommand:
    """Build link command with optional explicit root override."""
    command = _dockyard_command("link", url)
    if root is not None:
        command.extend(["--root", str(root)])
    return command


def _build_links_command(*, root: Path | None = None) -> RunCommand:
    """Build links command with optional explicit root override."""
    command = _dockyard_command("links")
    if root is not None:
        command.extend(["--root", str(root)])
    return command


def _build_metadata_commands_in_repo(_git_repo: Path, _base_branch: str) -> CommandMatrix:
    """Build in-repo review/link metadata command list."""
    return [_build_link_command(NON_INTERFERENCE_LINK_URL)]


def _build_metadata_commands_root_override(git_repo: Path, _base_branch: str) -> CommandMatrix:
    """Build root-override review/link metadata command list."""
    return [
        _build_link_command(
            NON_INTERFERENCE_ROOT_OVERRIDE_LINK_URL,
            root=git_repo,
        ),
        _build_links_command(root=git_repo),
    ]


def _build_review_add_command_in_repo(_git_repo: Path, _base_branch: str) -> RunCommand:
    """Build in-repo review-add command."""
    return _build_review_add_command(reason="manual")


def _build_review_add_command_root_override(git_repo: Path, base_branch: str) -> RunCommand:
    """Build root-override review-add command."""
    return _build_review_add_command(
        reason="manual-root-override",
        repo=git_repo.name,
        branch=base_branch,
        notes="outside repo invocation",
    )


def _build_review_add_command(
    *,
    reason: str,
    repo: str | None = None,
    branch: str | None = None,
    notes: str | None = None,
) -> RunCommand:
    """Build review-add command with optional scoped arguments."""
    command = _dockyard_command(
        "review",
        "add",
        "--reason",
        reason,
        "--severity",
        "low",
    )
    if repo is not None:
        command.extend(["--repo", repo])
    if branch is not None:
        command.extend(["--branch", branch])
    if notes is not None:
        command.extend(["--notes", notes])
    return command


def test_build_review_add_command_omits_optional_scope_args() -> None:
    """Review-add builder should include only required arguments by default."""
    command = _build_review_add_command(reason="manual")

    assert command == [
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


def test_build_review_add_command_includes_optional_scope_args() -> None:
    """Review-add builder should append optional scope arguments in order."""
    command = _build_review_add_command(
        reason="manual-root-override",
        repo="demo-repo",
        branch="feature/demo",
        notes="outside repo invocation",
    )

    assert command == [
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
        "demo-repo",
        "--branch",
        "feature/demo",
        "--notes",
        "outside repo invocation",
    ]


def test_build_review_add_command_supports_partial_optional_scope_args() -> None:
    """Review-add builder should include only provided optional arguments."""
    command = _build_review_add_command(
        reason="manual-partial",
        repo="demo-repo",
    )

    assert command == [
        "python3",
        "-m",
        "dockyard",
        "review",
        "add",
        "--reason",
        "manual-partial",
        "--severity",
        "low",
        "--repo",
        "demo-repo",
    ]


def test_build_review_add_command_in_repo_delegates_to_helper() -> None:
    """In-repo review-add wrapper should delegate to generic helper defaults."""
    assert _build_review_add_command_in_repo(Path("/tmp/demo-repo"), "main") == _build_review_add_command(
        reason="manual",
    )


def test_build_review_add_command_root_override_delegates_to_helper() -> None:
    """Root-override review-add wrapper should delegate with scoped options."""
    git_repo = Path("/tmp/demo-repo")
    assert _build_review_add_command_root_override(git_repo, "main") == _build_review_add_command(
        reason="manual-root-override",
        repo=git_repo.name,
        branch="main",
        notes="outside repo invocation",
    )


def test_build_link_command_omits_root_by_default() -> None:
    """Link command builder should omit root argument by default."""
    command = _build_link_command("https://example.com/default-link")
    assert command == _dockyard_command("link", "https://example.com/default-link")


def test_build_links_command_omits_root_by_default() -> None:
    """Links command builder should omit root argument by default."""
    command = _build_links_command()
    assert command == _dockyard_command("links")


def test_build_link_and_links_commands_include_root_when_provided() -> None:
    """Link and links command builders should include root override."""
    root = Path("/tmp/demo-repo")
    link_command = _build_link_command("https://example.com/root-link", root=root)
    links_command = _build_links_command(root=root)

    assert link_command == _dockyard_command(
        "link",
        "https://example.com/root-link",
        "--root",
        str(root),
    )
    assert links_command == _dockyard_command("links", "--root", str(root))


def test_build_metadata_commands_in_repo_uses_default_link_url() -> None:
    """In-repo metadata command matrix should use default link URL command."""
    commands = _build_metadata_commands_in_repo(Path("/tmp/demo-repo"), "main")
    assert commands == [_build_link_command(NON_INTERFERENCE_LINK_URL)]


def test_build_metadata_commands_root_override_uses_root_scoped_commands() -> None:
    """Root-override metadata command matrix should include root-scoped commands."""
    root = Path("/tmp/demo-repo")
    commands = _build_metadata_commands_root_override(root, "main")
    assert commands == [
        _build_link_command(NON_INTERFERENCE_ROOT_OVERRIDE_LINK_URL, root=root),
        _build_links_command(root=root),
    ]


def _build_resume_read_path_scenarios(
    cases: Sequence[ResumeReadPathMeta],
) -> tuple[ResumeReadPathScenarioMeta, ...]:
    """Build resume-read non-interference scenarios from shared case metadata.

    Args:
        cases: Resume-read case metadata entries.

    Returns:
        Rendered case metadata rows for resume-read non-interference tests.
    """
    return tuple(
        ResumeReadPathScenarioMeta(
            case_id=case.case_id,
            marker_name=case.marker_name,
            objective=f"{case.scope_label} command safety baseline",
            decisions=f"Ensure {case.scope_label} read paths do not execute stored commands",
            next_step=f"Inspect {case.scope_label} resume output",
            commands_builder=case.commands_builder,
            run_cwd_kind=case.run_cwd_kind,
        )
        for case in cases
    )


def _build_metadata_scope_scenarios(cases: Sequence[MetadataScopeMeta]) -> tuple[MetadataScopeScenarioMeta, ...]:
    """Build metadata-scope non-interference scenarios from shared cases.

    Args:
        cases: Metadata-scope case metadata entries.

    Returns:
        Rendered case metadata rows for metadata-scope non-interference tests.
    """
    return tuple(
        MetadataScopeScenarioMeta(
            case_id=case.case_id,
            objective=f"{case.scope_label} mutation command baseline",
            decisions=f"Validate {case.scope_label} review/link non-interference",
            next_step=f"Run {case.scope_label} metadata commands",
            run_cwd_kind=case.run_cwd_kind,
            metadata_builder=case.metadata_builder,
            review_add_builder=case.review_add_builder,
        )
        for case in cases
    )


RESUME_READ_PATH_CASES: tuple[ResumeReadPathMeta, ...] = (
    ResumeReadPathMeta(
        "in_repo_default",
        "in-repo default",
        "dockyard_resume_should_not_run.txt",
        _build_resume_read_commands_in_repo,
        "repo",
    ),
    ResumeReadPathMeta(
        "alias_berth",
        "alias berth",
        "dockyard_alias_berth_resume_should_not_run.txt",
        _build_resume_read_commands_alias_berth,
        "tmp",
    ),
    ResumeReadPathMeta(
        "alias_trimmed_berth",
        "alias trimmed berth",
        "dockyard_alias_trimmed_resume_should_not_run.txt",
        _build_resume_read_commands_alias_trimmed_berth,
        "tmp",
    ),
    ResumeReadPathMeta(
        "primary_trimmed_berth",
        "primary trimmed berth",
        "dockyard_primary_trimmed_resume_should_not_run.txt",
        _build_resume_read_commands_primary_trimmed_berth,
        "tmp",
    ),
)
RESUME_READ_PATH_SCENARIOS: tuple[ResumeReadPathScenarioMeta, ...] = _build_resume_read_path_scenarios(
    RESUME_READ_PATH_CASES,
)
RESUME_READ_PATH_IDS: tuple[str, ...] = case_ids(RESUME_READ_PATH_SCENARIOS)

METADATA_SCOPE_CASES: tuple[MetadataScopeMeta, ...] = (
    MetadataScopeMeta(
        "in_repo",
        "in-repo",
        "repo",
        _build_metadata_commands_in_repo,
        _build_review_add_command_in_repo,
    ),
    MetadataScopeMeta(
        "root_override",
        "root override",
        "tmp",
        _build_metadata_commands_root_override,
        _build_review_add_command_root_override,
    ),
)
METADATA_SCOPE_SCENARIOS: tuple[MetadataScopeScenarioMeta, ...] = _build_metadata_scope_scenarios(
    METADATA_SCOPE_CASES,
)
METADATA_SCOPE_IDS: tuple[str, ...] = case_ids(METADATA_SCOPE_SCENARIOS)
SAVE_NO_PROMPT_SCENARIOS: tuple[SaveNoPromptScenarioMeta, ...] = _build_save_no_prompt_scenarios(
    SAVE_COMMAND_CASES,
)
SAVE_EDITOR_SCENARIOS: tuple[SaveEditorScenarioMeta, ...] = _build_save_editor_scenarios(
    SAVE_COMMAND_CASES,
)
SAVE_TEMPLATE_SCENARIOS: tuple[SaveTemplateScenarioMeta, ...] = _build_save_template_scenarios(
    SAVE_COMMAND_CASES,
)
SAVE_NO_PROMPT_IDS: tuple[str, ...] = case_ids(SAVE_NO_PROMPT_SCENARIOS)
SAVE_EDITOR_IDS: tuple[str, ...] = case_ids(SAVE_EDITOR_SCENARIOS)
SAVE_TEMPLATE_IDS: tuple[str, ...] = case_ids(SAVE_TEMPLATE_SCENARIOS)
RUN_NO_COMMAND_SCENARIOS: tuple[RunNoCommandScenarioMeta, ...] = _build_no_command_run_scope_scenarios(
    RUN_SCOPE_CASES_DEFAULT_BERTH_BRANCH,
)
RUN_NO_COMMAND_IDS: tuple[str, ...] = case_ids(RUN_NO_COMMAND_SCENARIOS)
RUN_OPT_IN_MUTATION_SCENARIOS: tuple[RunOptInMutationScenarioMeta, ...] = (
    _build_opt_in_mutation_run_scope_scenarios(RUN_SCOPE_CASES_DEFAULT_BRANCH_BERTH)
)
RUN_OPT_IN_MUTATION_IDS: tuple[str, ...] = case_ids(RUN_OPT_IN_MUTATION_SCENARIOS)


@pytest.mark.parametrize(
    "case",
    SAVE_NO_PROMPT_SCENARIOS,
    ids=SAVE_NO_PROMPT_IDS,
)
def test_save_no_prompt_flows_do_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    case: SaveNoPromptScenarioMeta,
) -> None:
    """No-prompt save flows should not alter tracked files or git index."""
    env = _dockyard_env(tmp_path)
    _assert_repo_clean(git_repo)
    _run(
        [
            "python3",
            "-m",
            "dockyard",
            case.command_name,
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            case.objective,
            "--decisions",
            case.decisions,
            "--next-step",
            case.next_step,
            "--risks",
            case.risks,
            "--command",
            case.resume_command,
            "--tests-run",
            "--tests-command",
            "pytest -q",
            "--build-ok",
            "--build-command",
            case.build_command,
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
        _dockyard_command("resume"),
        _dockyard_command("resume", "--json"),
        _dockyard_command("resume", "--handoff"),
        _dockyard_command("resume", "--branch", base_branch),
        _dockyard_command("r"),
        _dockyard_command("undock"),
        _dockyard_command("links"),
    ]


def _build_dashboard_read_commands(
    command_name: DashboardCommandName,
    *,
    include_non_json_tag_combo: bool = False,
) -> CommandMatrix:
    """Build ls/harbor read-only command matrix."""
    commands: CommandMatrix = []
    for variant in DASHBOARD_READ_VARIANTS:
        if variant.include_only_when_requested and not include_non_json_tag_combo:
            continue
        commands.append(_dockyard_command(command_name, *variant.args_suffix))
    return commands


def _render_search_args_suffix(
    args_suffix_template: tuple[str, ...],
    *,
    repo_name: str,
    base_branch: str,
) -> list[str]:
    """Resolve search command placeholder args for scenario rendering."""
    resolved_args: list[str] = []
    for arg in args_suffix_template:
        if arg == SEARCH_REPO_PLACEHOLDER:
            resolved_args.append(repo_name)
        elif arg == SEARCH_BRANCH_PLACEHOLDER:
            resolved_args.append(base_branch)
        else:
            resolved_args.append(arg)
    return resolved_args


def _build_search_read_command(
    command_name: SearchCommandName,
    *,
    args_suffix_template: tuple[str, ...],
    repo_name: str,
    base_branch: str,
) -> RunCommand:
    """Build a single search/f read command from template metadata."""
    return _dockyard_command(
        command_name,
        *_render_search_args_suffix(
            args_suffix_template,
            repo_name=repo_name,
            base_branch=base_branch,
        ),
    )


def _build_search_read_commands(command_name: SearchCommandName, repo_name: str, base_branch: str) -> CommandMatrix:
    """Build search/f read-only command matrix."""
    commands: CommandMatrix = [
        _build_search_read_command(
            command_name,
            args_suffix_template=variant.args_suffix_template,
            repo_name=repo_name,
            base_branch=base_branch,
        )
        for variant in SEARCH_READ_VARIANTS
    ]
    if command_name == "f":
        commands.extend(_build_search_alias_extra_read_commands(repo_name=repo_name, base_branch=base_branch))
    return commands


def _build_search_alias_extra_read_commands(*, repo_name: str, base_branch: str) -> CommandMatrix:
    """Build additional alias-only search read commands."""
    return [
        _build_search_read_command(
            "f",
            args_suffix_template=variant.args_suffix_template,
            repo_name=repo_name,
            base_branch=base_branch,
        )
        for variant in SEARCH_ALIAS_EXTRA_READ_VARIANTS
    ]


def _build_outside_repo_read_only_commands(repo_name: str, base_branch: str) -> CommandMatrix:
    """Build outside-repo read-only command matrix for non-interference checks."""
    return [
        *_resume_read_variants("resume", berth=repo_name, branch=base_branch),
        *_build_dashboard_read_commands("ls"),
        *_build_dashboard_read_commands("harbor", include_non_json_tag_combo=True),
        *_build_search_read_commands("search", repo_name, base_branch),
        *_build_search_read_commands("f", repo_name, base_branch),
        _dockyard_command("review"),
        _dockyard_command("review", "list"),
        _dockyard_command("review", "--all"),
        _dockyard_command("review", "list", "--all"),
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
    ("review_args", "case_id"),
    [
        (("review",), "review_default"),
        (("review", "list"), "review_list"),
        (("review", "--all"), "review_all"),
        (("review", "list", "--all"), "review_list_all"),
    ],
    ids=["review_default", "review_list", "review_all", "review_list_all"],
)
def test_empty_review_listing_commands_keep_repo_clean(
    git_repo: Path,
    tmp_path: Path,
    review_args: tuple[str, ...],
    case_id: str,
) -> None:
    """Empty review listing commands should stay read-only for project repos."""
    env = _dockyard_env(tmp_path)
    _assert_repo_clean(git_repo)

    output = _run(_dockyard_command(*review_args), cwd=tmp_path, env=env)
    assert "No review items." in output, case_id
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize(
    ("review_args", "include_resolved"),
    [
        (("review",), False),
        (("review", "list"), False),
        (("review", "--all"), True),
        (("review", "list", "--all"), True),
    ],
    ids=["review_default", "review_list", "review_all", "review_list_all"],
)
def test_review_listing_commands_with_items_keep_repo_clean(
    git_repo: Path,
    tmp_path: Path,
    review_args: tuple[str, ...],
    include_resolved: bool,
) -> None:
    """Review listing commands with items should remain read-only."""
    env = _dockyard_env(tmp_path)
    base_branch = _current_branch(git_repo)
    _assert_repo_clean(git_repo)

    _save_checkpoint(
        git_repo,
        env,
        objective="Review listing non-interference baseline",
        decisions="Create open/resolved review items for list coverage",
        next_step="Run review listing commands",
        risks="none",
        command="echo noop",
        extra_args=["--no-auto-review"],
    )
    _assert_repo_clean(git_repo)

    open_created = _run(
        _build_review_add_command(
            reason="non_interference_review_open",
            repo=git_repo.name,
            branch=base_branch,
        ),
        cwd=tmp_path,
        env=env,
    )
    open_match = re.search(r"rev_[a-f0-9]+", open_created)
    assert open_match is not None
    open_review_id = open_match.group(0)

    resolved_created = _run(
        _build_review_add_command(
            reason="non_interference_review_resolved",
            repo=git_repo.name,
            branch=base_branch,
        ),
        cwd=tmp_path,
        env=env,
    )
    resolved_match = re.search(r"rev_[a-f0-9]+", resolved_created)
    assert resolved_match is not None
    resolved_review_id = resolved_match.group(0)

    _run(_dockyard_command("review", "done", resolved_review_id), cwd=tmp_path, env=env)

    output = _run(_dockyard_command(*review_args), cwd=tmp_path, env=env)
    assert open_review_id in output
    assert (resolved_review_id in output) is include_resolved
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize(
    ("command_name", "args_suffix"),
    [
        ("search", ("definitely-no-match", "--json")),
        ("search", ("baseline", "--tag", "missing-tag", "--json")),
        ("search", ("baseline", "--repo", "missing-berth", "--json")),
        ("search", ("baseline", "--branch", "missing/branch", "--json")),
        (
            "search",
            ("baseline", "--tag", "baseline", "--repo", "missing-berth", "--branch", "missing/branch", "--json"),
        ),
        ("f", ("definitely-no-match", "--json")),
        ("f", ("baseline", "--tag", "missing-tag", "--json")),
        ("f", ("baseline", "--repo", "missing-berth", "--json")),
        ("f", ("baseline", "--branch", "missing/branch", "--json")),
        ("f", ("baseline", "--tag", "baseline", "--repo", "missing-berth", "--branch", "missing/branch", "--json")),
    ],
    ids=[
        "search_query_no_match_json",
        "search_tag_no_match_json",
        "search_repo_no_match_json",
        "search_branch_no_match_json",
        "search_tag_repo_branch_no_match_json",
        "f_query_no_match_json",
        "f_tag_no_match_json",
        "f_repo_no_match_json",
        "f_branch_no_match_json",
        "f_tag_repo_branch_no_match_json",
    ],
)
def test_search_json_no_match_read_paths_keep_repo_clean(
    git_repo: Path,
    tmp_path: Path,
    command_name: SearchCommandName,
    args_suffix: tuple[str, ...],
) -> None:
    """JSON search no-match paths should remain read-only for project repos."""
    env = _dockyard_env(tmp_path)

    _save_checkpoint(
        git_repo,
        env,
        objective="baseline objective for search no-match non-interference",
        decisions="seed checkpoint for no-match json path checks",
        next_step="run json search no-match commands",
        risks="none",
        command="echo noop",
        extra_args=["--tag", "baseline"],
    )

    _assert_repo_clean(git_repo)
    output = _run(_dockyard_command(command_name, *args_suffix), cwd=tmp_path, env=env)
    assert json.loads(output) == []
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize(
    ("command_name", "args_suffix"),
    [
        ("search", ("definitely-no-match",)),
        ("search", ("baseline", "--tag", "missing-tag")),
        ("search", ("baseline", "--tag", "missing-tag", "--limit", "1")),
        ("search", ("baseline", "--repo", "missing-berth")),
        ("search", ("baseline", "--branch", "missing/branch")),
        ("search", ("baseline", "--repo", "missing-berth", "--branch", "missing/branch", "--limit", "1")),
        (
            "search",
            ("baseline", "--tag", "baseline", "--repo", "missing-berth", "--branch", "missing/branch"),
        ),
        (
            "search",
            (
                "baseline",
                "--tag",
                "baseline",
                "--repo",
                "missing-berth",
                "--branch",
                "missing/branch",
                "--limit",
                "1",
            ),
        ),
        ("f", ("definitely-no-match",)),
        ("f", ("baseline", "--tag", "missing-tag")),
        ("f", ("baseline", "--tag", "missing-tag", "--limit", "1")),
        ("f", ("baseline", "--repo", "missing-berth")),
        ("f", ("baseline", "--branch", "missing/branch")),
        ("f", ("baseline", "--repo", "missing-berth", "--branch", "missing/branch", "--limit", "1")),
        (
            "f",
            ("baseline", "--tag", "baseline", "--repo", "missing-berth", "--branch", "missing/branch"),
        ),
        (
            "f",
            (
                "baseline",
                "--tag",
                "baseline",
                "--repo",
                "missing-berth",
                "--branch",
                "missing/branch",
                "--limit",
                "1",
            ),
        ),
    ],
    ids=[
        "search_query_no_match_table",
        "search_filtered_no_match_table",
        "search_filtered_limit_no_match_table",
        "search_repo_no_match_table",
        "search_branch_no_match_table",
        "search_repo_branch_limit_no_match_table",
        "search_tag_repo_branch_no_match_table",
        "search_tag_repo_branch_limit_no_match_table",
        "f_query_no_match_table",
        "f_filtered_no_match_table",
        "f_filtered_limit_no_match_table",
        "f_repo_no_match_table",
        "f_branch_no_match_table",
        "f_repo_branch_limit_no_match_table",
        "f_tag_repo_branch_no_match_table",
        "f_tag_repo_branch_limit_no_match_table",
    ],
)
def test_search_no_match_read_paths_keep_repo_clean(
    git_repo: Path,
    tmp_path: Path,
    command_name: SearchCommandName,
    args_suffix: tuple[str, ...],
) -> None:
    """Table search no-match paths should be informative and non-mutating."""
    env = _dockyard_env(tmp_path)

    _save_checkpoint(
        git_repo,
        env,
        objective="baseline objective for search no-match table non-interference",
        decisions="seed checkpoint for no-match table path checks",
        next_step="run table search no-match commands",
        risks="none",
        command="echo noop",
        extra_args=["--tag", "baseline"],
    )

    _assert_repo_clean(git_repo)
    output = _run(_dockyard_command(command_name, *args_suffix), cwd=tmp_path, env=env)
    assert "No checkpoint matches found." in output
    assert "Traceback" not in output
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["search", "f"])
@pytest.mark.parametrize(
    "query",
    [
        "risktoken",
        "nexttoken",
        "decisiontoken",
        "objectivetoken",
    ],
    ids=["risks", "next_steps", "decisions", "objective"],
)
def test_search_json_snippet_match_paths_keep_repo_clean(
    git_repo: Path,
    tmp_path: Path,
    command_name: SearchCommandName,
    query: str,
) -> None:
    """Snippet-producing search/read paths should remain non-mutating."""
    env = _dockyard_env(tmp_path)

    _save_checkpoint(
        git_repo,
        env,
        objective="objectivetoken objective for search snippet non-interference",
        decisions="decisiontoken decisions for search snippet non-interference",
        next_step="Run nexttoken validation for search snippet non-interference",
        risks="Requires risktoken validation for search snippet non-interference",
        command="echo noop",
        extra_args=["--tag", "baseline"],
    )

    _assert_repo_clean(git_repo)
    rows = json.loads(_run(_dockyard_command(command_name, query, "--json"), cwd=tmp_path, env=env))
    assert len(rows) == 1
    assert query in rows[0]["snippet"].lower()
    assert rows[0]["objective"]
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["search", "f"])
def test_search_json_multiline_snippet_match_paths_keep_repo_clean(
    git_repo: Path,
    tmp_path: Path,
    command_name: SearchCommandName,
) -> None:
    """Multiline snippet normalization search paths should remain non-mutating."""
    env = _dockyard_env(tmp_path)

    _save_checkpoint(
        git_repo,
        env,
        objective="multiline snippet non-interference baseline",
        decisions="multiline snippet read path should not mutate repo",
        next_step="Run multiline search read path",
        risks="line1\nmultilinetoken line2\nline3",
        command="echo noop",
        extra_args=["--tag", "baseline"],
    )

    _assert_repo_clean(git_repo)
    rows = json.loads(
        _run(
            _dockyard_command(command_name, "multilinetoken", "--json"),
            cwd=tmp_path,
            env=env,
        )
    )
    assert len(rows) == 1
    assert rows[0]["snippet"] == "line1 multilinetoken line2 line3"
    assert "\n" not in rows[0]["snippet"]
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["search", "f"])
def test_search_json_unicode_snippet_match_paths_keep_repo_clean(
    git_repo: Path,
    tmp_path: Path,
    command_name: SearchCommandName,
) -> None:
    """Unicode snippet search read paths should remain non-mutating."""
    env = _dockyard_env(tmp_path)

    _save_checkpoint(
        git_repo,
        env,
        objective="unicode snippet non-interference baseline",
        decisions="unicode snippet read path should not mutate repo",
        next_step="Run unicode search read path",
        risks="Requires façade validation before merge",
        command="echo noop",
        extra_args=["--tag", "baseline"],
    )

    _assert_repo_clean(git_repo)
    rows = json.loads(
        _run(
            _dockyard_command(command_name, "façade", "--json"),
            cwd=tmp_path,
            env=env,
        )
    )
    assert len(rows) == 1
    assert "façade" in rows[0]["snippet"]
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["search", "f"])
def test_search_json_bounded_snippet_match_paths_keep_repo_clean(
    git_repo: Path,
    tmp_path: Path,
    command_name: SearchCommandName,
) -> None:
    """Bounded snippet search read paths should remain non-mutating."""
    env = _dockyard_env(tmp_path)

    _save_checkpoint(
        git_repo,
        env,
        objective="bounded snippet non-interference baseline",
        decisions="bounded snippet read path should not mutate repo",
        next_step="Run bounded snippet read path",
        risks="boundtoken " + ("x" * 400),
        command="echo noop",
        extra_args=["--tag", "baseline"],
    )

    _assert_repo_clean(git_repo)
    rows = json.loads(
        _run(
            _dockyard_command(command_name, "boundtoken", "--json"),
            cwd=tmp_path,
            env=env,
        )
    )
    assert len(rows) == 1
    assert "boundtoken" in rows[0]["snippet"]
    assert len(rows[0]["snippet"]) <= 140
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize(
    ("command_args", "run_cwd_kind"),
    [
        (("resume", "--json"), "repo"),
        (("ls", "--json"), "tmp"),
        (("harbor", "--json"), "tmp"),
        (("--json",), "tmp"),
        (("search", "jsonreadtoken", "--json"), "tmp"),
        (("f", "jsonreadtoken", "--json"), "tmp"),
    ],
    ids=["resume_json", "ls_json", "harbor_json", "callback_json", "search_json", "f_json"],
)
def test_json_read_outputs_are_parseable_ansi_free_and_non_mutating(
    git_repo: Path,
    tmp_path: Path,
    command_args: tuple[str, ...],
    run_cwd_kind: RunCwdKind,
) -> None:
    """JSON read outputs should be parseable/ANSI-free and remain non-mutating."""
    env = _dockyard_env(tmp_path)

    _save_checkpoint(
        git_repo,
        env,
        objective="jsonreadtoken objective for non-interference json read checks",
        decisions="ensure json read outputs remain parseable and ansi-free",
        next_step="run json read commands",
        risks="none",
        command="echo noop",
        extra_args=["--no-auto-review"],
    )

    _assert_repo_clean(git_repo)
    output = _run(
        _dockyard_command(*command_args),
        cwd=git_repo if run_cwd_kind == "repo" else tmp_path,
        env=env,
    )
    assert "\x1b[" not in output
    json.loads(output)
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize(
    ("command_args", "run_cwd_kind"),
    [
        (("resume", "--json"), "repo"),
        (("ls", "--json"), "tmp"),
        (("harbor", "--json"), "tmp"),
        (("--json",), "tmp"),
        (("search", "façade", "--json"), "tmp"),
        (("f", "façade", "--json"), "tmp"),
    ],
    ids=[
        "resume_json_unicode",
        "ls_json_unicode",
        "harbor_json_unicode",
        "callback_json_unicode",
        "search_json_unicode",
        "f_json_unicode",
    ],
)
def test_json_read_outputs_preserve_unicode_and_remain_non_mutating(
    git_repo: Path,
    tmp_path: Path,
    command_args: tuple[str, ...],
    run_cwd_kind: RunCwdKind,
) -> None:
    """JSON read outputs should preserve unicode glyphs and remain non-mutating."""
    env = _dockyard_env(tmp_path)

    _save_checkpoint(
        git_repo,
        env,
        objective="Unicode façade objective for non-interference json checks",
        decisions="Ensure naïve unicode text is preserved in JSON outputs",
        next_step="run unicode json read commands",
        risks="none",
        command="echo noop",
        extra_args=["--no-auto-review"],
    )

    _assert_repo_clean(git_repo)
    output = _run(
        _dockyard_command(*command_args),
        cwd=git_repo if run_cwd_kind == "repo" else tmp_path,
        env=env,
    )
    assert "façade" in output
    assert "\\u00e7" not in output
    json.loads(output)
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize(
    ("command_args", "run_cwd_kind", "expected_fragment"),
    [
        (("resume", "--json"), "repo", "risklong"),
        (("ls", "--json"), "tmp", "longtoken"),
        (("harbor", "--json"), "tmp", "longtoken"),
        (("--json",), "tmp", "longtoken"),
        (("search", "longtoken", "--json"), "tmp", "longtoken"),
        (("f", "longtoken", "--json"), "tmp", "longtoken"),
    ],
    ids=[
        "resume_json_long_text",
        "ls_json_long_text",
        "harbor_json_long_text",
        "callback_json_long_text",
        "search_json_long_text",
        "f_json_long_text",
    ],
)
def test_json_read_outputs_handle_long_text_and_remain_non_mutating(
    git_repo: Path,
    tmp_path: Path,
    command_args: tuple[str, ...],
    run_cwd_kind: RunCwdKind,
    expected_fragment: str,
) -> None:
    """Long-text JSON read outputs should be parseable and non-mutating."""
    env = _dockyard_env(tmp_path)
    long_objective = "longtoken " + ("x" * 500)
    long_risks = "risklong " + ("y" * 500)

    _save_checkpoint(
        git_repo,
        env,
        objective=long_objective,
        decisions="long text json non-interference",
        next_step="run long text json read commands",
        risks=long_risks,
        command="echo noop",
        extra_args=["--no-auto-review"],
    )

    _assert_repo_clean(git_repo)
    output = _run(
        _dockyard_command(*command_args),
        cwd=git_repo if run_cwd_kind == "repo" else tmp_path,
        env=env,
    )
    assert expected_fragment in output
    assert "\x1b[" not in output
    json.loads(output)
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize(
    ("command_args", "run_cwd_kind", "expect_resume_payload"),
    [
        (("resume", "--json"), "repo", True),
        (("ls", "--json"), "tmp", False),
        (("harbor", "--json"), "tmp", False),
        (("--json",), "tmp", False),
    ],
    ids=[
        "resume_json_multiline",
        "ls_json_multiline",
        "harbor_json_multiline",
        "callback_json_multiline",
    ],
)
def test_json_read_outputs_preserve_multiline_text_and_remain_non_mutating(
    git_repo: Path,
    tmp_path: Path,
    command_args: tuple[str, ...],
    run_cwd_kind: RunCwdKind,
    expect_resume_payload: bool,
) -> None:
    """Multiline JSON read outputs should remain parseable and non-mutating."""
    env = _dockyard_env(tmp_path)
    multiline_objective = "line one\nline two"
    multiline_decisions = "decision one\ndecision two\ndecision three"

    _save_checkpoint(
        git_repo,
        env,
        objective=multiline_objective,
        decisions=multiline_decisions,
        next_step="run multiline json read commands",
        risks="none",
        command="echo noop",
        extra_args=["--no-auto-review"],
    )

    _assert_repo_clean(git_repo)
    output = _run(
        _dockyard_command(*command_args),
        cwd=git_repo if run_cwd_kind == "repo" else tmp_path,
        env=env,
    )
    payload = json.loads(output)
    if expect_resume_payload:
        assert payload["decisions"] == multiline_decisions
    else:
        assert any(row.get("objective") == multiline_objective for row in payload)
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize(
    "command_args",
    [
        ("ls", "--json"),
        ("harbor", "--json"),
        ("--json",),
        ("search", "definitely-no-match", "--json"),
        ("f", "definitely-no-match", "--json"),
    ],
    ids=["ls_empty_json", "harbor_empty_json", "callback_empty_json", "search_empty_json", "f_empty_json"],
)
def test_json_empty_state_outputs_are_parseable_ansi_free_and_non_mutating(
    git_repo: Path,
    tmp_path: Path,
    command_args: tuple[str, ...],
) -> None:
    """Empty-state JSON outputs should be parseable, ANSI-free, and non-mutating."""
    env = _dockyard_env(tmp_path)

    _assert_repo_clean(git_repo)
    output = _run(_dockyard_command(*command_args), cwd=tmp_path, env=env)
    assert "\x1b[" not in output
    assert json.loads(output) == []
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize(
    ("dashboard_args", "dashboard_label"),
    [
        (("ls", "--json"), "ls"),
        (("harbor", "--json"), "harbor"),
        (("--json",), "callback"),
    ],
    ids=["ls", "harbor", "callback"],
)
def test_review_lifecycle_status_recompute_dashboard_reads_keep_repo_clean(
    git_repo: Path,
    tmp_path: Path,
    dashboard_args: tuple[str, ...],
    dashboard_label: str,
) -> None:
    """Review lifecycle dashboard-read status checks should remain non-mutating."""
    env = _dockyard_env(tmp_path)

    objective = f"non-interference status recompute ({dashboard_label})"
    _save_checkpoint(
        git_repo,
        env,
        objective=objective,
        decisions="verify status recompute reads are non-mutating",
        next_step="run dashboard status reads",
        risks="none",
        command="echo status",
    )

    def _status_for_objective() -> str:
        rows = json.loads(_run(_dockyard_command(*dashboard_args), cwd=tmp_path, env=env))
        target = next(row for row in rows if row.get("objective") == objective)
        return str(target["status"])

    _assert_repo_clean(git_repo)
    assert _status_for_objective() == "green"
    _assert_repo_clean(git_repo)

    added = _run(
        _dockyard_command(
            "review",
            "add",
            "--reason",
            f"critical_non_interference_{dashboard_label}",
            "--severity",
            "high",
        ),
        cwd=git_repo,
        env=env,
    )
    review_match = re.search(r"rev_[a-f0-9]+", added)
    assert review_match is not None
    review_id = review_match.group(0)

    _assert_repo_clean(git_repo)
    assert _status_for_objective() == "red"
    _assert_repo_clean(git_repo)

    _run(_dockyard_command("review", "done", review_id), cwd=tmp_path, env=env)
    _assert_repo_clean(git_repo)
    assert _status_for_objective() == "green"
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["search", "f"])
def test_search_json_objective_first_snippet_paths_keep_repo_clean(
    git_repo: Path,
    tmp_path: Path,
    command_name: SearchCommandName,
) -> None:
    """Objective-first snippet read paths should remain non-mutating."""
    env = _dockyard_env(tmp_path)

    _save_checkpoint(
        git_repo,
        env,
        objective="prioritytoken objective text",
        decisions="prioritytoken decisions text",
        next_step="prioritytoken next step text",
        risks="prioritytoken risks text",
        command="echo noop",
        extra_args=["--tag", "baseline"],
    )

    _assert_repo_clean(git_repo)
    rows = json.loads(
        _run(
            _dockyard_command(command_name, "prioritytoken", "--json"),
            cwd=tmp_path,
            env=env,
        )
    )
    assert len(rows) == 1
    assert rows[0]["snippet"] == "prioritytoken objective text"
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["search", "f"])
def test_search_json_objective_whitespace_snippet_paths_keep_repo_clean(
    git_repo: Path,
    tmp_path: Path,
    command_name: SearchCommandName,
) -> None:
    """Objective whitespace snippet normalization paths should stay non-mutating."""
    env = _dockyard_env(tmp_path)

    _save_checkpoint(
        git_repo,
        env,
        objective="token   with\t\tspace",
        decisions="objective whitespace snippet should not mutate repo",
        next_step="Run objective whitespace snippet read path",
        risks="none",
        command="echo noop",
        extra_args=["--tag", "baseline"],
    )

    _assert_repo_clean(git_repo)
    rows = json.loads(
        _run(
            _dockyard_command(command_name, "token", "--json"),
            cwd=tmp_path,
            env=env,
        )
    )
    assert len(rows) == 1
    assert rows[0]["snippet"] == "token with space"
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize(
    "case",
    RESUME_READ_PATH_SCENARIOS,
    ids=RESUME_READ_PATH_IDS,
)
def test_resume_read_paths_do_not_execute_saved_commands(
    git_repo: Path,
    tmp_path: Path,
    case: ResumeReadPathScenarioMeta,
) -> None:
    """Resume read-only path variants must never execute stored commands."""
    _assert_resume_read_paths_do_not_execute_saved_commands(
        git_repo,
        tmp_path,
        marker_name=case.marker_name,
        objective=case.objective,
        decisions=case.decisions,
        next_step=case.next_step,
        commands=case.commands_builder(git_repo),
        run_cwd=_resolve_run_cwd(git_repo, tmp_path, case.run_cwd_kind),
    )


@pytest.mark.parametrize(
    "case",
    METADATA_SCOPE_SCENARIOS,
    ids=METADATA_SCOPE_IDS,
)
def test_review_and_link_commands_do_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    case: MetadataScopeScenarioMeta,
) -> None:
    """Review/link metadata paths must not alter repository tree/index."""
    base_branch = _current_branch(git_repo)
    _assert_review_link_commands_do_not_modify_repo(
        git_repo,
        tmp_path,
        objective=case.objective,
        decisions=case.decisions,
        next_step=case.next_step,
        run_cwd=_resolve_run_cwd(git_repo, tmp_path, case.run_cwd_kind),
        metadata_commands=case.metadata_builder(git_repo, base_branch),
        review_add_command=case.review_add_builder(git_repo, base_branch),
    )


@pytest.mark.parametrize(
    "case",
    SAVE_EDITOR_SCENARIOS,
    ids=SAVE_EDITOR_IDS,
)
def test_save_editor_flows_do_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    case: SaveEditorScenarioMeta,
) -> None:
    """Save/editor flows should not alter project working tree/index."""
    env = _dockyard_env(tmp_path)
    _configure_editor(
        env=env,
        tmp_path=tmp_path,
        script_name=case.script_name,
        decisions_text=case.decisions_text,
    )

    _assert_repo_clean(git_repo)
    _run(
        [
            "python3",
            "-m",
            "dockyard",
            case.command_name,
            "--root",
            str(git_repo),
            "--editor",
            "--no-prompt",
            "--objective",
            case.objective,
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
    "case",
    SAVE_TEMPLATE_SCENARIOS,
    ids=SAVE_TEMPLATE_IDS,
)
def test_save_template_flows_do_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    case: SaveTemplateScenarioMeta,
) -> None:
    """Save/template flows should not alter project working tree/index."""
    env = _dockyard_env(tmp_path)
    template_path = tmp_path / case.template_name
    _write_non_interference_template(template_path=template_path, objective=case.objective)

    _assert_repo_clean(git_repo)
    _run(
        [
            "python3",
            "-m",
            "dockyard",
            case.command_name,
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


def test_save_with_blank_origin_remote_does_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Save should remain read-only when origin remote URL is blank."""
    env = _dockyard_env(tmp_path)

    _run(
        ["git", "config", "remote.origin.url", ""],
        cwd=git_repo,
        env=env,
    )
    _assert_repo_clean(git_repo)

    _run(
        _dockyard_command(
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "blank origin remote non-interference",
            "--decisions",
            "verify save remains read-only",
            "--next-step",
            "run save with blank origin remote",
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
        ),
        cwd=git_repo,
        env=env,
    )
    _assert_repo_clean(git_repo)


def test_save_with_non_origin_remote_fallback_does_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Save should remain read-only when falling back to non-origin remotes."""
    env = _dockyard_env(tmp_path)

    _run(
        ["git", "remote", "remove", "origin"],
        cwd=git_repo,
        env=env,
    )
    _run(
        ["git", "remote", "add", "upstream", "https://example.com/team/upstream.git"],
        cwd=git_repo,
        env=env,
    )
    _assert_repo_clean(git_repo)

    _run(
        _dockyard_command(
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "non-origin remote fallback non-interference",
            "--decisions",
            "verify save remains read-only with fallback remote",
            "--next-step",
            "run save with non-origin fallback remote",
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
        ),
        cwd=git_repo,
        env=env,
    )
    _assert_repo_clean(git_repo)


def test_save_with_case_collision_remote_fallback_does_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Save should remain read-only with case-colliding fallback remotes."""
    env = _dockyard_env(tmp_path)

    _run(
        ["git", "remote", "remove", "origin"],
        cwd=git_repo,
        env=env,
    )
    _run(
        ["git", "remote", "add", "alpha", "https://example.com/team/alpha-lower.git"],
        cwd=git_repo,
        env=env,
    )
    _run(
        ["git", "remote", "add", "Alpha", "https://example.com/team/alpha-upper.git"],
        cwd=git_repo,
        env=env,
    )
    _assert_repo_clean(git_repo)

    _run(
        _dockyard_command(
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "case-collision fallback non-interference",
            "--decisions",
            "verify save remains read-only with case-colliding remotes",
            "--next-step",
            "run save with case-collision fallback remotes",
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
        ),
        cwd=git_repo,
        env=env,
    )
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["save", "s", "dock"])
def test_save_aliases_with_blank_origin_remote_do_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Save aliases should remain read-only when origin remote URL is blank."""
    env = _dockyard_env(tmp_path)

    _run(
        ["git", "config", "remote.origin.url", ""],
        cwd=git_repo,
        env=env,
    )
    _assert_repo_clean(git_repo)

    _run(
        _dockyard_command(
            command_name,
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"{command_name} blank origin non-interference",
            "--decisions",
            "verify alias save remains read-only",
            "--next-step",
            "run alias save with blank origin",
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
        ),
        cwd=git_repo,
        env=env,
    )
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["save", "s", "dock"])
def test_save_aliases_with_non_origin_remote_fallback_do_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Save aliases should remain read-only with non-origin remote fallback."""
    env = _dockyard_env(tmp_path)

    _run(
        ["git", "remote", "remove", "origin"],
        cwd=git_repo,
        env=env,
    )
    _run(
        ["git", "remote", "add", "upstream", "https://example.com/team/upstream.git"],
        cwd=git_repo,
        env=env,
    )
    _assert_repo_clean(git_repo)

    _run(
        _dockyard_command(
            command_name,
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"{command_name} non-origin fallback non-interference",
            "--decisions",
            "verify alias save remains read-only with fallback remote",
            "--next-step",
            "run alias save with non-origin fallback remote",
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
        ),
        cwd=git_repo,
        env=env,
    )
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["save", "s", "dock"])
def test_review_open_after_save_alias_with_linked_checkpoint_keeps_repo_clean(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Save-alias + linked review-open flow should not mutate repo state."""
    env = _dockyard_env(tmp_path)
    _assert_repo_clean(git_repo)

    _run(
        _dockyard_command(
            command_name,
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"{command_name} auto-review non-interference",
            "--decisions",
            "create checkpoint and inspect review open behavior",
            "--next-step",
            "open linked review",
            "--risks",
            "none",
            "--command",
            "echo review",
            "--tests-run",
            "--tests-command",
            "pytest -q",
            "--build-ok",
            "--build-command",
            "echo build",
            "--lint-fail",
            "--smoke-fail",
            "--no-auto-review",
        ),
        cwd=git_repo,
        env=env,
    )
    _assert_repo_clean(git_repo)

    db_path = Path(env["DOCKYARD_HOME"]) / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT id FROM checkpoints ORDER BY created_at DESC LIMIT 1").fetchone()
    conn.close()
    assert row is not None
    checkpoint_id = row[0]
    branch = _current_branch(git_repo)
    created = _run(
        _dockyard_command(
            "review",
            "add",
            "--reason",
            "non_interference_alias_review_open",
            "--severity",
            "med",
            "--checkpoint-id",
            checkpoint_id,
            "--repo",
            git_repo.name,
            "--branch",
            branch,
        ),
        cwd=tmp_path,
        env=env,
    )
    review_match = re.search(r"rev_[a-f0-9]+", created)
    assert review_match is not None
    review_id = review_match.group(0)

    opened = _run(_dockyard_command("review", "open", review_id), cwd=tmp_path, env=env)
    assert "created_at:" in opened
    assert f"checkpoint_id: {checkpoint_id}" in opened
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["save", "s", "dock"])
def test_review_open_after_save_alias_with_missing_checkpoint_keeps_repo_clean(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Save-alias + missing-checkpoint review-open flow should not mutate repo."""
    env = _dockyard_env(tmp_path)
    _assert_repo_clean(git_repo)

    _run(
        _dockyard_command(
            command_name,
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"{command_name} missing-checkpoint review-open non-interference",
            "--decisions",
            "create checkpoint then open missing-checkpoint review",
            "--next-step",
            "open missing-checkpoint linked review",
            "--risks",
            "none",
            "--command",
            "echo review",
            "--tests-run",
            "--tests-command",
            "pytest -q",
            "--build-ok",
            "--build-command",
            "echo build",
            "--lint-fail",
            "--smoke-fail",
            "--no-auto-review",
        ),
        cwd=git_repo,
        env=env,
    )
    _assert_repo_clean(git_repo)

    branch = _current_branch(git_repo)
    created = _run(
        _dockyard_command(
            "review",
            "add",
            "--reason",
            "non_interference_alias_missing_checkpoint",
            "--severity",
            "low",
            "--checkpoint-id",
            "cp_missing_123",
            "--repo",
            git_repo.name,
            "--branch",
            branch,
        ),
        cwd=tmp_path,
        env=env,
    )
    review_match = re.search(r"rev_[a-f0-9]+", created)
    assert review_match is not None
    review_id = review_match.group(0)

    opened = _run(_dockyard_command("review", "open", review_id), cwd=tmp_path, env=env)
    assert "created_at:" in opened
    assert "checkpoint_id: cp_missing_123" in opened
    assert "status: missing from index" in opened
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["save", "s", "dock"])
def test_review_open_after_save_alias_with_file_and_notes_keeps_repo_clean(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Save-alias + file/notes review-open flow should not mutate repo."""
    env = _dockyard_env(tmp_path)
    _assert_repo_clean(git_repo)

    _run(
        _dockyard_command(
            command_name,
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"{command_name} file+notes review-open non-interference",
            "--decisions",
            "create checkpoint then open file/notes review metadata",
            "--next-step",
            "open file/notes review metadata",
            "--risks",
            "none",
            "--command",
            "echo review",
            "--tests-run",
            "--tests-command",
            "pytest -q",
            "--build-ok",
            "--build-command",
            "echo build",
            "--lint-fail",
            "--smoke-fail",
            "--no-auto-review",
        ),
        cwd=git_repo,
        env=env,
    )
    _assert_repo_clean(git_repo)

    branch = _current_branch(git_repo)
    created = _run(
        _dockyard_command(
            "review",
            "add",
            "--reason",
            "non_interference_alias_file_notes",
            "--severity",
            "low",
            "--file",
            "src/a.py",
            "--file",
            "src/b.py",
            "--notes",
            "needs careful review",
            "--repo",
            git_repo.name,
            "--branch",
            branch,
        ),
        cwd=tmp_path,
        env=env,
    )
    review_match = re.search(r"rev_[a-f0-9]+", created)
    assert review_match is not None
    review_id = review_match.group(0)

    opened = _run(_dockyard_command("review", "open", review_id), cwd=tmp_path, env=env)
    assert "files: src/a.py, src/b.py" in opened
    assert "notes: needs careful review" in opened
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["save", "s", "dock"])
def test_review_open_after_save_alias_with_scalar_files_payload_keeps_repo_clean(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Save-alias + scalar-files review-open flow should not mutate repo."""
    env = _dockyard_env(tmp_path)
    dock_home = Path(env["DOCKYARD_HOME"])
    _assert_repo_clean(git_repo)

    _run(
        _dockyard_command(
            command_name,
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"{command_name} scalar-files review-open non-interference",
            "--decisions",
            "create checkpoint then open scalar-files review metadata",
            "--next-step",
            "open scalar-files review metadata",
            "--risks",
            "none",
            "--command",
            "echo review",
            "--tests-run",
            "--tests-command",
            "pytest -q",
            "--build-ok",
            "--build-command",
            "echo build",
            "--lint-fail",
            "--smoke-fail",
            "--no-auto-review",
        ),
        cwd=git_repo,
        env=env,
    )
    _assert_repo_clean(git_repo)

    branch = _current_branch(git_repo)
    created = _run(
        _dockyard_command(
            "review",
            "add",
            "--reason",
            "non_interference_alias_scalar_files",
            "--severity",
            "low",
            "--repo",
            git_repo.name,
            "--branch",
            branch,
        ),
        cwd=tmp_path,
        env=env,
    )
    review_match = re.search(r"rev_[a-f0-9]+", created)
    assert review_match is not None
    review_id = review_match.group(0)

    db_path = dock_home / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE review_items SET files_json = ? WHERE id = ?",
        (json.dumps("src/scalar.py"), review_id),
    )
    conn.commit()
    conn.close()

    opened = _run(_dockyard_command("review", "open", review_id), cwd=tmp_path, env=env)
    assert "files: src/scalar.py" in opened
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["save", "s", "dock"])
def test_review_open_after_save_alias_with_blank_metadata_keeps_repo_clean(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Save-alias + blank-metadata review-open flow should not mutate repo."""
    env = _dockyard_env(tmp_path)
    dock_home = Path(env["DOCKYARD_HOME"])
    _assert_repo_clean(git_repo)

    _run(
        _dockyard_command(
            command_name,
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"{command_name} blank-metadata review-open non-interference",
            "--decisions",
            "create checkpoint then open blank-metadata review",
            "--next-step",
            "open blank-metadata review metadata",
            "--risks",
            "none",
            "--command",
            "echo review",
            "--tests-run",
            "--tests-command",
            "pytest -q",
            "--build-ok",
            "--build-command",
            "echo build",
            "--lint-fail",
            "--smoke-fail",
            "--no-auto-review",
        ),
        cwd=git_repo,
        env=env,
    )
    _assert_repo_clean(git_repo)

    branch = _current_branch(git_repo)
    created = _run(
        _dockyard_command(
            "review",
            "add",
            "--reason",
            "non_interference_alias_blank_metadata",
            "--severity",
            "med",
            "--repo",
            git_repo.name,
            "--branch",
            branch,
        ),
        cwd=tmp_path,
        env=env,
    )
    review_match = re.search(r"rev_[a-f0-9]+", created)
    assert review_match is not None
    review_id = review_match.group(0)

    db_path = dock_home / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        (
            "UPDATE review_items "
            "SET repo_id = ?, branch = ?, created_at = ?, severity = ?, status = ?, reason = ? "
            "WHERE id = ?"
        ),
        ("   ", "   ", "   ", "   ", "   ", "   ", review_id),
    )
    conn.commit()
    conn.close()

    opened = _run(_dockyard_command("review", "open", review_id), cwd=tmp_path, env=env)
    assert "created_at: (unknown)" in opened
    assert "checkpoint_id: (none)" in opened
    assert "reason: (none)" in opened
    assert "status: (unknown)" in opened
    _assert_repo_clean(git_repo)


def test_bare_dock_command_does_not_modify_repo(git_repo: Path, tmp_path: Path) -> None:
    """Bare dock command (harbor view) should not alter repo state."""
    env = _dockyard_env(tmp_path)

    _assert_repo_clean(git_repo)

    _run(_dockyard_command(), cwd=git_repo, env=env)

    _assert_repo_clean(git_repo)


@pytest.mark.parametrize(
    "args",
    [
        (),
        ("--json",),
        ("--limit", "1"),
        ("--stale", "0"),
        ("--json", "--stale", "0", "--limit", "1"),
        ("--tag", "missing-tag"),
        ("--tag", "missing-tag", "--json"),
        ("--tag", "missing-tag", "--limit", "1"),
        ("--tag", "missing-tag", "--limit", "1", "--json"),
    ],
    ids=[
        "default",
        "json",
        "limit",
        "stale_zero",
        "json_stale_limit",
        "missing_tag",
        "missing_tag_json",
        "missing_tag_limit",
        "missing_tag_limit_json",
    ],
)
def test_bare_dock_command_in_repo_empty_store_read_variants_do_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    args: tuple[str, ...],
) -> None:
    """Bare dock read variants should stay non-mutating in empty repo context."""
    env = _dockyard_env(tmp_path)

    _assert_repo_clean(git_repo)

    _run(_dockyard_command(*args), cwd=git_repo, env=env)

    _assert_repo_clean(git_repo)


def test_bare_dock_command_with_ls_flags_does_not_modify_repo(git_repo: Path, tmp_path: Path) -> None:
    """Bare dock ls-style flags should remain read-only for project repos."""
    env = _dockyard_env(tmp_path)

    _assert_repo_clean(git_repo)

    _run(_dockyard_command("--json", "--limit", "1"), cwd=git_repo, env=env)

    _assert_repo_clean(git_repo)


def test_bare_dock_command_with_tag_stale_flags_does_not_modify_repo(git_repo: Path, tmp_path: Path) -> None:
    """Bare dock tag/stale filter flags should remain read-only."""
    env = _dockyard_env(tmp_path)

    _assert_repo_clean(git_repo)

    _run(
        _dockyard_command("--json", "--tag", "baseline", "--stale", "0", "--limit", "1"),
        cwd=git_repo,
        env=env,
    )

    _assert_repo_clean(git_repo)


@pytest.mark.parametrize(
    "args",
    [
        ("--tag", "baseline", "--stale", "0"),
        ("--tag", "baseline", "--stale", "0", "--limit", "1"),
        ("--tag", "missing-tag", "--stale", "0"),
        ("--tag", "missing-tag", "--stale", "0", "--limit", "1"),
        ("--json", "--tag", "baseline", "--stale", "0"),
        ("--json", "--tag", "missing-tag", "--stale", "0"),
        ("--json", "--tag", "baseline", "--stale", "0", "--limit", "1"),
        ("--json", "--tag", "missing-tag", "--stale", "0", "--limit", "1"),
    ],
    ids=[
        "table_tag_stale",
        "table_tag_stale_limit",
        "table_missing_tag_stale",
        "table_missing_tag_stale_limit",
        "json_tag_stale",
        "json_missing_tag_stale",
        "json_tag_stale_limit",
        "json_missing_tag_stale_limit",
    ],
)
def test_bare_dock_command_in_repo_seeded_filter_variants_do_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    args: tuple[str, ...],
) -> None:
    """Bare dock seeded tag/stale variants should remain read-only in repo cwd."""
    env = _dockyard_env(tmp_path)

    _save_checkpoint(
        git_repo,
        env,
        objective="bare dock in-repo seeded filter baseline",
        decisions="seed checkpoint for in-repo callback filter matrix",
        next_step="run bare dock in-repo filter variants",
        risks="none",
        command="echo callback in-repo seeded matrix",
        extra_args=["--tag", "baseline"],
    )

    _assert_repo_clean(git_repo)

    _run(_dockyard_command(*args), cwd=git_repo, env=env)

    _assert_repo_clean(git_repo)


def test_bare_dock_command_in_repo_with_missing_tag_limit_does_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Bare dock miss-filter+limit paths should remain read-only in repo cwd."""
    env = _dockyard_env(tmp_path)

    _save_checkpoint(
        git_repo,
        env,
        objective="bare dock in-repo miss-filter baseline",
        decisions="seed checkpoint for callback in-repo no-match tag+limit coverage",
        next_step="run bare dock from repo",
        risks="none",
        command="echo callback in-repo non-interference",
        extra_args=["--tag", "baseline"],
    )

    _assert_repo_clean(git_repo)

    _run(_dockyard_command("--tag", "missing-tag"), cwd=git_repo, env=env)
    _run(_dockyard_command("--tag", "missing-tag", "--json"), cwd=git_repo, env=env)
    _run(_dockyard_command("--tag", "missing-tag", "--limit", "1"), cwd=git_repo, env=env)
    _run(_dockyard_command("--tag", "missing-tag", "--limit", "1", "--json"), cwd=git_repo, env=env)

    _assert_repo_clean(git_repo)


def test_bare_dock_command_outside_repo_with_missing_tag_limit_does_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Bare dock miss-filter+limit paths should remain read-only outside repos."""
    env = _dockyard_env(tmp_path)

    _save_checkpoint(
        git_repo,
        env,
        objective="bare dock outside repo miss-filter baseline",
        decisions="seed checkpoint for callback no-match tag+limit coverage",
        next_step="run bare dock from outside repo",
        risks="none",
        command="echo callback non-interference",
        extra_args=["--tag", "baseline"],
    )

    _assert_repo_clean(git_repo)

    _run(_dockyard_command("--tag", "missing-tag"), cwd=tmp_path, env=env)
    _run(_dockyard_command("--tag", "missing-tag", "--json"), cwd=tmp_path, env=env)
    _run(_dockyard_command("--tag", "missing-tag", "--limit", "1"), cwd=tmp_path, env=env)
    _run(_dockyard_command("--tag", "missing-tag", "--limit", "1", "--json"), cwd=tmp_path, env=env)

    _assert_repo_clean(git_repo)


@pytest.mark.parametrize(
    "args",
    [
        (),
        ("--json",),
        ("--json", "--limit", "1"),
        ("--tag", "missing-tag", "--stale", "0"),
        ("--json", "--tag", "baseline", "--stale", "0", "--limit", "1"),
        ("--json", "--tag", "missing-tag", "--stale", "0"),
        ("--tag", "missing-tag", "--stale", "0", "--limit", "1"),
        ("--json", "--tag", "missing-tag", "--stale", "0", "--limit", "1"),
    ],
    ids=[
        "default",
        "json",
        "json_limit",
        "table_missing_tag_stale",
        "json_tag_stale_limit",
        "json_missing_tag_stale",
        "table_missing_tag_stale_limit",
        "json_missing_tag_stale_limit",
    ],
)
def test_bare_dock_command_outside_repo_read_variants_do_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    args: tuple[str, ...],
) -> None:
    """Bare dock read variants should stay non-mutating outside repos."""
    env = _dockyard_env(tmp_path)

    _save_checkpoint(
        git_repo,
        env,
        objective="bare dock outside repo read-variant baseline",
        decisions="seed checkpoint for callback outside-repo read variants",
        next_step="run bare dock from outside repo",
        risks="none",
        command="echo callback outside-repo",
        extra_args=["--tag", "baseline"],
    )

    _assert_repo_clean(git_repo)

    _run(_dockyard_command(*args), cwd=tmp_path, env=env)

    _assert_repo_clean(git_repo)


@pytest.mark.parametrize(
    "args",
    [
        (),
        ("--stale", "0"),
        ("--json",),
        ("--json", "--stale", "0", "--limit", "1"),
        ("--json", "--limit", "1"),
        ("--tag", "missing-tag"),
        ("--tag", "missing-tag", "--json"),
        ("--tag", "missing-tag", "--limit", "1"),
        ("--tag", "missing-tag", "--limit", "1", "--json"),
    ],
    ids=[
        "default",
        "stale_zero",
        "json",
        "json_stale_limit",
        "json_limit",
        "missing_tag",
        "missing_tag_json",
        "missing_tag_limit",
        "missing_tag_limit_json",
    ],
)
def test_bare_dock_command_outside_repo_empty_store_read_variants_do_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    args: tuple[str, ...],
) -> None:
    """Bare dock read variants should stay non-mutating with empty data store."""
    env = _dockyard_env(tmp_path)

    _assert_repo_clean(git_repo)

    _run(_dockyard_command(*args), cwd=tmp_path, env=env)

    _assert_repo_clean(git_repo)


@pytest.mark.parametrize(
    ("args", "expected_fragment"),
    [
        (("--stale", "-1"), "--stale must be >= 0."),
        (("--limit", "0"), "--limit must be >= 1."),
        (("--tag", "   "), "--tag must be a non-empty string."),
        (("--tag", "alpha", "--stale", "-1", "--limit", "1"), "--stale must be >= 0."),
        (("--tag", "alpha", "--stale", "0", "--limit", "0"), "--limit must be >= 1."),
        (("--tag", "   ", "--stale", "0", "--limit", "1"), "--tag must be a non-empty string."),
    ],
)
def test_bare_dock_invalid_flag_validation_does_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    args: tuple[str, ...],
    expected_fragment: str,
) -> None:
    """Bare dock validation failures should remain non-mutating."""
    env = _dockyard_env(tmp_path)

    _assert_repo_clean(git_repo)
    completed = subprocess.run(
        _dockyard_command(*args),
        cwd=str(git_repo),
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode != 0
    output = f"{completed.stdout}\n{completed.stderr}"
    assert expected_fragment in output
    assert "Traceback" not in output
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize(
    ("args", "expected_fragment"),
    [
        (("--stale", "-1"), "--stale must be >= 0."),
        (("--limit", "0"), "--limit must be >= 1."),
        (("--tag", "   "), "--tag must be a non-empty string."),
        (("--tag", "alpha", "--stale", "-1", "--limit", "1"), "--stale must be >= 0."),
        (("--tag", "alpha", "--stale", "0", "--limit", "0"), "--limit must be >= 1."),
        (("--tag", "   ", "--stale", "0", "--limit", "1"), "--tag must be a non-empty string."),
    ],
)
def test_bare_dock_invalid_flag_validation_outside_repo_does_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    args: tuple[str, ...],
    expected_fragment: str,
) -> None:
    """Bare dock validation failures outside repos should remain non-mutating."""
    env = _dockyard_env(tmp_path)

    _assert_repo_clean(git_repo)
    completed = subprocess.run(
        _dockyard_command(*args),
        cwd=str(tmp_path),
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode != 0
    output = f"{completed.stdout}\n{completed.stderr}"
    assert expected_fragment in output
    assert "Traceback" not in output
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["ls", "harbor"], ids=["ls", "harbor"])
@pytest.mark.parametrize(
    ("args", "expected_fragment"),
    [
        (("--stale", "-1"), "--stale must be >= 0."),
        (("--limit", "0"), "--limit must be >= 1."),
        (("--tag", "   "), "--tag must be a non-empty string."),
        (("--tag", "alpha", "--stale", "-1", "--limit", "1"), "--stale must be >= 0."),
        (("--tag", "alpha", "--stale", "0", "--limit", "0"), "--limit must be >= 1."),
        (("--tag", "   ", "--stale", "0", "--limit", "1"), "--tag must be a non-empty string."),
    ],
)
def test_dashboard_invalid_flag_validation_does_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    command_name: DashboardCommandName,
    args: tuple[str, ...],
    expected_fragment: str,
) -> None:
    """ls/harbor validation failures should remain non-mutating."""
    env = _dockyard_env(tmp_path)

    _assert_repo_clean(git_repo)
    completed = subprocess.run(
        _dockyard_command(command_name, *args),
        cwd=str(git_repo),
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode != 0
    output = f"{completed.stdout}\n{completed.stderr}"
    assert expected_fragment in output
    assert "Traceback" not in output
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["ls", "harbor"], ids=["ls", "harbor"])
@pytest.mark.parametrize(
    ("args", "expected_fragment"),
    [
        (("--stale", "-1"), "--stale must be >= 0."),
        (("--limit", "0"), "--limit must be >= 1."),
        (("--tag", "   "), "--tag must be a non-empty string."),
        (("--tag", "alpha", "--stale", "-1", "--limit", "1"), "--stale must be >= 0."),
        (("--tag", "alpha", "--stale", "0", "--limit", "0"), "--limit must be >= 1."),
        (("--tag", "   ", "--stale", "0", "--limit", "1"), "--tag must be a non-empty string."),
    ],
)
def test_dashboard_invalid_flag_validation_outside_repo_does_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    command_name: DashboardCommandName,
    args: tuple[str, ...],
    expected_fragment: str,
) -> None:
    """Outside-repo ls/harbor validation failures should remain non-mutating."""
    env = _dockyard_env(tmp_path)

    _assert_repo_clean(git_repo)
    completed = subprocess.run(
        _dockyard_command(command_name, *args),
        cwd=str(tmp_path),
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode != 0
    output = f"{completed.stdout}\n{completed.stderr}"
    assert expected_fragment in output
    assert "Traceback" not in output
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["search", "f"], ids=["search", "f_alias"])
@pytest.mark.parametrize(
    ("args", "expected_fragment"),
    [
        (("   ",), "Query must be a non-empty string."),
        (("baseline", "--limit", "0"), "--limit must be >= 1."),
        (("baseline", "--tag", "   "), "--tag must be a non-empty string."),
        (("baseline", "--repo", "   "), "--repo must be a non-empty string."),
        (("baseline", "--branch", "   "), "--branch must be a non-empty string."),
        (
            ("baseline", "--tag", "   ", "--repo", "repo-x"),
            "--tag must be a non-empty string.",
        ),
        (
            ("baseline", "--repo", "   ", "--branch", "main"),
            "--repo must be a non-empty string.",
        ),
        (
            ("baseline", "--repo", "repo-x", "--branch", "   "),
            "--branch must be a non-empty string.",
        ),
        (
            ("baseline", "--tag", "baseline", "--repo", "   ", "--branch", "main"),
            "--repo must be a non-empty string.",
        ),
        (("baseline", "--tag", "baseline", "--limit", "0"), "--limit must be >= 1."),
        (("baseline", "--tag", "   ", "--limit", "1"), "--tag must be a non-empty string."),
    ],
)
def test_search_invalid_flag_validation_does_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    command_name: SearchCommandName,
    args: tuple[str, ...],
    expected_fragment: str,
) -> None:
    """search/f validation failures should remain non-mutating."""
    env = _dockyard_env(tmp_path)

    _assert_repo_clean(git_repo)
    completed = subprocess.run(
        _dockyard_command(command_name, *args),
        cwd=str(git_repo),
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode != 0
    output = f"{completed.stdout}\n{completed.stderr}"
    assert expected_fragment in output
    assert "Traceback" not in output
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["search", "f"], ids=["search", "f_alias"])
@pytest.mark.parametrize(
    ("args", "expected_fragment"),
    [
        (("   ",), "Query must be a non-empty string."),
        (("baseline", "--limit", "0"), "--limit must be >= 1."),
        (("baseline", "--tag", "   "), "--tag must be a non-empty string."),
        (("baseline", "--repo", "   "), "--repo must be a non-empty string."),
        (("baseline", "--branch", "   "), "--branch must be a non-empty string."),
        (
            ("baseline", "--tag", "   ", "--repo", "repo-x"),
            "--tag must be a non-empty string.",
        ),
        (
            ("baseline", "--repo", "   ", "--branch", "main"),
            "--repo must be a non-empty string.",
        ),
        (
            ("baseline", "--repo", "repo-x", "--branch", "   "),
            "--branch must be a non-empty string.",
        ),
        (
            ("baseline", "--tag", "baseline", "--repo", "   ", "--branch", "main"),
            "--repo must be a non-empty string.",
        ),
        (("baseline", "--tag", "baseline", "--limit", "0"), "--limit must be >= 1."),
        (("baseline", "--tag", "   ", "--limit", "1"), "--tag must be a non-empty string."),
    ],
)
def test_search_invalid_flag_validation_outside_repo_does_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    command_name: SearchCommandName,
    args: tuple[str, ...],
    expected_fragment: str,
) -> None:
    """Outside-repo search/f validation failures should remain non-mutating."""
    env = _dockyard_env(tmp_path)

    _assert_repo_clean(git_repo)
    completed = subprocess.run(
        _dockyard_command(command_name, *args),
        cwd=str(tmp_path),
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode != 0
    output = f"{completed.stdout}\n{completed.stderr}"
    assert expected_fragment in output
    assert "Traceback" not in output
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize(
    ("args", "expected_fragment"),
    [
        (("review", "add", "--reason", "invalid", "--severity", "critical"), "Invalid severity"),
        (
            ("review", "add", "--reason", "invalid", "--severity", "   "),
            "Severity must be a non-empty string.",
        ),
        (
            ("review", "add", "--reason", "   ", "--severity", "low"),
            "--reason must be a non-empty string.",
        ),
        (
            ("review", "add", "--reason", "ok", "--severity", "low", "--repo", "repo-x"),
            "Provide both --repo and --branch when overriding context.",
        ),
        (
            (
                "review",
                "add",
                "--reason",
                "ok",
                "--severity",
                "low",
                "--repo",
                "   ",
                "--branch",
                "main",
            ),
            "--repo must be a non-empty string.",
        ),
        (
            (
                "review",
                "add",
                "--reason",
                "ok",
                "--severity",
                "low",
                "--repo",
                "repo-x",
                "--branch",
                "   ",
            ),
            "--branch must be a non-empty string.",
        ),
    ],
)
def test_review_add_invalid_validation_does_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    args: tuple[str, ...],
    expected_fragment: str,
) -> None:
    """Review add validation failures should remain non-mutating."""
    env = _dockyard_env(tmp_path)

    _assert_repo_clean(git_repo)
    completed = subprocess.run(
        _dockyard_command(*args),
        cwd=str(git_repo),
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode != 0
    output = f"{completed.stdout}\n{completed.stderr}"
    assert expected_fragment in output
    assert "Traceback" not in output
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize(
    ("args", "expected_fragment"),
    [
        (("review", "add", "--reason", "invalid", "--severity", "critical"), "Invalid severity"),
        (
            ("review", "add", "--reason", "invalid", "--severity", "   "),
            "Severity must be a non-empty string.",
        ),
        (
            ("review", "add", "--reason", "   ", "--severity", "low"),
            "--reason must be a non-empty string.",
        ),
        (
            ("review", "add", "--reason", "ok", "--severity", "low", "--repo", "repo-x"),
            "Provide both --repo and --branch when overriding context.",
        ),
        (
            ("review", "add", "--reason", "ok", "--severity", "low"),
            "Current path is not inside a git repository.",
        ),
        (
            (
                "review",
                "add",
                "--reason",
                "ok",
                "--severity",
                "low",
                "--repo",
                "   ",
                "--branch",
                "main",
            ),
            "--repo must be a non-empty string.",
        ),
        (
            (
                "review",
                "add",
                "--reason",
                "ok",
                "--severity",
                "low",
                "--repo",
                "repo-x",
                "--branch",
                "   ",
            ),
            "--branch must be a non-empty string.",
        ),
    ],
)
def test_review_add_invalid_validation_outside_repo_does_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    args: tuple[str, ...],
    expected_fragment: str,
) -> None:
    """Outside-repo review add validation failures should remain non-mutating."""
    env = _dockyard_env(tmp_path)

    _assert_repo_clean(git_repo)
    completed = subprocess.run(
        _dockyard_command(*args),
        cwd=str(tmp_path),
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode != 0
    output = f"{completed.stdout}\n{completed.stderr}"
    assert expected_fragment in output
    assert "Traceback" not in output
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize(
    ("args", "expected_fragment"),
    [
        (("review", "open", "rev_missing"), "Review item not found: rev_missing"),
        (("review", "done", "rev_missing"), "Review item not found: rev_missing"),
        (("review", "open", "   "), "Review ID must be a non-empty string."),
        (("review", "done", "   "), "Review ID must be a non-empty string."),
    ],
)
def test_review_open_done_invalid_id_does_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    args: tuple[str, ...],
    expected_fragment: str,
) -> None:
    """Invalid review open/done IDs should remain non-mutating."""
    env = _dockyard_env(tmp_path)

    _assert_repo_clean(git_repo)
    completed = subprocess.run(
        _dockyard_command(*args),
        cwd=str(git_repo),
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode != 0
    output = f"{completed.stdout}\n{completed.stderr}"
    assert expected_fragment in output
    assert "Traceback" not in output
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize(
    ("args", "expected_fragment"),
    [
        (("review", "open", "rev_missing"), "Review item not found: rev_missing"),
        (("review", "done", "rev_missing"), "Review item not found: rev_missing"),
        (("review", "open", "   "), "Review ID must be a non-empty string."),
        (("review", "done", "   "), "Review ID must be a non-empty string."),
    ],
)
def test_review_open_done_invalid_id_outside_repo_does_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    args: tuple[str, ...],
    expected_fragment: str,
) -> None:
    """Outside-repo invalid review open/done IDs should remain non-mutating."""
    env = _dockyard_env(tmp_path)

    _assert_repo_clean(git_repo)
    completed = subprocess.run(
        _dockyard_command(*args),
        cwd=str(tmp_path),
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode != 0
    output = f"{completed.stdout}\n{completed.stderr}"
    assert expected_fragment in output
    assert "Traceback" not in output
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize(
    ("args", "expected_fragment"),
    [
        (("link", "   "), "URL must be a non-empty string."),
        (("link", "https://example.com/no-root", "--root", "   "), "--root must be a non-empty string."),
        (("links", "--root", "   "), "--root must be a non-empty string."),
    ],
)
def test_link_invalid_validation_does_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    args: tuple[str, ...],
    expected_fragment: str,
) -> None:
    """Invalid link/links input validation failures should remain non-mutating."""
    env = _dockyard_env(tmp_path)

    _assert_repo_clean(git_repo)
    completed = subprocess.run(
        _dockyard_command(*args),
        cwd=str(git_repo),
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode != 0
    output = f"{completed.stdout}\n{completed.stderr}"
    assert expected_fragment in output
    assert "Traceback" not in output
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize(
    ("args", "expected_fragment"),
    [
        (("link", "   "), "URL must be a non-empty string."),
        (("link", "https://example.com/no-root", "--root", "   "), "--root must be a non-empty string."),
        (("links", "--root", "   "), "--root must be a non-empty string."),
    ],
)
def test_link_invalid_validation_outside_repo_does_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    args: tuple[str, ...],
    expected_fragment: str,
) -> None:
    """Outside-repo invalid link/links input should remain non-mutating."""
    env = _dockyard_env(tmp_path)

    _assert_repo_clean(git_repo)
    completed = subprocess.run(
        _dockyard_command(*args),
        cwd=str(tmp_path),
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode != 0
    output = f"{completed.stdout}\n{completed.stderr}"
    assert expected_fragment in output
    assert "Traceback" not in output
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["save", "s", "dock"])
def test_save_blank_root_validation_does_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Blank root validation failures for save aliases should remain non-mutating."""
    env = _dockyard_env(tmp_path)

    _assert_repo_clean(git_repo)
    completed = subprocess.run(
        _dockyard_command(
            command_name,
            "--root",
            "   ",
            "--no-prompt",
            "--objective",
            "objective",
            "--decisions",
            "decisions",
            "--next-step",
            "step",
            "--risks",
            "none",
            "--command",
            "echo noop",
        ),
        cwd=str(git_repo),
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode != 0
    output = f"{completed.stdout}\n{completed.stderr}"
    assert "--root must be a non-empty string." in output
    assert "Traceback" not in output
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["save", "s", "dock"])
def test_save_blank_root_validation_outside_repo_does_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Outside-repo blank root validation for save aliases should stay clean."""
    env = _dockyard_env(tmp_path)

    _assert_repo_clean(git_repo)
    completed = subprocess.run(
        _dockyard_command(
            command_name,
            "--root",
            "   ",
            "--no-prompt",
            "--objective",
            "objective",
            "--decisions",
            "decisions",
            "--next-step",
            "step",
            "--risks",
            "none",
            "--command",
            "echo noop",
        ),
        cwd=str(tmp_path),
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode != 0
    output = f"{completed.stdout}\n{completed.stderr}"
    assert "--root must be a non-empty string." in output
    assert "Traceback" not in output
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["resume", "r", "undock"])
def test_resume_blank_root_validation_does_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Unknown root option failures for resume aliases should remain non-mutating."""
    env = _dockyard_env(tmp_path)

    _assert_repo_clean(git_repo)
    completed = subprocess.run(
        _dockyard_command(command_name, "--root", "   "),
        cwd=str(git_repo),
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode != 0
    output = f"{completed.stdout}\n{completed.stderr}"
    assert "No such option: --root" in output
    assert "Traceback" not in output
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["resume", "r", "undock"])
def test_resume_blank_root_validation_outside_repo_does_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Outside-repo unknown root option for resume aliases should stay clean."""
    env = _dockyard_env(tmp_path)

    _assert_repo_clean(git_repo)
    completed = subprocess.run(
        _dockyard_command(command_name, "--root", "   "),
        cwd=str(tmp_path),
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode != 0
    output = f"{completed.stdout}\n{completed.stderr}"
    assert "No such option: --root" in output
    assert "Traceback" not in output
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["resume", "r", "undock"])
def test_resume_blank_branch_validation_does_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    command_name: RunCommandName,
) -> None:
    """Blank branch validation for resume aliases should remain non-mutating."""
    env = _dockyard_env(tmp_path)

    _assert_repo_clean(git_repo)
    completed = subprocess.run(
        _dockyard_command(command_name, "--branch", "   "),
        cwd=str(git_repo),
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode != 0
    output = f"{completed.stdout}\n{completed.stderr}"
    assert "--branch must be a non-empty string." in output
    assert "Traceback" not in output
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["resume", "r", "undock"])
def test_resume_blank_branch_validation_outside_repo_does_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    command_name: RunCommandName,
) -> None:
    """Outside-repo blank branch validation for resume aliases stays clean."""
    env = _dockyard_env(tmp_path)

    _assert_repo_clean(git_repo)
    completed = subprocess.run(
        _dockyard_command(command_name, "--branch", "   "),
        cwd=str(tmp_path),
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode != 0
    output = f"{completed.stdout}\n{completed.stderr}"
    assert "--branch must be a non-empty string." in output
    assert "Traceback" not in output
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["resume", "r", "undock"])
@pytest.mark.parametrize("run_cwd_kind", ["repo", "tmp"], ids=["in_repo", "outside_repo"])
@pytest.mark.parametrize("output_flag", ["", "--json", "--handoff"], ids=["default", "json", "handoff"])
def test_resume_blank_berth_validation_does_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    command_name: RunCommandName,
    run_cwd_kind: RunCwdKind,
    output_flag: str,
) -> None:
    """Blank berth argument validation should remain non-mutating."""
    env = _dockyard_env(tmp_path)

    _assert_repo_clean(git_repo)
    args = [command_name, "   "]
    if output_flag:
        args.append(output_flag)
    completed = subprocess.run(
        _dockyard_command(*args),
        cwd=str(git_repo if run_cwd_kind == "repo" else tmp_path),
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode != 0
    output = f"{completed.stdout}\n{completed.stderr}"
    assert "Berth must be a non-empty string." in output
    assert "Traceback" not in output
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["resume", "r", "undock"])
@pytest.mark.parametrize("output_flag", ["", "--json", "--handoff"], ids=["default", "json", "handoff"])
@pytest.mark.parametrize("run_cwd_kind", ["repo", "tmp"], ids=["in_repo", "outside_repo"])
def test_resume_unknown_berth_validation_does_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    command_name: RunCommandName,
    output_flag: str,
    run_cwd_kind: RunCwdKind,
) -> None:
    """Unknown berth validation should remain non-mutating across cwd contexts."""
    env = _dockyard_env(tmp_path)

    _assert_repo_clean(git_repo)
    args = [command_name, "missing-berth"]
    if output_flag:
        args.append(output_flag)
    completed = subprocess.run(
        _dockyard_command(*args),
        cwd=str(git_repo if run_cwd_kind == "repo" else tmp_path),
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode != 0
    output = f"{completed.stdout}\n{completed.stderr}"
    assert "Unknown berth: missing-berth" in output
    assert "Traceback" not in output
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["resume", "r", "undock"])
@pytest.mark.parametrize("run_cwd_kind", ["repo", "tmp"], ids=["in_repo", "outside_repo"])
@pytest.mark.parametrize("output_flag", ["", "--json", "--handoff"], ids=["default", "json", "handoff"])
def test_resume_unknown_berth_literal_markup_error_does_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    command_name: RunCommandName,
    run_cwd_kind: RunCwdKind,
    output_flag: str,
) -> None:
    """Unknown berth errors should preserve literal markup and stay non-mutating."""
    env = _dockyard_env(tmp_path)

    _assert_repo_clean(git_repo)
    args = [command_name, "[red]missing[/red]"]
    if output_flag:
        args.append(output_flag)
    completed = subprocess.run(
        _dockyard_command(*args),
        cwd=str(git_repo if run_cwd_kind == "repo" else tmp_path),
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode != 0
    output = f"{completed.stdout}\n{completed.stderr}"
    assert "Unknown berth: [red]missing[/red]" in output
    assert "Traceback" not in output
    _assert_repo_clean(git_repo)


def test_link_branch_scoped_paths_keep_repo_clean(git_repo: Path, tmp_path: Path) -> None:
    """Branch-scoped link/list flows should remain non-mutating to repo tree/index."""
    env = _dockyard_env(tmp_path)
    main_branch = _current_branch(git_repo)

    _assert_repo_clean(git_repo)
    _run(_dockyard_command("link", "https://example.com/non-interference-main-link"), cwd=git_repo, env=env)
    main_links = _run(_dockyard_command("links"), cwd=git_repo, env=env)
    assert "https://example.com/non-interference-main-link" in main_links
    _assert_repo_clean(git_repo)

    _run(["git", "checkout", "-b", "feature/non-interference-links"], cwd=git_repo, env=env)
    _run(_dockyard_command("link", "https://example.com/non-interference-feature-link"), cwd=git_repo, env=env)
    feature_links = _run(_dockyard_command("links"), cwd=git_repo, env=env)
    assert "https://example.com/non-interference-feature-link" in feature_links
    assert "https://example.com/non-interference-main-link" not in feature_links
    _assert_repo_clean(git_repo)

    _run(["git", "checkout", main_branch], cwd=git_repo, env=env)
    restored_main_links = _run(_dockyard_command("links"), cwd=git_repo, env=env)
    assert "https://example.com/non-interference-main-link" in restored_main_links
    assert "https://example.com/non-interference-feature-link" not in restored_main_links
    _assert_repo_clean(git_repo)


def test_link_branch_scoped_root_override_paths_keep_repo_clean(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Root-override branch-scoped link/list flows should remain non-mutating."""
    env = _dockyard_env(tmp_path)
    main_branch = _current_branch(git_repo)

    _assert_repo_clean(git_repo)
    _run(
        _dockyard_command(
            "link",
            "https://example.com/non-interference-root-main-link",
            "--root",
            str(git_repo),
        ),
        cwd=tmp_path,
        env=env,
    )
    main_links = _run(_dockyard_command("links", "--root", str(git_repo)), cwd=tmp_path, env=env)
    assert "https://example.com/non-interference-root-main-link" in main_links
    _assert_repo_clean(git_repo)

    _run(["git", "checkout", "-b", "feature/non-interference-root-links"], cwd=git_repo, env=env)
    _run(
        _dockyard_command(
            "link",
            "https://example.com/non-interference-root-feature-link",
            "--root",
            str(git_repo),
        ),
        cwd=tmp_path,
        env=env,
    )
    feature_links = _run(_dockyard_command("links", "--root", str(git_repo)), cwd=tmp_path, env=env)
    assert "https://example.com/non-interference-root-feature-link" in feature_links
    assert "https://example.com/non-interference-root-main-link" not in feature_links
    _assert_repo_clean(git_repo)

    _run(["git", "checkout", main_branch], cwd=git_repo, env=env)
    restored_main_links = _run(_dockyard_command("links", "--root", str(git_repo)), cwd=tmp_path, env=env)
    assert "https://example.com/non-interference-root-main-link" in restored_main_links
    assert "https://example.com/non-interference-root-feature-link" not in restored_main_links
    _assert_repo_clean(git_repo)


def test_link_branch_scoped_trimmed_root_override_paths_keep_repo_clean(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Trimmed root-override branch-scoped link/list flows should remain non-mutating."""
    env = _dockyard_env(tmp_path)
    trimmed_root = f"  {git_repo}  "
    main_branch = _current_branch(git_repo)

    _assert_repo_clean(git_repo)
    _run(
        _dockyard_command(
            "link",
            "https://example.com/non-interference-trimmed-root-main-link",
            "--root",
            trimmed_root,
        ),
        cwd=tmp_path,
        env=env,
    )
    main_links = _run(_dockyard_command("links", "--root", trimmed_root), cwd=tmp_path, env=env)
    assert "https://example.com/non-interference-trimmed-root-main-link" in main_links
    _assert_repo_clean(git_repo)

    _run(["git", "checkout", "-b", "feature/non-interference-trimmed-root-links"], cwd=git_repo, env=env)
    _run(
        _dockyard_command(
            "link",
            "https://example.com/non-interference-trimmed-root-feature-link",
            "--root",
            trimmed_root,
        ),
        cwd=tmp_path,
        env=env,
    )
    feature_links = _run(_dockyard_command("links", "--root", trimmed_root), cwd=tmp_path, env=env)
    assert "https://example.com/non-interference-trimmed-root-feature-link" in feature_links
    assert "https://example.com/non-interference-trimmed-root-main-link" not in feature_links
    _assert_repo_clean(git_repo)

    _run(["git", "checkout", main_branch], cwd=git_repo, env=env)
    restored_main_links = _run(_dockyard_command("links", "--root", trimmed_root), cwd=tmp_path, env=env)
    assert "https://example.com/non-interference-trimmed-root-main-link" in restored_main_links
    assert "https://example.com/non-interference-trimmed-root-feature-link" not in restored_main_links
    _assert_repo_clean(git_repo)


def test_save_template_validation_failures_do_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Template validation failures during save should remain non-mutating."""
    env = _dockyard_env(tmp_path)

    missing_template = tmp_path / "missing_template.json"
    bad_parse_template = tmp_path / "bad_parse_template.toml"
    bad_parse_template.write_text("[broken\nvalue = 1", encoding="utf-8")
    bad_schema_template = tmp_path / "bad_schema_template.json"
    bad_schema_template.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
    unsupported_template = tmp_path / "bad_template.yaml"
    unsupported_template.write_text("objective: unsupported\n", encoding="utf-8")
    non_utf_template = tmp_path / "bad_non_utf_template.json"
    non_utf_template.write_bytes(b"\xff\xfe\x00")

    cases = [
        (missing_template, "Template not found"),
        (bad_parse_template, "Failed to parse template"),
        (bad_schema_template, "Template must contain an object/table"),
        (unsupported_template, "Template must be .json or .toml"),
        (non_utf_template, "Failed to read template"),
    ]

    for template_path, expected_fragment in cases:
        _assert_repo_clean(git_repo)
        completed = subprocess.run(
            _dockyard_command(
                "save",
                "--root",
                str(git_repo),
                "--template",
                str(template_path),
                "--no-prompt",
                "--objective",
                "override objective",
                "--decisions",
                "override decisions",
                "--next-step",
                "override step",
                "--risks",
                "none",
                "--command",
                "echo noop",
            ),
            cwd=str(git_repo),
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert completed.returncode != 0
        output = f"{completed.stdout}\n{completed.stderr}"
        assert expected_fragment in output
        assert "Traceback" not in output
        _assert_repo_clean(git_repo)


def test_save_template_validation_failures_outside_repo_do_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Outside-repo template validation failures should remain non-mutating."""
    env = _dockyard_env(tmp_path)

    missing_template = tmp_path / "missing_template_outside.json"
    bad_parse_template = tmp_path / "bad_parse_template_outside.toml"
    bad_parse_template.write_text("[broken\nvalue = 1", encoding="utf-8")
    bad_schema_template = tmp_path / "bad_schema_template_outside.json"
    bad_schema_template.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
    unsupported_template = tmp_path / "bad_template_outside.yaml"
    unsupported_template.write_text("objective: unsupported\n", encoding="utf-8")
    non_utf_template = tmp_path / "bad_non_utf_template_outside.json"
    non_utf_template.write_bytes(b"\xff\xfe\x00")

    cases = [
        (missing_template, "Template not found"),
        (bad_parse_template, "Failed to parse template"),
        (bad_schema_template, "Template must contain an object/table"),
        (unsupported_template, "Template must be .json or .toml"),
        (non_utf_template, "Failed to read template"),
    ]

    for template_path, expected_fragment in cases:
        _assert_repo_clean(git_repo)
        completed = subprocess.run(
            _dockyard_command(
                "save",
                "--root",
                str(git_repo),
                "--template",
                str(template_path),
                "--no-prompt",
                "--objective",
                "override objective",
                "--decisions",
                "override decisions",
                "--next-step",
                "override step",
                "--risks",
                "none",
                "--command",
                "echo noop",
            ),
            cwd=str(tmp_path),
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert completed.returncode != 0
        output = f"{completed.stdout}\n{completed.stderr}"
        assert expected_fragment in output
        assert "Traceback" not in output
        _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["s", "dock"])
def test_save_alias_template_validation_failures_do_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    command_name: SaveCommandName,
) -> None:
    """Template validation failures for save aliases should remain non-mutating."""
    env = _dockyard_env(tmp_path)

    missing_template = tmp_path / f"{command_name}_missing_template.json"
    bad_parse_template = tmp_path / f"{command_name}_bad_parse_template.toml"
    bad_parse_template.write_text("[broken\nvalue = 1", encoding="utf-8")
    bad_schema_template = tmp_path / f"{command_name}_bad_schema_template.json"
    bad_schema_template.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
    unsupported_template = tmp_path / f"{command_name}_bad_template.yaml"
    unsupported_template.write_text("objective: unsupported\n", encoding="utf-8")
    non_utf_template = tmp_path / f"{command_name}_bad_non_utf_template.json"
    non_utf_template.write_bytes(b"\xff\xfe\x00")

    cases = [
        (missing_template, "Template not found"),
        (bad_parse_template, "Failed to parse template"),
        (bad_schema_template, "Template must contain an object/table"),
        (unsupported_template, "Template must be .json or .toml"),
        (non_utf_template, "Failed to read template"),
    ]

    for template_path, expected_fragment in cases:
        _assert_repo_clean(git_repo)
        completed = subprocess.run(
            _dockyard_command(
                command_name,
                "--root",
                str(git_repo),
                "--template",
                str(template_path),
                "--no-prompt",
                "--objective",
                "override objective",
                "--decisions",
                "override decisions",
                "--next-step",
                "override step",
                "--risks",
                "none",
                "--command",
                "echo noop",
            ),
            cwd=str(git_repo),
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert completed.returncode != 0
        output = f"{completed.stdout}\n{completed.stderr}"
        assert expected_fragment in output
        assert "Traceback" not in output
        _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["s", "dock"])
def test_save_alias_template_validation_failures_outside_repo_do_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    command_name: SaveCommandName,
) -> None:
    """Outside-repo template failures for save aliases should remain non-mutating."""
    env = _dockyard_env(tmp_path)

    missing_template = tmp_path / f"{command_name}_missing_template_outside.json"
    bad_parse_template = tmp_path / f"{command_name}_bad_parse_template_outside.toml"
    bad_parse_template.write_text("[broken\nvalue = 1", encoding="utf-8")
    bad_schema_template = tmp_path / f"{command_name}_bad_schema_template_outside.json"
    bad_schema_template.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
    unsupported_template = tmp_path / f"{command_name}_bad_template_outside.yaml"
    unsupported_template.write_text("objective: unsupported\n", encoding="utf-8")
    non_utf_template = tmp_path / f"{command_name}_bad_non_utf_template_outside.json"
    non_utf_template.write_bytes(b"\xff\xfe\x00")

    cases = [
        (missing_template, "Template not found"),
        (bad_parse_template, "Failed to parse template"),
        (bad_schema_template, "Template must contain an object/table"),
        (unsupported_template, "Template must be .json or .toml"),
        (non_utf_template, "Failed to read template"),
    ]

    for template_path, expected_fragment in cases:
        _assert_repo_clean(git_repo)
        completed = subprocess.run(
            _dockyard_command(
                command_name,
                "--root",
                str(git_repo),
                "--template",
                str(template_path),
                "--no-prompt",
                "--objective",
                "override objective",
                "--decisions",
                "override decisions",
                "--next-step",
                "override step",
                "--risks",
                "none",
                "--command",
                "echo noop",
            ),
            cwd=str(tmp_path),
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert completed.returncode != 0
        output = f"{completed.stdout}\n{completed.stderr}"
        assert expected_fragment in output
        assert "Traceback" not in output
        _assert_repo_clean(git_repo)


def test_save_required_field_validation_failures_do_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Save required-field validation failures should remain non-mutating."""
    env = _dockyard_env(tmp_path)

    cases: list[tuple[list[str], str]] = [
        (
            [
                "--objective",
                "objective",
                "--decisions",
                "decisions",
                "--risks",
                "none",
                "--command",
                "echo noop",
            ],
            "--no-prompt requires --objective, --decisions, and at least one --next-step.",
        ),
        (
            [
                "--objective",
                "   ",
                "--decisions",
                "decisions",
                "--next-step",
                "step",
                "--risks",
                "none",
                "--command",
                "echo noop",
            ],
            "Objective is required.",
        ),
        (
            [
                "--objective",
                "objective",
                "--decisions",
                "   ",
                "--next-step",
                "step",
                "--risks",
                "none",
                "--command",
                "echo noop",
            ],
            "Decisions / Findings is required.",
        ),
        (
            [
                "--objective",
                "objective",
                "--decisions",
                "decisions",
                "--next-step",
                "   ",
                "--risks",
                "none",
                "--command",
                "echo noop",
            ],
            "At least one next step is required.",
        ),
        (
            [
                "--objective",
                "objective",
                "--decisions",
                "decisions",
                "--next-step",
                "step",
                "--risks",
                "   ",
                "--command",
                "echo noop",
            ],
            "Risks / Review Needed is required.",
        ),
    ]

    for args_suffix, expected_fragment in cases:
        _assert_repo_clean(git_repo)
        completed = subprocess.run(
            _dockyard_command(
                "save",
                "--root",
                str(git_repo),
                "--no-prompt",
                *args_suffix,
            ),
            cwd=str(git_repo),
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert completed.returncode != 0
        output = f"{completed.stdout}\n{completed.stderr}"
        assert expected_fragment in output
        assert "Traceback" not in output
        _assert_repo_clean(git_repo)


def test_save_required_field_validation_failures_outside_repo_do_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Outside-repo save required-field failures should remain non-mutating."""
    env = _dockyard_env(tmp_path)

    cases: list[tuple[list[str], str]] = [
        (
            [
                "--objective",
                "objective",
                "--decisions",
                "decisions",
                "--risks",
                "none",
                "--command",
                "echo noop",
            ],
            "--no-prompt requires --objective, --decisions, and at least one --next-step.",
        ),
        (
            [
                "--objective",
                "   ",
                "--decisions",
                "decisions",
                "--next-step",
                "step",
                "--risks",
                "none",
                "--command",
                "echo noop",
            ],
            "Objective is required.",
        ),
        (
            [
                "--objective",
                "objective",
                "--decisions",
                "   ",
                "--next-step",
                "step",
                "--risks",
                "none",
                "--command",
                "echo noop",
            ],
            "Decisions / Findings is required.",
        ),
        (
            [
                "--objective",
                "objective",
                "--decisions",
                "decisions",
                "--next-step",
                "   ",
                "--risks",
                "none",
                "--command",
                "echo noop",
            ],
            "At least one next step is required.",
        ),
        (
            [
                "--objective",
                "objective",
                "--decisions",
                "decisions",
                "--next-step",
                "step",
                "--risks",
                "   ",
                "--command",
                "echo noop",
            ],
            "Risks / Review Needed is required.",
        ),
    ]

    for args_suffix, expected_fragment in cases:
        _assert_repo_clean(git_repo)
        completed = subprocess.run(
            _dockyard_command(
                "save",
                "--root",
                str(git_repo),
                "--no-prompt",
                *args_suffix,
            ),
            cwd=str(tmp_path),
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert completed.returncode != 0
        output = f"{completed.stdout}\n{completed.stderr}"
        assert expected_fragment in output
        assert "Traceback" not in output
        _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["save", "s", "dock"])
def test_save_template_path_validation_failures_do_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Template-path validation failures for save aliases should stay clean."""
    env = _dockyard_env(tmp_path)
    missing_template = tmp_path / f"{command_name}_missing_template.json"
    cases = [
        ("   ", "--template must be a non-empty string."),
        (str(missing_template), "Template not found"),
    ]

    for template_value, expected_fragment in cases:
        _assert_repo_clean(git_repo)
        completed = subprocess.run(
            _dockyard_command(
                command_name,
                "--root",
                str(git_repo),
                "--template",
                template_value,
                "--no-prompt",
                "--objective",
                "objective",
                "--decisions",
                "decisions",
                "--next-step",
                "step",
                "--risks",
                "none",
                "--command",
                "echo noop",
            ),
            cwd=str(git_repo),
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert completed.returncode != 0
        output = f"{completed.stdout}\n{completed.stderr}"
        assert expected_fragment in output
        assert "Traceback" not in output
        _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["save", "s", "dock"])
def test_save_template_path_validation_failures_outside_repo_do_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Outside-repo template-path failures for save aliases should stay clean."""
    env = _dockyard_env(tmp_path)
    missing_template = tmp_path / f"{command_name}_missing_template_outside.json"
    cases = [
        ("   ", "--template must be a non-empty string."),
        (str(missing_template), "Template not found"),
    ]

    for template_value, expected_fragment in cases:
        _assert_repo_clean(git_repo)
        completed = subprocess.run(
            _dockyard_command(
                command_name,
                "--root",
                str(git_repo),
                "--template",
                template_value,
                "--no-prompt",
                "--objective",
                "objective",
                "--decisions",
                "decisions",
                "--next-step",
                "step",
                "--risks",
                "none",
                "--command",
                "echo noop",
            ),
            cwd=str(tmp_path),
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert completed.returncode != 0
        output = f"{completed.stdout}\n{completed.stderr}"
        assert expected_fragment in output
        assert "Traceback" not in output
        _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["s", "dock"])
def test_save_alias_required_field_validation_failures_do_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    command_name: SaveCommandName,
) -> None:
    """Required-field validation failures for save aliases should stay clean."""
    env = _dockyard_env(tmp_path)

    cases: list[tuple[list[str], str]] = [
        (
            [
                "--objective",
                "objective",
                "--decisions",
                "decisions",
                "--risks",
                "none",
                "--command",
                "echo noop",
            ],
            "--no-prompt requires --objective, --decisions, and at least one --next-step.",
        ),
        (
            [
                "--objective",
                "   ",
                "--decisions",
                "decisions",
                "--next-step",
                "step",
                "--risks",
                "none",
                "--command",
                "echo noop",
            ],
            "Objective is required.",
        ),
        (
            [
                "--objective",
                "objective",
                "--decisions",
                "   ",
                "--next-step",
                "step",
                "--risks",
                "none",
                "--command",
                "echo noop",
            ],
            "Decisions / Findings is required.",
        ),
        (
            [
                "--objective",
                "objective",
                "--decisions",
                "decisions",
                "--next-step",
                "   ",
                "--risks",
                "none",
                "--command",
                "echo noop",
            ],
            "At least one next step is required.",
        ),
        (
            [
                "--objective",
                "objective",
                "--decisions",
                "decisions",
                "--next-step",
                "step",
                "--risks",
                "   ",
                "--command",
                "echo noop",
            ],
            "Risks / Review Needed is required.",
        ),
    ]

    for args_suffix, expected_fragment in cases:
        _assert_repo_clean(git_repo)
        completed = subprocess.run(
            _dockyard_command(
                command_name,
                "--root",
                str(git_repo),
                "--no-prompt",
                *args_suffix,
            ),
            cwd=str(git_repo),
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert completed.returncode != 0
        output = f"{completed.stdout}\n{completed.stderr}"
        assert expected_fragment in output
        assert "Traceback" not in output
        _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["s", "dock"])
def test_save_alias_required_field_validation_failures_outside_repo_do_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    command_name: SaveCommandName,
) -> None:
    """Outside-repo required-field failures for save aliases stay clean."""
    env = _dockyard_env(tmp_path)

    cases: list[tuple[list[str], str]] = [
        (
            [
                "--objective",
                "objective",
                "--decisions",
                "decisions",
                "--risks",
                "none",
                "--command",
                "echo noop",
            ],
            "--no-prompt requires --objective, --decisions, and at least one --next-step.",
        ),
        (
            [
                "--objective",
                "   ",
                "--decisions",
                "decisions",
                "--next-step",
                "step",
                "--risks",
                "none",
                "--command",
                "echo noop",
            ],
            "Objective is required.",
        ),
        (
            [
                "--objective",
                "objective",
                "--decisions",
                "   ",
                "--next-step",
                "step",
                "--risks",
                "none",
                "--command",
                "echo noop",
            ],
            "Decisions / Findings is required.",
        ),
        (
            [
                "--objective",
                "objective",
                "--decisions",
                "decisions",
                "--next-step",
                "   ",
                "--risks",
                "none",
                "--command",
                "echo noop",
            ],
            "At least one next step is required.",
        ),
        (
            [
                "--objective",
                "objective",
                "--decisions",
                "decisions",
                "--next-step",
                "step",
                "--risks",
                "   ",
                "--command",
                "echo noop",
            ],
            "Risks / Review Needed is required.",
        ),
    ]

    for args_suffix, expected_fragment in cases:
        _assert_repo_clean(git_repo)
        completed = subprocess.run(
            _dockyard_command(
                command_name,
                "--root",
                str(git_repo),
                "--no-prompt",
                *args_suffix,
            ),
            cwd=str(tmp_path),
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert completed.returncode != 0
        output = f"{completed.stdout}\n{completed.stderr}"
        assert expected_fragment in output
        assert "Traceback" not in output
        _assert_repo_clean(git_repo)


def test_save_invalid_config_failures_do_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Save invalid-config failures should remain non-mutating."""
    env = _dockyard_env(tmp_path)
    dock_home = Path(env["DOCKYARD_HOME"])
    dock_home.mkdir(parents=True, exist_ok=True)
    config_path = dock_home / "config.toml"

    cases = [
        ("[review_heuristics\nfiles_changed_threshold = 4", "Invalid config TOML"),
        ('review_heuristics = "bad-type"\n', "Config section review_heuristics must be a table."),
        ('[review_heuristics]\nrisky_path_patterns = ["(^|/)[bad"]\n', "Invalid regex"),
        ("[review_heuristics]\nchurn_threshold = -1\n", "Config field review_heuristics.churn_threshold must be >= 0."),
    ]

    for config_text, expected_fragment in cases:
        config_path.write_text(config_text, encoding="utf-8")
        _assert_repo_clean(git_repo)
        completed = subprocess.run(
            _dockyard_command(
                "save",
                "--root",
                str(git_repo),
                "--no-prompt",
                "--objective",
                "config failure objective",
                "--decisions",
                "config failure decisions",
                "--next-step",
                "fix config",
                "--risks",
                "none",
                "--command",
                "echo noop",
            ),
            cwd=str(git_repo),
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert completed.returncode != 0
        output = f"{completed.stdout}\n{completed.stderr}"
        assert expected_fragment in output
        assert "Traceback" not in output
        _assert_repo_clean(git_repo)


def test_save_invalid_config_failures_outside_repo_do_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Outside-repo save invalid-config failures should remain non-mutating."""
    env = _dockyard_env(tmp_path)
    dock_home = Path(env["DOCKYARD_HOME"])
    dock_home.mkdir(parents=True, exist_ok=True)
    config_path = dock_home / "config.toml"

    cases = [
        ("[review_heuristics\nfiles_changed_threshold = 4", "Invalid config TOML"),
        ('review_heuristics = "bad-type"\n', "Config section review_heuristics must be a table."),
        ('[review_heuristics]\nrisky_path_patterns = ["(^|/)[bad"]\n', "Invalid regex"),
        ("[review_heuristics]\nchurn_threshold = -1\n", "Config field review_heuristics.churn_threshold must be >= 0."),
    ]

    for config_text, expected_fragment in cases:
        config_path.write_text(config_text, encoding="utf-8")
        _assert_repo_clean(git_repo)
        completed = subprocess.run(
            _dockyard_command(
                "save",
                "--root",
                str(git_repo),
                "--no-prompt",
                "--objective",
                "config failure objective",
                "--decisions",
                "config failure decisions",
                "--next-step",
                "fix config",
                "--risks",
                "none",
                "--command",
                "echo noop",
            ),
            cwd=str(tmp_path),
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert completed.returncode != 0
        output = f"{completed.stdout}\n{completed.stderr}"
        assert expected_fragment in output
        assert "Traceback" not in output
        _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["s", "dock"])
def test_save_alias_invalid_config_failures_do_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    command_name: SaveCommandName,
) -> None:
    """Save-alias invalid-config failures should remain non-mutating."""
    env = _dockyard_env(tmp_path)
    dock_home = Path(env["DOCKYARD_HOME"])
    dock_home.mkdir(parents=True, exist_ok=True)
    config_path = dock_home / "config.toml"

    cases = [
        ("[review_heuristics\nfiles_changed_threshold = 4", "Invalid config TOML"),
        ('review_heuristics = "bad-type"\n', "Config section review_heuristics must be a table."),
        ('[review_heuristics]\nrisky_path_patterns = ["(^|/)[bad"]\n', "Invalid regex"),
        ("[review_heuristics]\nchurn_threshold = -1\n", "Config field review_heuristics.churn_threshold must be >= 0."),
    ]

    for config_text, expected_fragment in cases:
        config_path.write_text(config_text, encoding="utf-8")
        _assert_repo_clean(git_repo)
        completed = subprocess.run(
            _dockyard_command(
                command_name,
                "--root",
                str(git_repo),
                "--no-prompt",
                "--objective",
                "alias config failure objective",
                "--decisions",
                "alias config failure decisions",
                "--next-step",
                "fix config",
                "--risks",
                "none",
                "--command",
                "echo noop",
            ),
            cwd=str(git_repo),
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert completed.returncode != 0
        output = f"{completed.stdout}\n{completed.stderr}"
        assert expected_fragment in output
        assert "Traceback" not in output
        _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["s", "dock"])
def test_save_alias_invalid_config_failures_outside_repo_do_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    command_name: SaveCommandName,
) -> None:
    """Outside-repo save-alias invalid-config failures should remain non-mutating."""
    env = _dockyard_env(tmp_path)
    dock_home = Path(env["DOCKYARD_HOME"])
    dock_home.mkdir(parents=True, exist_ok=True)
    config_path = dock_home / "config.toml"

    cases = [
        ("[review_heuristics\nfiles_changed_threshold = 4", "Invalid config TOML"),
        ('review_heuristics = "bad-type"\n', "Config section review_heuristics must be a table."),
        ('[review_heuristics]\nrisky_path_patterns = ["(^|/)[bad"]\n', "Invalid regex"),
        ("[review_heuristics]\nchurn_threshold = -1\n", "Config field review_heuristics.churn_threshold must be >= 0."),
    ]

    for config_text, expected_fragment in cases:
        config_path.write_text(config_text, encoding="utf-8")
        _assert_repo_clean(git_repo)
        completed = subprocess.run(
            _dockyard_command(
                command_name,
                "--root",
                str(git_repo),
                "--no-prompt",
                "--objective",
                "alias outside config failure objective",
                "--decisions",
                "alias outside config failure decisions",
                "--next-step",
                "fix config",
                "--risks",
                "none",
                "--command",
                "echo noop",
            ),
            cwd=str(tmp_path),
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert completed.returncode != 0
        output = f"{completed.stdout}\n{completed.stderr}"
        assert expected_fragment in output
        assert "Traceback" not in output
        _assert_repo_clean(git_repo)


def test_save_unknown_config_section_does_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Unknown config sections should not affect non-interference guarantees."""
    env = _dockyard_env(tmp_path)
    dock_home = Path(env["DOCKYARD_HOME"])
    dock_home.mkdir(parents=True, exist_ok=True)
    (dock_home / "config.toml").write_text(
        "[other_section]\nfoo = \"bar\"\n",
        encoding="utf-8",
    )

    _assert_repo_clean(git_repo)
    _run(
        _dockyard_command(
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "unknown config section non-interference",
            "--decisions",
            "unknown section should be ignored",
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
        ),
        cwd=git_repo,
        env=env,
    )
    _assert_repo_clean(git_repo)


def test_save_unknown_config_section_outside_repo_does_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Outside-repo save with unknown config sections should remain non-mutating."""
    env = _dockyard_env(tmp_path)
    dock_home = Path(env["DOCKYARD_HOME"])
    dock_home.mkdir(parents=True, exist_ok=True)
    (dock_home / "config.toml").write_text(
        "[other_section]\nfoo = \"bar\"\n",
        encoding="utf-8",
    )

    _assert_repo_clean(git_repo)
    _run(
        _dockyard_command(
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "outside unknown config section non-interference",
            "--decisions",
            "unknown section should be ignored outside repo",
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
        ),
        cwd=tmp_path,
        env=env,
    )
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["s", "dock"])
def test_save_alias_unknown_config_section_does_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    command_name: SaveCommandName,
) -> None:
    """Unknown config sections should keep save aliases non-mutating."""
    env = _dockyard_env(tmp_path)
    dock_home = Path(env["DOCKYARD_HOME"])
    dock_home.mkdir(parents=True, exist_ok=True)
    (dock_home / "config.toml").write_text(
        "[other_section]\nfoo = \"bar\"\n",
        encoding="utf-8",
    )

    _assert_repo_clean(git_repo)
    _run(
        _dockyard_command(
            command_name,
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"{command_name} unknown config section non-interference",
            "--decisions",
            "unknown section should be ignored",
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
        ),
        cwd=git_repo,
        env=env,
    )
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["s", "dock"])
def test_save_alias_unknown_config_section_outside_repo_does_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    command_name: SaveCommandName,
) -> None:
    """Outside-repo save aliases with unknown config sections stay non-mutating."""
    env = _dockyard_env(tmp_path)
    dock_home = Path(env["DOCKYARD_HOME"])
    dock_home.mkdir(parents=True, exist_ok=True)
    (dock_home / "config.toml").write_text(
        "[other_section]\nfoo = \"bar\"\n",
        encoding="utf-8",
    )

    _assert_repo_clean(git_repo)
    _run(
        _dockyard_command(
            command_name,
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"outside {command_name} unknown config section non-interference",
            "--decisions",
            "unknown section should be ignored outside repo",
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
        ),
        cwd=tmp_path,
        env=env,
    )
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["save", "s", "dock"])
@pytest.mark.parametrize("run_cwd_kind", ["repo", "tmp"], ids=["in_repo", "outside_repo"])
def test_save_empty_review_heuristics_section_do_not_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    command_name: SaveCommandName,
    run_cwd_kind: RunCwdKind,
) -> None:
    """Empty review_heuristics config should keep save aliases non-mutating."""
    env = _dockyard_env(tmp_path)
    dock_home = Path(env["DOCKYARD_HOME"])
    dock_home.mkdir(parents=True, exist_ok=True)
    (dock_home / "config.toml").write_text("[review_heuristics]\n", encoding="utf-8")

    security_dir = git_repo / "security"
    security_dir.mkdir(exist_ok=True)
    (security_dir / "guard.py").write_text("print('guard')\n", encoding="utf-8")
    _run(["git", "add", "security/guard.py"], cwd=git_repo, env=env)
    _run(
        ["git", "commit", "-m", "seed risky file for empty review heuristics non-interference"],
        cwd=git_repo,
        env=env,
    )

    _assert_repo_clean(git_repo)
    _run(
        _dockyard_command(
            command_name,
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"{command_name} empty review_heuristics non-interference",
            "--decisions",
            "empty review_heuristics should preserve default behavior",
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
        ),
        cwd=git_repo if run_cwd_kind == "repo" else tmp_path,
        env=env,
    )
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["resume", "r", "undock"])
@pytest.mark.parametrize("output_flag", ["", "--json", "--handoff"], ids=["default", "json", "handoff"])
def test_trimmed_explicit_berth_resume_read_modes_keep_repo_clean(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
    output_flag: str,
) -> None:
    """Trimmed explicit-berth resume read modes should remain non-mutating."""
    env = _dockyard_env(tmp_path)

    _run(
        _dockyard_command(
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "trimmed explicit berth non-interference",
            "--decisions",
            "validate trimmed explicit berth read modes",
            "--next-step",
            "run trimmed explicit berth resume read path",
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
        ),
        cwd=git_repo,
        env=env,
    )

    args = [command_name, f"  {git_repo.name}  "]
    if output_flag:
        args.append(output_flag)

    _assert_repo_clean(git_repo)
    _run(_dockyard_command(*args), cwd=tmp_path, env=env)
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["resume", "r", "undock"])
@pytest.mark.parametrize("output_flag", ["", "--json", "--handoff"], ids=["default", "json", "handoff"])
def test_trimmed_explicit_berth_branch_resume_read_modes_keep_repo_clean(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
    output_flag: str,
) -> None:
    """Trimmed explicit-berth+branch resume read modes should remain non-mutating."""
    env = _dockyard_env(tmp_path)
    branch = _current_branch(git_repo)

    _run(
        _dockyard_command(
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "trimmed explicit berth+branch non-interference",
            "--decisions",
            "validate trimmed explicit berth+branch read modes",
            "--next-step",
            "run trimmed explicit berth+branch resume read path",
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
        ),
        cwd=git_repo,
        env=env,
    )

    args = [command_name, f"  {git_repo.name}  ", "--branch", f"  {branch}  "]
    if output_flag:
        args.append(output_flag)

    _assert_repo_clean(git_repo)
    _run(_dockyard_command(*args), cwd=tmp_path, env=env)
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["resume", "r", "undock"])
def test_run_with_missing_berth_root_keeps_repo_clean(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Run-enabled resume commands should fail cleanly on stale berth roots."""
    env = _dockyard_env(tmp_path)
    dock_home = Path(env["DOCKYARD_HOME"])

    _run(
        _dockyard_command(
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "missing berth root non-interference",
            "--decisions",
            "validate stale run root error path",
            "--next-step",
            "run resume with stale berth root",
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
        ),
        cwd=git_repo,
        env=env,
    )
    payload = json.loads(_run(_dockyard_command("resume", "--json"), cwd=git_repo, env=env))
    repo_id = payload["repo_id"]

    db_path = dock_home / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE berths SET root_path = ? WHERE repo_id = ?",
        (str(tmp_path / "missing-run-root"), repo_id),
    )
    conn.commit()
    conn.close()

    _assert_repo_clean(git_repo)
    completed = subprocess.run(
        _dockyard_command(command_name, git_repo.name, "--run"),
        cwd=str(tmp_path),
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode == 2
    output = f"{completed.stdout}\n{completed.stderr}"
    assert "Repository root for --run does not exist:" in output
    assert "Traceback" not in output
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["resume", "r", "undock"])
def test_run_with_branch_and_missing_berth_root_keeps_repo_clean(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Branch-scoped run failures on stale roots should remain non-mutating."""
    env = _dockyard_env(tmp_path)
    dock_home = Path(env["DOCKYARD_HOME"])
    branch = _current_branch(git_repo)

    _run(
        _dockyard_command(
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "branch stale berth root non-interference",
            "--decisions",
            "validate branch-scoped stale run root error path",
            "--next-step",
            "run branch-scoped resume with stale berth root",
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
        ),
        cwd=git_repo,
        env=env,
    )
    payload = json.loads(_run(_dockyard_command("resume", "--json"), cwd=git_repo, env=env))
    repo_id = payload["repo_id"]

    db_path = dock_home / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE berths SET root_path = ? WHERE repo_id = ?",
        (str(tmp_path / f"missing-run-root-branch-{command_name}"), repo_id),
    )
    conn.commit()
    conn.close()

    _assert_repo_clean(git_repo)
    completed = subprocess.run(
        _dockyard_command(command_name, git_repo.name, "--branch", branch, "--run"),
        cwd=str(tmp_path),
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode == 2
    output = f"{completed.stdout}\n{completed.stderr}"
    assert "Repository root for --run does not exist:" in output
    assert "Traceback" not in output
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["resume", "r", "undock"])
@pytest.mark.parametrize("output_flag", ["", "--json", "--handoff"], ids=["default", "json", "handoff"])
def test_unknown_explicit_berth_branch_resume_errors_keep_repo_clean(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
    output_flag: str,
) -> None:
    """Unknown berth+branch resume failures should remain non-mutating."""
    env = _dockyard_env(tmp_path)

    _run(
        _dockyard_command(
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "unknown explicit berth branch non-interference",
            "--decisions",
            "validate explicit berth+branch missing context error path",
            "--next-step",
            "run resume with unknown explicit berth+branch",
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
        ),
        cwd=git_repo,
        env=env,
    )

    _assert_repo_clean(git_repo)
    args = [command_name, f"  {git_repo.name}  ", "--branch", "  missing/branch  "]
    if output_flag:
        args.append(output_flag)

    completed = subprocess.run(
        _dockyard_command(*args),
        cwd=str(tmp_path),
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode == 2
    output = f"{completed.stdout}\n{completed.stderr}"
    assert "No checkpoint found for the requested context." in output
    assert "Traceback" not in output
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize("command_name", ["resume", "r", "undock"])
@pytest.mark.parametrize("run_cwd_kind", ["repo", "tmp"], ids=["in_repo", "outside_repo"])
def test_resume_alias_json_long_unicode_multiline_read_paths_keep_repo_clean(
    git_repo: Path,
    tmp_path: Path,
    command_name: RunCommandName,
    run_cwd_kind: RunCwdKind,
) -> None:
    """Resume alias JSON read paths with rich text payloads should be non-mutating."""
    env = _dockyard_env(tmp_path)
    multiline_unicode_decisions = "line one\nConfirm naïve façade safety\nline three"
    long_risks = "risklong " + ("z" * 500)

    _save_checkpoint(
        git_repo,
        env,
        objective="resume alias json rich text non-interference objective",
        decisions=multiline_unicode_decisions,
        next_step="run resume json rich text read paths",
        risks=long_risks,
        command="echo noop",
    )

    args = [command_name, "--json"]
    run_cwd = git_repo
    if run_cwd_kind == "tmp":
        args = [command_name, git_repo.name, "--json"]
        run_cwd = tmp_path

    _assert_repo_clean(git_repo)
    output = _run(_dockyard_command(*args), cwd=run_cwd, env=env)
    payload = json.loads(output)
    assert payload["decisions"] == multiline_unicode_decisions
    assert payload["risks_review"] == long_risks
    assert "façade" in output
    assert "\\u00e7" not in output
    _assert_repo_clean(git_repo)


@pytest.mark.parametrize(
    "case",
    RUN_NO_COMMAND_SCENARIOS,
    ids=RUN_NO_COMMAND_IDS,
)
def test_run_scopes_without_commands_keep_repo_clean(
    git_repo: Path,
    tmp_path: Path,
    case: RunNoCommandScenarioMeta,
) -> None:
    """No-command run scopes should remain non-mutating."""
    _assert_opt_in_run_without_commands_for_scope(
        git_repo,
        tmp_path,
        command_name=case.command_name,
        include_berth=case.include_berth,
        include_branch=case.include_branch,
        run_cwd_kind=case.run_cwd_kind,
        objective=case.objective,
        decisions=case.decisions,
        next_step=case.next_step,
    )


@pytest.mark.parametrize(
    "case",
    RUN_OPT_IN_MUTATION_SCENARIOS,
    ids=RUN_OPT_IN_MUTATION_IDS,
)
def test_run_scopes_opt_in_can_modify_repo(
    git_repo: Path,
    tmp_path: Path,
    case: RunOptInMutationScenarioMeta,
) -> None:
    """Opt-in run scopes may mutate repository as expected."""
    _assert_opt_in_run_mutates_for_scope(
        git_repo,
        tmp_path,
        command_name=case.command_name,
        include_berth=case.include_berth,
        include_branch=case.include_branch,
        run_cwd_kind=case.run_cwd_kind,
        marker_name=case.marker_name,
        objective=case.objective,
        decisions=case.decisions,
        next_step=case.next_step,
    )
