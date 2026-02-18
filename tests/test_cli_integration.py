"""Integration tests for CLI command flows."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

import pytest

from tests.metadata_utils import case_ids, pair_scope_cases_with_context

RunArgs = Sequence[str]
RunCommands = Sequence[str]
RunCwdKind = Literal["repo", "tmp"]
RunCommandName = Literal["resume", "r", "undock"]
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
    scope_slug: str

    @property
    def phrase(self) -> str:
        """Return combined command/scope phrase for scenario text."""
        return f"{self.command_label} {self.scope_descriptor}"


@dataclass(frozen=True)
class RunCommandMeta:
    """Metadata describing a run-enabled command token."""

    name: RunCommandName
    slug: str
    case_id: str
    label: str


@dataclass(frozen=True)
class RunScopeVariantMeta:
    """Metadata describing a run-scope variant."""

    variant_id: RunScopeVariantId
    include_berth: bool
    include_branch: bool
    run_cwd_kind: RunCwdKind
    descriptor: str
    slug: str


@dataclass(frozen=True)
class RunDefaultSuccessCaseMeta:
    """Scenario metadata for default-scope run success tests."""

    case_id: str
    command_name: RunCommandName
    objective: str
    decisions: str
    next_step: str
    resume_commands: tuple[str, ...]


@dataclass(frozen=True)
class RunDefaultFailureCaseMeta:
    """Scenario metadata for default-scope run failure tests."""

    case_id: str
    command_name: RunCommandName
    objective: str
    decisions: str
    next_step: str
    first_command: str
    skipped_command: str


@dataclass(frozen=True)
class RunBranchSuccessCaseMeta:
    """Scenario metadata for branch-aware run success tests."""

    case_id: str
    command_name: RunCommandName
    include_berth: bool
    include_branch: bool
    run_cwd_kind: RunCwdKind
    objective: str
    decisions: str
    next_step: str
    resume_commands: tuple[str, ...]


@dataclass(frozen=True)
class RunBranchFailureCaseMeta:
    """Scenario metadata for branch-aware run failure tests."""

    case_id: str
    command_name: RunCommandName
    include_berth: bool
    include_branch: bool
    run_cwd_kind: RunCwdKind
    objective: str
    decisions: str
    next_step: str
    first_command: str
    skipped_command: str


@dataclass(frozen=True)
class RunNoCommandCaseMeta:
    """Scenario metadata for scoped no-command run tests."""

    case_id: str
    command_name: RunCommandName
    include_berth: bool
    include_branch: bool
    run_cwd_kind: RunCwdKind
    objective: str
    decisions: str
    next_step: str


RUN_COMMAND_CASES: tuple[RunCommandMeta, ...] = (
    RunCommandMeta(name="resume", slug="resume", case_id="resume", label="resume"),
    RunCommandMeta(name="r", slug="r", case_id="r_alias", label="resume alias"),
    RunCommandMeta(name="undock", slug="undock", case_id="undock_alias", label="undock alias"),
)
RUN_SCOPE_COMMANDS: tuple[RunCommandName, ...] = tuple(case.name for case in RUN_COMMAND_CASES)
RUN_SCOPE_COMMAND_LABELS: Mapping[RunCommandName, str] = MappingProxyType(
    {case.name: case.label for case in RUN_COMMAND_CASES}
)
RUN_SCOPE_COMMAND_INDEX: Mapping[RunCommandName, int] = MappingProxyType(
    {command_name: index for index, command_name in enumerate(RUN_SCOPE_COMMANDS)}
)
RUN_SCOPE_VARIANTS: tuple[RunScopeVariantMeta, ...] = (
    RunScopeVariantMeta("default", False, False, "repo", "default", "default"),
    RunScopeVariantMeta("berth", True, False, "tmp", "berth", "berth"),
    RunScopeVariantMeta("branch", False, True, "repo", "branch", "branch"),
    RunScopeVariantMeta("berth_branch", True, True, "tmp", "berth+branch", "berth-branch"),
)
RUN_SCOPE_DESCRIPTOR_BY_FLAGS: Mapping[tuple[bool, bool], str] = MappingProxyType(
    {
        (variant.include_berth, variant.include_branch): variant.descriptor
        for variant in RUN_SCOPE_VARIANTS
    }
)
RUN_SCOPE_SLUG_BY_FLAGS: Mapping[tuple[bool, bool], str] = MappingProxyType(
    {
        (variant.include_berth, variant.include_branch): variant.slug
        for variant in RUN_SCOPE_VARIANTS
    }
)
RUN_SCOPE_VARIANT_INDEX: Mapping[RunScopeVariantId, int] = MappingProxyType(
    {variant.variant_id: index for index, variant in enumerate(RUN_SCOPE_VARIANTS)}
)


def _run_scope_case_branch_sort_key(case: RunScopeCaseMeta) -> tuple[int, int]:
    """Return sort key for branch-enabled run-scope case ordering."""
    return (
        RUN_SCOPE_VARIANT_INDEX[case.variant_id],
        RUN_SCOPE_COMMAND_INDEX[case.command_name],
    )


RUN_SCOPE_CASES: tuple[RunScopeCaseMeta, ...] = tuple(
    RunScopeCaseMeta(
        command_name=command_name,
        include_berth=variant.include_berth,
        include_branch=variant.include_branch,
        run_cwd_kind=variant.run_cwd_kind,
        variant_id=variant.variant_id,
        case_id=f"{command_name}_{variant.variant_id}",
    )
    for variant in RUN_SCOPE_VARIANTS
    for command_name in RUN_SCOPE_COMMANDS
)
RUN_BRANCH_SCOPE_CASES: tuple[RunScopeCaseMeta, ...] = tuple(
    sorted(
        (case for case in RUN_SCOPE_CASES if case.include_branch),
        key=_run_scope_case_branch_sort_key,
    )
)

def _run_scope_descriptor(include_berth: bool, include_branch: bool) -> str:
    """Return scope descriptor text for run-scenario metadata strings."""
    return RUN_SCOPE_DESCRIPTOR_BY_FLAGS[(include_berth, include_branch)]


def _run_scope_slug(include_berth: bool, include_branch: bool) -> str:
    """Return command suffix slug for scope-aware command labels."""
    return RUN_SCOPE_SLUG_BY_FLAGS[(include_berth, include_branch)]


def _run_scope_context(
    command_name: RunCommandName,
    include_berth: bool,
    include_branch: bool,
) -> RunScopeContextMeta:
    """Return command label plus scope descriptor/slug for metadata text."""
    return RunScopeContextMeta(
        command_label=RUN_SCOPE_COMMAND_LABELS[command_name],
        scope_descriptor=_run_scope_descriptor(include_berth, include_branch),
        scope_slug=_run_scope_slug(include_berth, include_branch),
    )


def _build_default_run_success_scenarios(
    cases: Sequence[RunCommandMeta],
) -> tuple[RunDefaultSuccessCaseMeta, ...]:
    """Build default-scope run success scenarios from command metadata.

    Args:
        cases: Command metadata entries for default-scope run scenarios.

    Returns:
        Parameter entries for default-scope run success tests.
    """
    return tuple(
        RunDefaultSuccessCaseMeta(
            case_id=case.case_id,
            command_name=case.name,
            objective=f"{case.label} run success objective",
            decisions=f"Validate {case.label} run success-path behavior",
            next_step=f"run {case.label}",
            resume_commands=(f"echo {case.slug}-run-one", f"echo {case.slug}-run-two"),
        )
        for case in cases
    )


def _build_default_run_failure_scenarios(
    cases: Sequence[RunCommandMeta],
) -> tuple[RunDefaultFailureCaseMeta, ...]:
    """Build default-scope run failure scenarios from command metadata.

    Args:
        cases: Command metadata entries for default-scope run scenarios.

    Returns:
        Parameter entries for default-scope run stop-on-failure tests.
    """
    return tuple(
        RunDefaultFailureCaseMeta(
            case_id=case.case_id,
            command_name=case.name,
            objective=f"{case.label} run failure objective",
            decisions=f"Validate {case.label} run stop-on-failure behavior",
            next_step=f"run {case.label}",
            first_command=f"echo {case.slug}-first",
            skipped_command=f"echo {case.slug}-should-not-run",
        )
        for case in cases
    )


def _build_branch_run_success_scenarios(
    cases: Sequence[RunScopeCaseMeta],
) -> tuple[RunBranchSuccessCaseMeta, ...]:
    """Build branch-targeted run success scenarios from shared scope metadata.

    Args:
        cases: Run-scope metadata entries with branch-targeted scope settings.

    Returns:
        Parameter entries for branch-scope run-success tests.
    """
    return tuple(
        RunBranchSuccessCaseMeta(
            case_id=case.case_id,
            command_name=case.command_name,
            include_berth=case.include_berth,
            include_branch=case.include_branch,
            run_cwd_kind=case.run_cwd_kind,
            objective=f"{context.phrase} run success objective",
            decisions=f"Validate {context.phrase} run success-path behavior",
            next_step=f"run {context.phrase}",
            resume_commands=(
                f"echo {case.command_name}-{context.scope_slug}-run-one",
                f"echo {case.command_name}-{context.scope_slug}-run-two",
            ),
        )
        for case, context in pair_scope_cases_with_context(cases, context_builder=_run_scope_context)
    )


def _build_branch_run_failure_scenarios(
    cases: Sequence[RunScopeCaseMeta],
) -> tuple[RunBranchFailureCaseMeta, ...]:
    """Build branch-targeted run failure scenarios from shared scope metadata.

    Args:
        cases: Run-scope metadata entries with branch-targeted scope settings.

    Returns:
        Parameter entries for branch-scope stop-on-failure tests.
    """
    return tuple(
        RunBranchFailureCaseMeta(
            case_id=case.case_id,
            command_name=case.command_name,
            include_berth=case.include_berth,
            include_branch=case.include_branch,
            run_cwd_kind=case.run_cwd_kind,
            objective=f"{context.phrase} run failure objective",
            decisions=f"Validate {context.phrase} stop-on-failure behavior",
            next_step=f"run {context.phrase}",
            first_command=f"echo {case.command_name}-{context.scope_slug}-first",
            skipped_command=f"echo {case.command_name}-{context.scope_slug}-should-not-run",
        )
        for case, context in pair_scope_cases_with_context(cases, context_builder=_run_scope_context)
    )


def _build_no_command_run_scope_scenarios(cases: Sequence[RunScopeCaseMeta]) -> tuple[RunNoCommandCaseMeta, ...]:
    """Build no-command run scenarios from shared scope metadata.

    Args:
        cases: Run-scope metadata entries.

    Returns:
        Parameter entries for no-command run-path tests.
    """
    return tuple(
        RunNoCommandCaseMeta(
            case_id=case.case_id,
            command_name=case.command_name,
            include_berth=case.include_berth,
            include_branch=case.include_branch,
            run_cwd_kind=case.run_cwd_kind,
            objective=f"No command {context.phrase} run",
            decisions=f"Ensure {context.phrase} run path handles empty command list",
            next_step=f"run {context.phrase} with run",
        )
        for case, context in pair_scope_cases_with_context(cases, context_builder=_run_scope_context)
    )


RUN_DEFAULT_SUCCESS_CASES: tuple[RunDefaultSuccessCaseMeta, ...] = _build_default_run_success_scenarios(
    RUN_COMMAND_CASES,
)
RUN_DEFAULT_FAILURE_CASES: tuple[RunDefaultFailureCaseMeta, ...] = _build_default_run_failure_scenarios(
    RUN_COMMAND_CASES,
)
RUN_BRANCH_SUCCESS_CASES: tuple[RunBranchSuccessCaseMeta, ...] = _build_branch_run_success_scenarios(
    RUN_BRANCH_SCOPE_CASES,
)
RUN_BRANCH_FAILURE_CASES: tuple[RunBranchFailureCaseMeta, ...] = _build_branch_run_failure_scenarios(
    RUN_BRANCH_SCOPE_CASES,
)
RUN_NO_COMMAND_CASES: tuple[RunNoCommandCaseMeta, ...] = _build_no_command_run_scope_scenarios(
    RUN_SCOPE_CASES,
)
RUN_DEFAULT_SUCCESS_IDS: tuple[str, ...] = case_ids(RUN_DEFAULT_SUCCESS_CASES)
RUN_DEFAULT_FAILURE_IDS: tuple[str, ...] = case_ids(RUN_DEFAULT_FAILURE_CASES)
RUN_BRANCH_SUCCESS_IDS: tuple[str, ...] = case_ids(RUN_BRANCH_SUCCESS_CASES)
RUN_BRANCH_FAILURE_IDS: tuple[str, ...] = case_ids(RUN_BRANCH_FAILURE_CASES)
RUN_NO_COMMAND_IDS: tuple[str, ...] = case_ids(RUN_NO_COMMAND_CASES)


def _run_dock(
    args: RunArgs,
    cwd: Path,
    env: dict[str, str],
    expect_code: int = 0,
) -> subprocess.CompletedProcess[str]:
    """Run dock CLI command and assert expected return code.

    Args:
        args: CLI argument list excluding `python3 -m dockyard`.
        cwd: Working directory for command execution.
        env: Process environment variables.
        expect_code: Expected return code.

    Returns:
        Completed process result.
    """
    completed = subprocess.run(
        _dockyard_command(*args),
        cwd=str(cwd),
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == expect_code, (
        f"Unexpected code {completed.returncode} for args={args}\n"
        f"stdout:\n{completed.stdout}\n"
        f"stderr:\n{completed.stderr}"
    )
    return completed


def _git_current_branch(repo: Path) -> str:
    """Return current branch name for test repo."""
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(repo),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _assert_resume_top_lines_contract(output: str) -> None:
    """Assert resume top-lines include required summary markers in order."""
    lines = [line for line in output.splitlines() if line.strip()]
    top = lines[:15]
    required_markers = [
        "Project/Branch:",
        "Last Checkpoint:",
        "Objective:",
        "Next Steps:",
        "  1. ",
        "Open Reviews:",
        "Verification:",
    ]
    positions: list[int] = []
    for marker in required_markers:
        index = next((i for i, line in enumerate(top) if marker in line), -1)
        assert index >= 0, f"Missing marker in top lines: {marker}\nTop lines: {top}"
        positions.append(index)

    assert positions == sorted(positions)


def _build_run_args(
    command_name: RunCommandName,
    *,
    git_repo: Path,
    branch: str | None = None,
    include_berth: bool = False,
) -> RunArgs:
    """Build run-command arguments with optional berth and branch scope."""
    run_args: list[str] = [command_name]
    if include_berth:
        run_args.append(f"  {git_repo.name}  ")
    if branch is not None:
        run_args.extend(["--branch", f"  {branch}  "])
    run_args.append("--run")
    return run_args


def _resolve_run_cwd(git_repo: Path, tmp_path: Path, run_cwd_kind: RunCwdKind) -> Path:
    """Resolve run command cwd from run-scope selector."""
    return git_repo if run_cwd_kind == "repo" else tmp_path


def _dockyard_command(*args: str) -> list[str]:
    """Build dockyard command with shared Python module prefix."""
    return [*DOCKYARD_COMMAND_PREFIX, *args]


def test_dockyard_command_helper_uses_shared_prefix() -> None:
    """Dockyard command helper should prepend the dockyard module prefix."""
    assert _dockyard_command("resume", "--json") == [
        "python3",
        "-m",
        "dockyard",
        "resume",
        "--json",
    ]


def test_dockyard_command_helper_returns_fresh_lists() -> None:
    """Dockyard command helper should return a fresh list per invocation."""
    first = _dockyard_command("ls")
    second = _dockyard_command("ls")

    first.append("--json")
    assert second == ["python3", "-m", "dockyard", "ls"]


def test_dockyard_command_helper_supports_empty_suffix() -> None:
    """Dockyard command helper should support empty command suffix."""
    assert _dockyard_command() == ["python3", "-m", "dockyard"]


def test_run_dock_helper_accepts_expected_nonzero_exit_code(tmp_path: Path) -> None:
    """Run helper should allow callers to assert expected non-zero exit codes."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    result = _run_dock(
        ["--definitely-invalid-flag"],
        cwd=tmp_path,
        env=env,
        expect_code=2,
    )
    assert result.returncode == 2


def test_run_dock_helper_defaults_to_zero_exit_code(tmp_path: Path) -> None:
    """Run helper should default to expecting successful zero exit code."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    result = _run_dock(["--help"], cwd=tmp_path, env=env)
    assert result.returncode == 0
    assert "Usage:" in result.stdout


def test_run_dock_helper_raises_on_unexpected_exit_code(tmp_path: Path) -> None:
    """Run helper should raise assertion when return code mismatches expectation."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    with pytest.raises(AssertionError, match="Unexpected code .*--definitely-invalid-flag"):
        _run_dock(
            ["--definitely-invalid-flag"],
            cwd=tmp_path,
            env=env,
            expect_code=0,
        )


def test_build_run_args_renders_expected_scope_variants(tmp_path: Path) -> None:
    """Run-args helper should include optional berth and branch selectors."""
    git_repo = tmp_path / "demo-repo"

    assert _build_run_args("resume", git_repo=git_repo) == ["resume", "--run"]
    assert _build_run_args("undock", git_repo=git_repo, include_berth=True) == [
        "undock",
        "  demo-repo  ",
        "--run",
    ]
    assert _build_run_args("resume", git_repo=git_repo, branch="main") == [
        "resume",
        "--branch",
        "  main  ",
        "--run",
    ]
    assert _build_run_args("r", git_repo=git_repo, branch="main", include_berth=True) == [
        "r",
        "  demo-repo  ",
        "--branch",
        "  main  ",
        "--run",
    ]


def test_resolve_run_cwd_selects_repo_or_tmp(git_repo: Path, tmp_path: Path) -> None:
    """Run cwd resolver should map selector values to expected paths."""
    assert _resolve_run_cwd(git_repo, tmp_path, "repo") == git_repo
    assert _resolve_run_cwd(git_repo, tmp_path, "tmp") == tmp_path


def test_cli_flow_and_aliases(git_repo: Path, tmp_path: Path) -> None:
    """Validate save/ls/resume/review/link flows including `dock dock` alias."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    save_result = _run_dock(
        [
            "dock",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Implement integration flow",
            "--decisions",
            "Keep integration tests light but realistic",
            "--next-step",
            "Run command flow checks",
            "--risks",
            "Minimal",
            "--command",
            "echo resume-one",
            "--tests-run",
            "--tests-command",
            "pytest -q",
            "--build-ok",
            "--build-command",
            "python -m build",
            "--lint-ok",
            "--lint-command",
            "ruff check",
            "--smoke-fail",
            "--tag",
            "mvp",
            "--no-auto-review",
        ],
        cwd=git_repo,
        env=env,
    )
    assert "Saved checkpoint" in save_result.stdout

    ls_json = _run_dock(["ls", "--json"], cwd=tmp_path, env=env)
    rows = json.loads(ls_json.stdout)
    assert len(rows) == 1
    assert rows[0]["berth_name"] == git_repo.name

    _run_dock(
        ["link", "https://example.com/pr/123"],
        cwd=git_repo,
        env=env,
    )
    links_result = _run_dock(["links"], cwd=git_repo, env=env)
    assert "https://example.com/pr/123" in links_result.stdout

    add_review = _run_dock(
        [
            "review",
            "add",
            "--reason",
            "manual_validation",
            "--severity",
            "med",
        ],
        cwd=git_repo,
        env=env,
    )
    review_match = re.search(r"rev_[a-f0-9]+", add_review.stdout)
    assert review_match is not None
    review_id = review_match.group(0)

    review_list = _run_dock(["review"], cwd=tmp_path, env=env)
    assert review_id in review_list.stdout

    _run_dock(["review", "done", review_id], cwd=tmp_path, env=env)
    review_all = _run_dock(["review", "list", "--all"], cwd=tmp_path, env=env)
    assert review_id in review_all.stdout
    assert "done" in review_all.stdout

    resume_json = _run_dock(["resume", "--json"], cwd=git_repo, env=env)
    payload = json.loads(resume_json.stdout)
    assert payload["objective"] == "Implement integration flow"
    assert payload["next_steps"][0] == "Run command flow checks"
    assert payload["project_name"] == git_repo.name
    assert payload["open_reviews"] == 0


def test_resume_json_reports_open_review_count(git_repo: Path, tmp_path: Path) -> None:
    """Resume JSON should reflect unresolved review debt for current slip."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Open review count objective",
            "--decisions",
            "Validate resume json review count",
            "--next-step",
            "Create unresolved review",
            "--risks",
            "manual review pending",
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
    _run_dock(
        ["review", "add", "--reason", "manual_followup", "--severity", "low"],
        cwd=git_repo,
        env=env,
    )

    payload = json.loads(_run_dock(["resume", "--json"], cwd=git_repo, env=env).stdout)
    assert payload["open_reviews"] == 1


def test_resume_json_handles_long_text_fields(git_repo: Path, tmp_path: Path) -> None:
    """Resume JSON should remain parseable with long text payloads."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    long_risk = "risktoken " + ("x" * 500)
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Long JSON objective",
            "--decisions",
            "long payload regression test",
            "--next-step",
            "run resume json",
            "--risks",
            long_risk,
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

    payload = json.loads(_run_dock(["resume", "--json"], cwd=git_repo, env=env).stdout)
    assert payload["risks_review"] == long_risk


def test_resume_json_preserves_unicode_text(git_repo: Path, tmp_path: Path) -> None:
    """Resume JSON output should preserve unicode characters."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    unicode_decisions = "Confirm naïve parser won’t mangle unicode"
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Unicode resume objective",
            "--decisions",
            unicode_decisions,
            "--next-step",
            "run resume json",
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

    payload = json.loads(_run_dock(["resume", "--json"], cwd=git_repo, env=env).stdout)
    assert payload["decisions"] == unicode_decisions


def test_resume_json_preserves_multiline_text(git_repo: Path, tmp_path: Path) -> None:
    """Resume JSON should preserve multiline decisions text."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    multiline_decisions = "line one\nline two\nline three"
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Multiline resume objective",
            "--decisions",
            multiline_decisions,
            "--next-step",
            "run resume json",
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

    payload = json.loads(_run_dock(["resume", "--json"], cwd=git_repo, env=env).stdout)
    assert payload["decisions"] == multiline_decisions


def test_json_outputs_do_not_include_ansi_sequences(git_repo: Path, tmp_path: Path) -> None:
    """JSON output modes should emit plain parseable text without ANSI codes."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "JSON plain output objective",
            "--decisions",
            "Ensure no ANSI escapes in JSON",
            "--next-step",
            "run json commands",
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

    resume_output = _run_dock(["resume", "--json"], cwd=git_repo, env=env).stdout
    ls_output = _run_dock(["ls", "--json"], cwd=tmp_path, env=env).stdout
    harbor_output = _run_dock(["harbor", "--json"], cwd=tmp_path, env=env).stdout
    callback_output = _run_dock(["--json"], cwd=tmp_path, env=env).stdout
    search_output = _run_dock(["search", "JSON plain output", "--json"], cwd=tmp_path, env=env).stdout

    for output in [resume_output, ls_output, harbor_output, callback_output, search_output]:
        assert "\x1b[" not in output
        json.loads(output)


def test_json_outputs_preserve_unicode_characters(git_repo: Path, tmp_path: Path) -> None:
    """JSON modes should keep unicode characters unescaped for readability."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    unicode_objective = "Unicode façade objective"
    unicode_decisions = "Keep naïve check in place"
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            unicode_objective,
            "--decisions",
            unicode_decisions,
            "--next-step",
            "run json commands",
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

    resume_output = _run_dock(["resume", "--json"], cwd=git_repo, env=env).stdout
    ls_output = _run_dock(["ls", "--json"], cwd=tmp_path, env=env).stdout
    harbor_output = _run_dock(["harbor", "--json"], cwd=tmp_path, env=env).stdout
    callback_output = _run_dock(["--json"], cwd=tmp_path, env=env).stdout
    search_output = _run_dock(["search", "façade", "--json"], cwd=tmp_path, env=env).stdout

    for output in [resume_output, ls_output, harbor_output, callback_output, search_output]:
        assert "\\u00e7" not in output
        assert "façade" in output


def test_save_alias_s_works(git_repo: Path, tmp_path: Path) -> None:
    """Short alias `s` should behave the same as `save`."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    saved = _run_dock(
        [
            "s",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Alias s objective",
            "--decisions",
            "Alias s decisions",
            "--next-step",
            "Alias s next step",
            "--risks",
            "none",
            "--command",
            "echo alias-s",
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
    assert "Saved checkpoint" in saved.stdout

    payload = json.loads(_run_dock(["resume", "--json"], cwd=git_repo, env=env).stdout)
    assert payload["objective"] == "Alias s objective"


def test_save_alias_s_accepts_trimmed_root_override(git_repo: Path, tmp_path: Path) -> None:
    """Save alias `s` should accept trimmed root override values."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    saved = _run_dock(
        [
            "s",
            "--root",
            f"  {git_repo}  ",
            "--no-prompt",
            "--objective",
            "Alias s trimmed root objective",
            "--decisions",
            "Alias s trimmed root decisions",
            "--next-step",
            "alias s step",
            "--risks",
            "none",
            "--command",
            "echo alias-s-trimmed",
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
        cwd=tmp_path,
        env=env,
    )
    assert "Saved checkpoint" in saved.stdout


def test_save_alias_s_rejects_blank_root_override(git_repo: Path, tmp_path: Path) -> None:
    """Save alias `s` should reject blank root override values."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    failed = _run_dock(
        [
            "s",
            "--root",
            "   ",
            "--no-prompt",
            "--objective",
            "Alias s blank root objective",
            "--decisions",
            "Alias s blank root decisions",
            "--next-step",
            "alias s step",
            "--risks",
            "none",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "--root must be a non-empty string." in output
    assert "Traceback" not in output


def test_save_alias_s_rejects_blank_template_path(git_repo: Path, tmp_path: Path) -> None:
    """Save alias `s` should reject blank template option values."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    failed = _run_dock(
        [
            "s",
            "--root",
            str(git_repo),
            "--template",
            "   ",
            "--no-prompt",
            "--objective",
            "Alias s template objective",
            "--decisions",
            "Alias s template decisions",
            "--next-step",
            "alias s step",
            "--risks",
            "none",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "--template must be a non-empty string." in output
    assert "Traceback" not in output


def test_save_alias_s_rejects_tml_template_extension(git_repo: Path, tmp_path: Path) -> None:
    """Save alias `s` should reject unsupported `.tml` templates."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    bad_template = tmp_path / "alias_s_template.tml"
    bad_template.write_text('objective = "bad extension"\n', encoding="utf-8")

    failed = _run_dock(
        [
            "s",
            "--root",
            str(git_repo),
            "--template",
            str(bad_template),
            "--no-prompt",
            "--objective",
            "Alias s unsupported extension",
            "--decisions",
            "should fail before save",
            "--next-step",
            "use json or toml",
            "--risks",
            "none",
            "--command",
            "echo noop",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "Template must be .json or .toml" in output
    assert "Traceback" not in output


def test_save_alias_s_template_non_utf8_file_is_actionable(git_repo: Path, tmp_path: Path) -> None:
    """Save alias `s` should show actionable errors for non-UTF8 templates."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    bad_template = tmp_path / "alias_s_non_utf8_template.json"
    bad_template.write_bytes(b"\xff\xfe\x00")

    failed = _run_dock(
        [
            "s",
            "--root",
            str(git_repo),
            "--template",
            str(bad_template),
            "--no-prompt",
            "--objective",
            "Alias s non-utf8 template",
            "--decisions",
            "should fail before save",
            "--next-step",
            "use a utf-8 encoded template",
            "--risks",
            "none",
            "--command",
            "echo noop",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "Failed to read template:" in output
    assert "Traceback" not in output


def test_save_alias_s_template_directory_path_is_actionable(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Save alias `s` should fail clearly when template path is a directory."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    failed = _run_dock(
        [
            "s",
            "--root",
            str(git_repo),
            "--template",
            str(tmp_path),
            "--no-prompt",
            "--objective",
            "Alias s template directory path",
            "--decisions",
            "should fail before save",
            "--next-step",
            "use a file path for template",
            "--risks",
            "none",
            "--command",
            "echo noop",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "Failed to read template:" in output
    assert "Traceback" not in output


def test_save_alias_s_missing_template_path_is_actionable(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Save alias `s` should fail clearly for missing template files."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    missing_template = tmp_path / "alias-s-missing-template.json"

    failed = _run_dock(
        [
            "s",
            "--root",
            str(git_repo),
            "--template",
            str(missing_template),
            "--no-prompt",
            "--objective",
            "Alias s missing template",
            "--decisions",
            "should fail before save",
            "--next-step",
            "use an existing template file",
            "--risks",
            "none",
            "--command",
            "echo noop",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "Template not found:" in output
    assert "Traceback" not in output


def test_save_alias_s_invalid_template_content_is_actionable(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Save alias `s` should fail clearly for malformed template content."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    bad_template = tmp_path / "alias_s_bad_template.toml"
    bad_template.write_text("[broken\nvalue = 1", encoding="utf-8")

    failed = _run_dock(
        [
            "s",
            "--root",
            str(git_repo),
            "--template",
            str(bad_template),
            "--no-prompt",
            "--objective",
            "Alias s invalid template",
            "--decisions",
            "should fail before save",
            "--next-step",
            "fix template syntax",
            "--risks",
            "none",
            "--command",
            "echo noop",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "Failed to parse template:" in output
    assert "Traceback" not in output


def test_save_alias_s_template_list_field_type_error_is_actionable(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Save alias `s` should surface schema list-field type errors cleanly."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    bad_template = tmp_path / "alias_s_bad_types.json"
    bad_template.write_text(
        json.dumps(
            {
                "objective": "bad list shape",
                "decisions": "invalid next_steps type",
                "next_steps": "not-a-list",
            }
        ),
        encoding="utf-8",
    )

    failed = _run_dock(
        [
            "s",
            "--root",
            str(git_repo),
            "--template",
            str(bad_template),
            "--no-prompt",
            "--objective",
            "override",
            "--decisions",
            "override",
            "--next-step",
            "override",
            "--risks",
            "none",
            "--command",
            "echo noop",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "Template field 'next_steps' must be an array of strings" in output
    assert "Traceback" not in output


def test_save_alias_s_template_verification_type_error_is_actionable(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Save alias `s` should surface verification type errors cleanly."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    bad_template = tmp_path / "alias_s_bad_verification.toml"
    bad_template.write_text(
        "\n".join(
            [
                'objective = "bad verification"',
                'decisions = "verification section malformed"',
                'next_steps = ["step"]',
                "",
                "[verification]",
                "tests_run = 123",
            ]
        ),
        encoding="utf-8",
    )

    failed = _run_dock(
        [
            "s",
            "--root",
            str(git_repo),
            "--template",
            str(bad_template),
            "--no-prompt",
            "--objective",
            "override",
            "--decisions",
            "override",
            "--next-step",
            "override",
            "--risks",
            "none",
            "--command",
            "echo noop",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "Template field 'tests_run' must be bool or bool-like string" in output
    assert "Traceback" not in output


def test_save_alias_s_template_bool_like_invalid_string_is_rejected(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Save alias `s` should reject unknown bool-like verification values."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    bad_template = tmp_path / "alias_s_bad_bool_like.json"
    bad_template.write_text(
        json.dumps(
            {
                "objective": "Alias s invalid bool-like",
                "decisions": "bad tests_run value",
                "next_steps": ["step"],
                "risks_review": "none",
                "verification": {"tests_run": "maybe"},
            }
        ),
        encoding="utf-8",
    )

    failed = _run_dock(
        [
            "s",
            "--root",
            str(git_repo),
            "--template",
            str(bad_template),
            "--no-prompt",
            "--objective",
            "override",
            "--decisions",
            "override",
            "--next-step",
            "override",
            "--risks",
            "none",
            "--command",
            "echo noop",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "Template field 'tests_run' must be bool or bool-like string" in output
    assert "Traceback" not in output


def test_save_alias_s_template_must_be_object_or_table(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Save alias `s` should reject non-object template payloads."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    bad_template = tmp_path / "alias_s_list_template.json"
    bad_template.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    failed = _run_dock(
        [
            "s",
            "--root",
            str(git_repo),
            "--template",
            str(bad_template),
            "--no-prompt",
            "--objective",
            "override",
            "--decisions",
            "override",
            "--next-step",
            "override",
            "--risks",
            "none",
            "--command",
            "echo noop",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "Template must contain an object/table" in output
    assert "Traceback" not in output


def test_save_alias_s_unsupported_template_extension_is_actionable(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Save alias `s` should reject unsupported template extensions."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    bad_template = tmp_path / "alias_s_template.yaml"
    bad_template.write_text("objective: bad extension\n", encoding="utf-8")

    failed = _run_dock(
        [
            "s",
            "--root",
            str(git_repo),
            "--template",
            str(bad_template),
            "--no-prompt",
            "--objective",
            "Alias s unsupported extension",
            "--decisions",
            "should fail before save",
            "--next-step",
            "use json or toml",
            "--risks",
            "none",
            "--command",
            "echo noop",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "Template must be .json or .toml" in output
    assert "Traceback" not in output


def test_save_alias_s_with_json_template_no_prompt(git_repo: Path, tmp_path: Path) -> None:
    """Save alias `s` should support JSON templates in no-prompt mode."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    template_path = tmp_path / "alias_s_save_template.json"
    template_path.write_text(
        json.dumps(
            {
                "objective": "Alias s template checkpoint objective",
                "decisions": "Alias s template decisions block",
                "next_steps": ["Alias s template next step 1", "Alias s template next step 2"],
                "risks_review": "Alias s template risk notes",
                "resume_commands": ["echo alias-s-template-cmd"],
                "tags": ["alias-s-template", "mvp"],
                "links": ["https://example.com/alias-s-template-doc"],
                "verification": {
                    "tests_run": True,
                    "tests_command": "pytest -q",
                    "build_ok": True,
                    "build_command": "echo build",
                    "lint_ok": False,
                    "smoke_ok": False,
                },
            }
        ),
        encoding="utf-8",
    )

    _run_dock(
        [
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

    resume_payload = json.loads(_run_dock(["resume", "--json"], cwd=git_repo, env=env).stdout)
    assert resume_payload["objective"] == "Alias s template checkpoint objective"
    assert resume_payload["next_steps"] == ["Alias s template next step 1", "Alias s template next step 2"]
    assert resume_payload["verification"]["tests_run"] is True
    assert resume_payload["verification"]["build_ok"] is True
    assert resume_payload["verification"]["lint_ok"] is False

    links_output = _run_dock(["links"], cwd=git_repo, env=env).stdout
    assert "https://example.com/alias-s-template-doc" in links_output
    tagged_rows = json.loads(
        _run_dock(["ls", "--tag", "alias-s-template", "--json"], cwd=tmp_path, env=env).stdout
    )
    assert len(tagged_rows) == 1
    assert tagged_rows[0]["branch"] == _git_current_branch(git_repo)


def test_save_alias_s_with_toml_template_no_prompt(git_repo: Path, tmp_path: Path) -> None:
    """Save alias `s` should accept TOML templates in no-prompt mode."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    template_path = tmp_path / "alias_s_save_template.toml"
    template_path.write_text(
        "\n".join(
            [
                'objective = "Alias s TOML objective"',
                'decisions = "Alias s TOML decisions"',
                'risks_review = "Alias s TOML risk"',
                'next_steps = ["Alias s TOML next"]',
                "",
                "[verification]",
                "tests_run = true",
                "build_ok = true",
                "lint_ok = false",
                "smoke_ok = false",
            ]
        ),
        encoding="utf-8",
    )

    _run_dock(
        [
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

    payload = json.loads(_run_dock(["resume", "--json"], cwd=git_repo, env=env).stdout)
    assert payload["objective"] == "Alias s TOML objective"
    assert payload["verification"]["tests_run"] is True
    assert payload["verification"]["build_ok"] is True
    assert payload["verification"]["lint_ok"] is False
    assert payload["verification"]["smoke_ok"] is False


def test_save_alias_s_template_path_accepts_trimmed_value(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Save alias `s` should trim whitespace around template path values."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    template_path = tmp_path / "alias_s_trimmed_template.json"
    template_path.write_text(
        json.dumps(
            {
                "objective": "Alias s trimmed template objective",
                "decisions": "Template path trimming behavior",
                "next_steps": ["run resume"],
                "risks_review": "none",
                "resume_commands": ["echo alias-s-trimmed-template"],
            }
        ),
        encoding="utf-8",
    )

    _run_dock(
        [
            "s",
            "--root",
            str(git_repo),
            "--template",
            f"  {template_path}  ",
            "--no-prompt",
            "--no-auto-review",
        ],
        cwd=git_repo,
        env=env,
    )
    payload = json.loads(_run_dock(["resume", "--json"], cwd=git_repo, env=env).stdout)
    assert payload["objective"] == "Alias s trimmed template objective"


def test_save_alias_s_template_bool_like_strings_are_coerced(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Save alias `s` should coerce bool-like verification template values."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    template_path = tmp_path / "alias_s_bool_like_template.json"
    template_path.write_text(
        json.dumps(
            {
                "objective": "Alias s bool-like objective",
                "decisions": "Use string booleans in template",
                "next_steps": ["Run resume json"],
                "risks_review": "none",
                "verification": {
                    "tests_run": "yes",
                    "build_ok": "1",
                    "lint_ok": "no",
                    "smoke_ok": "false",
                },
            }
        ),
        encoding="utf-8",
    )

    _run_dock(
        [
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
    payload = json.loads(_run_dock(["resume", "--json"], cwd=git_repo, env=env).stdout)
    assert payload["verification"]["tests_run"] is True
    assert payload["verification"]["build_ok"] is True
    assert payload["verification"]["lint_ok"] is False
    assert payload["verification"]["smoke_ok"] is False


def test_save_accepts_trimmed_root_override(git_repo: Path, tmp_path: Path) -> None:
    """Save should accept root override values with surrounding whitespace."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    saved = _run_dock(
        [
            "save",
            "--root",
            f"  {git_repo}  ",
            "--no-prompt",
            "--objective",
            "Trimmed root objective",
            "--decisions",
            "Trimmed root decisions",
            "--next-step",
            "trimmed root step",
            "--risks",
            "none",
            "--command",
            "echo trimmed-root",
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
        cwd=tmp_path,
        env=env,
    )
    assert "Saved checkpoint" in saved.stdout


def test_save_rejects_blank_root_override(git_repo: Path, tmp_path: Path) -> None:
    """Save should reject blank root override values."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    failed = _run_dock(
        [
            "save",
            "--root",
            "   ",
            "--no-prompt",
            "--objective",
            "Blank root objective",
            "--decisions",
            "Blank root decisions",
            "--next-step",
            "blank root step",
            "--risks",
            "none",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "--root must be a non-empty string." in output
    assert "Traceback" not in output


def test_save_alias_dock_accepts_trimmed_root_override(git_repo: Path, tmp_path: Path) -> None:
    """Dock alias should accept trimmed root override values."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    saved = _run_dock(
        [
            "dock",
            "--root",
            f"  {git_repo}  ",
            "--no-prompt",
            "--objective",
            "Dock alias trimmed root objective",
            "--decisions",
            "Dock alias trimmed root decisions",
            "--next-step",
            "dock alias step",
            "--risks",
            "none",
            "--command",
            "echo dock-alias",
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
        cwd=tmp_path,
        env=env,
    )
    assert "Saved checkpoint" in saved.stdout


def test_save_alias_dock_rejects_blank_root_override(git_repo: Path, tmp_path: Path) -> None:
    """Dock alias should reject blank root override values."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    failed = _run_dock(
        [
            "dock",
            "--root",
            "   ",
            "--no-prompt",
            "--objective",
            "Dock alias blank root objective",
            "--decisions",
            "Dock alias blank root decisions",
            "--next-step",
            "dock alias step",
            "--risks",
            "none",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "--root must be a non-empty string." in output
    assert "Traceback" not in output


def test_save_alias_dock_rejects_blank_template_path(git_repo: Path, tmp_path: Path) -> None:
    """Dock alias should reject blank template option values."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    failed = _run_dock(
        [
            "dock",
            "--root",
            str(git_repo),
            "--template",
            "   ",
            "--no-prompt",
            "--objective",
            "Dock alias template objective",
            "--decisions",
            "Dock alias template decisions",
            "--next-step",
            "dock alias step",
            "--risks",
            "none",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "--template must be a non-empty string." in output
    assert "Traceback" not in output


def test_save_alias_dock_rejects_tml_template_extension(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Dock alias should reject unsupported `.tml` templates."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    bad_template = tmp_path / "alias_dock_template.tml"
    bad_template.write_text('objective = "bad extension"\n', encoding="utf-8")

    failed = _run_dock(
        [
            "dock",
            "--root",
            str(git_repo),
            "--template",
            str(bad_template),
            "--no-prompt",
            "--objective",
            "Dock alias unsupported extension",
            "--decisions",
            "should fail before save",
            "--next-step",
            "use json or toml",
            "--risks",
            "none",
            "--command",
            "echo noop",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "Template must be .json or .toml" in output
    assert "Traceback" not in output


def test_save_alias_dock_template_non_utf8_file_is_actionable(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Dock alias should show actionable errors for non-UTF8 templates."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    bad_template = tmp_path / "alias_dock_non_utf8_template.json"
    bad_template.write_bytes(b"\xff\xfe\x00")

    failed = _run_dock(
        [
            "dock",
            "--root",
            str(git_repo),
            "--template",
            str(bad_template),
            "--no-prompt",
            "--objective",
            "Dock alias non-utf8 template",
            "--decisions",
            "should fail before save",
            "--next-step",
            "use a utf-8 encoded template",
            "--risks",
            "none",
            "--command",
            "echo noop",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "Failed to read template:" in output
    assert "Traceback" not in output


def test_save_alias_dock_template_directory_path_is_actionable(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Dock alias should fail clearly when template path is a directory."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    failed = _run_dock(
        [
            "dock",
            "--root",
            str(git_repo),
            "--template",
            str(tmp_path),
            "--no-prompt",
            "--objective",
            "Dock alias template directory path",
            "--decisions",
            "should fail before save",
            "--next-step",
            "use a file path for template",
            "--risks",
            "none",
            "--command",
            "echo noop",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "Failed to read template:" in output
    assert "Traceback" not in output


def test_save_alias_dock_missing_template_path_is_actionable(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Dock alias should fail clearly for missing template files."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    missing_template = tmp_path / "alias-dock-missing-template.json"

    failed = _run_dock(
        [
            "dock",
            "--root",
            str(git_repo),
            "--template",
            str(missing_template),
            "--no-prompt",
            "--objective",
            "Dock alias missing template",
            "--decisions",
            "should fail before save",
            "--next-step",
            "use an existing template file",
            "--risks",
            "none",
            "--command",
            "echo noop",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "Template not found:" in output
    assert "Traceback" not in output


def test_save_alias_dock_invalid_template_content_is_actionable(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Dock alias should fail clearly for malformed template content."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    bad_template = tmp_path / "alias_dock_bad_template.toml"
    bad_template.write_text("[broken\nvalue = 1", encoding="utf-8")

    failed = _run_dock(
        [
            "dock",
            "--root",
            str(git_repo),
            "--template",
            str(bad_template),
            "--no-prompt",
            "--objective",
            "Dock alias invalid template",
            "--decisions",
            "should fail before save",
            "--next-step",
            "fix template syntax",
            "--risks",
            "none",
            "--command",
            "echo noop",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "Failed to parse template:" in output
    assert "Traceback" not in output


def test_save_alias_dock_template_list_field_type_error_is_actionable(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Dock alias should surface schema list-field type errors cleanly."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    bad_template = tmp_path / "alias_dock_bad_types.json"
    bad_template.write_text(
        json.dumps(
            {
                "objective": "bad list shape",
                "decisions": "invalid next_steps type",
                "next_steps": "not-a-list",
            }
        ),
        encoding="utf-8",
    )

    failed = _run_dock(
        [
            "dock",
            "--root",
            str(git_repo),
            "--template",
            str(bad_template),
            "--no-prompt",
            "--objective",
            "override",
            "--decisions",
            "override",
            "--next-step",
            "override",
            "--risks",
            "none",
            "--command",
            "echo noop",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "Template field 'next_steps' must be an array of strings" in output
    assert "Traceback" not in output


def test_save_alias_dock_template_verification_type_error_is_actionable(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Dock alias should surface verification type errors cleanly."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    bad_template = tmp_path / "alias_dock_bad_verification.toml"
    bad_template.write_text(
        "\n".join(
            [
                'objective = "bad verification"',
                'decisions = "verification section malformed"',
                'next_steps = ["step"]',
                "",
                "[verification]",
                "tests_run = 123",
            ]
        ),
        encoding="utf-8",
    )

    failed = _run_dock(
        [
            "dock",
            "--root",
            str(git_repo),
            "--template",
            str(bad_template),
            "--no-prompt",
            "--objective",
            "override",
            "--decisions",
            "override",
            "--next-step",
            "override",
            "--risks",
            "none",
            "--command",
            "echo noop",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "Template field 'tests_run' must be bool or bool-like string" in output
    assert "Traceback" not in output


def test_save_alias_dock_template_bool_like_invalid_string_is_rejected(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Dock alias should reject unknown bool-like verification values."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    bad_template = tmp_path / "alias_dock_bad_bool_like.json"
    bad_template.write_text(
        json.dumps(
            {
                "objective": "Dock alias invalid bool-like",
                "decisions": "bad tests_run value",
                "next_steps": ["step"],
                "risks_review": "none",
                "verification": {"tests_run": "maybe"},
            }
        ),
        encoding="utf-8",
    )

    failed = _run_dock(
        [
            "dock",
            "--root",
            str(git_repo),
            "--template",
            str(bad_template),
            "--no-prompt",
            "--objective",
            "override",
            "--decisions",
            "override",
            "--next-step",
            "override",
            "--risks",
            "none",
            "--command",
            "echo noop",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "Template field 'tests_run' must be bool or bool-like string" in output
    assert "Traceback" not in output


def test_save_alias_dock_template_must_be_object_or_table(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Dock alias should reject non-object template payloads."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    bad_template = tmp_path / "alias_dock_list_template.json"
    bad_template.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    failed = _run_dock(
        [
            "dock",
            "--root",
            str(git_repo),
            "--template",
            str(bad_template),
            "--no-prompt",
            "--objective",
            "override",
            "--decisions",
            "override",
            "--next-step",
            "override",
            "--risks",
            "none",
            "--command",
            "echo noop",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "Template must contain an object/table" in output
    assert "Traceback" not in output


def test_save_alias_dock_unsupported_template_extension_is_actionable(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Dock alias should reject unsupported template extensions."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    bad_template = tmp_path / "alias_dock_template.yaml"
    bad_template.write_text("objective: bad extension\n", encoding="utf-8")

    failed = _run_dock(
        [
            "dock",
            "--root",
            str(git_repo),
            "--template",
            str(bad_template),
            "--no-prompt",
            "--objective",
            "Dock alias unsupported extension",
            "--decisions",
            "should fail before save",
            "--next-step",
            "use json or toml",
            "--risks",
            "none",
            "--command",
            "echo noop",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "Template must be .json or .toml" in output
    assert "Traceback" not in output


def test_save_alias_dock_with_json_template_no_prompt(git_repo: Path, tmp_path: Path) -> None:
    """Dock alias should support JSON templates in no-prompt mode."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    template_path = tmp_path / "alias_dock_save_template.json"
    template_path.write_text(
        json.dumps(
            {
                "objective": "Dock alias template checkpoint objective",
                "decisions": "Dock alias template decisions block",
                "next_steps": ["Dock alias template next step 1", "Dock alias template next step 2"],
                "risks_review": "Dock alias template risk notes",
                "resume_commands": ["echo alias-dock-template-cmd"],
                "tags": ["alias-dock-template", "mvp"],
                "links": ["https://example.com/alias-dock-template-doc"],
                "verification": {
                    "tests_run": True,
                    "tests_command": "pytest -q",
                    "build_ok": True,
                    "build_command": "echo build",
                    "lint_ok": False,
                    "smoke_ok": False,
                },
            }
        ),
        encoding="utf-8",
    )

    _run_dock(
        [
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

    resume_payload = json.loads(_run_dock(["resume", "--json"], cwd=git_repo, env=env).stdout)
    assert resume_payload["objective"] == "Dock alias template checkpoint objective"
    assert resume_payload["next_steps"] == ["Dock alias template next step 1", "Dock alias template next step 2"]
    assert resume_payload["verification"]["tests_run"] is True
    assert resume_payload["verification"]["build_ok"] is True
    assert resume_payload["verification"]["lint_ok"] is False

    links_output = _run_dock(["links"], cwd=git_repo, env=env).stdout
    assert "https://example.com/alias-dock-template-doc" in links_output
    tagged_rows = json.loads(
        _run_dock(["ls", "--tag", "alias-dock-template", "--json"], cwd=tmp_path, env=env).stdout
    )
    assert len(tagged_rows) == 1
    assert tagged_rows[0]["branch"] == _git_current_branch(git_repo)


def test_save_alias_dock_with_toml_template_no_prompt(git_repo: Path, tmp_path: Path) -> None:
    """Dock alias should accept TOML templates in no-prompt mode."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    template_path = tmp_path / "alias_dock_save_template.toml"
    template_path.write_text(
        "\n".join(
            [
                'objective = "Dock alias TOML objective"',
                'decisions = "Dock alias TOML decisions"',
                'risks_review = "Dock alias TOML risk"',
                'next_steps = ["Dock alias TOML next"]',
                "",
                "[verification]",
                "tests_run = true",
                "build_ok = true",
                "lint_ok = false",
                "smoke_ok = false",
            ]
        ),
        encoding="utf-8",
    )

    _run_dock(
        [
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

    payload = json.loads(_run_dock(["resume", "--json"], cwd=git_repo, env=env).stdout)
    assert payload["objective"] == "Dock alias TOML objective"
    assert payload["verification"]["tests_run"] is True
    assert payload["verification"]["build_ok"] is True
    assert payload["verification"]["lint_ok"] is False
    assert payload["verification"]["smoke_ok"] is False


def test_save_alias_dock_template_path_accepts_trimmed_value(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Dock alias should trim whitespace around template path values."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    template_path = tmp_path / "alias_dock_trimmed_template.json"
    template_path.write_text(
        json.dumps(
            {
                "objective": "Dock alias trimmed template objective",
                "decisions": "Template path trimming behavior",
                "next_steps": ["run resume"],
                "risks_review": "none",
                "resume_commands": ["echo alias-dock-trimmed-template"],
            }
        ),
        encoding="utf-8",
    )

    _run_dock(
        [
            "dock",
            "--root",
            str(git_repo),
            "--template",
            f"  {template_path}  ",
            "--no-prompt",
            "--no-auto-review",
        ],
        cwd=git_repo,
        env=env,
    )
    payload = json.loads(_run_dock(["resume", "--json"], cwd=git_repo, env=env).stdout)
    assert payload["objective"] == "Dock alias trimmed template objective"


def test_save_alias_dock_template_bool_like_strings_are_coerced(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Dock alias should coerce bool-like verification template values."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    template_path = tmp_path / "alias_dock_bool_like_template.json"
    template_path.write_text(
        json.dumps(
            {
                "objective": "Dock alias bool-like objective",
                "decisions": "Use string booleans in template",
                "next_steps": ["Run resume json"],
                "risks_review": "none",
                "verification": {
                    "tests_run": "yes",
                    "build_ok": "1",
                    "lint_ok": "no",
                    "smoke_ok": "false",
                },
            }
        ),
        encoding="utf-8",
    )

    _run_dock(
        [
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
    payload = json.loads(_run_dock(["resume", "--json"], cwd=git_repo, env=env).stdout)
    assert payload["verification"]["tests_run"] is True
    assert payload["verification"]["build_ok"] is True
    assert payload["verification"]["lint_ok"] is False
    assert payload["verification"]["smoke_ok"] is False


def test_save_verification_text_fields_are_normalized(git_repo: Path, tmp_path: Path) -> None:
    """Save should trim non-blank verification text and drop blank entries."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Verification normalization objective",
            "--decisions",
            "Normalize verification command/note text values",
            "--next-step",
            "inspect resume json",
            "--risks",
            "none",
            "--tests-run",
            "--tests-command",
            "   ",
            "--build-ok",
            "--build-command",
            "  make build  ",
            "--lint-ok",
            "--lint-command",
            "  ruff check  ",
            "--smoke-ok",
            "--smoke-notes",
            "   ",
            "--no-auto-review",
        ],
        cwd=git_repo,
        env=env,
    )

    payload = json.loads(_run_dock(["resume", "--json"], cwd=git_repo, env=env).stdout)
    verification = payload["verification"]
    assert verification["tests_run"] is True
    assert verification["build_ok"] is True
    assert verification["lint_ok"] is True
    assert verification["smoke_ok"] is True
    assert verification["tests_command"] is None
    assert verification["build_command"] == "make build"
    assert verification["lint_command"] == "ruff check"
    assert verification["smoke_notes"] is None


def test_save_editor_populates_decisions(git_repo: Path, tmp_path: Path) -> None:
    """Save should capture decisions from the configured editor."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    editor_script = tmp_path / "fake_editor.sh"
    editor_script.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "printf 'Decisions captured in editor\\n' > \"$1\"",
            ]
        ),
        encoding="utf-8",
    )
    editor_script.chmod(0o755)
    env["EDITOR"] = str(editor_script)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--editor",
            "--no-prompt",
            "--objective",
            "Editor decisions objective",
            "--next-step",
            "Run resume json",
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

    payload = json.loads(_run_dock(["resume", "--json"], cwd=git_repo, env=env).stdout)
    assert payload["decisions"] == "Decisions captured in editor"


def test_save_editor_with_explicit_decisions_skips_editor(git_repo: Path, tmp_path: Path) -> None:
    """Explicit decisions should take precedence over editor invocation."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    env["EDITOR"] = str(tmp_path / "missing-editor-command")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--editor",
            "--no-prompt",
            "--objective",
            "Editor precedence objective",
            "--decisions",
            "Use explicit decisions value",
            "--next-step",
            "Run resume json",
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
    payload = json.loads(_run_dock(["resume", "--json"], cwd=git_repo, env=env).stdout)
    assert payload["decisions"] == "Use explicit decisions value"


def test_save_editor_ignores_placeholder_only_content(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Placeholder-only editor text should not satisfy required decisions field."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    editor_script = tmp_path / "placeholder_editor.sh"
    editor_script.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "printf '# Decisions / Findings\\n' > \"$1\"",
            ]
        ),
        encoding="utf-8",
    )
    editor_script.chmod(0o755)
    env["EDITOR"] = str(editor_script)

    failed = _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--editor",
            "--no-prompt",
            "--objective",
            "Editor placeholder objective",
            "--next-step",
            "Run resume json",
            "--risks",
            "none",
            "--command",
            "echo noop",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "--no-prompt requires --objective, --decisions, and at least one --next-step." in output
    assert "Traceback" not in output


def test_save_editor_ignores_indented_placeholder_only_content(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Indented scaffold-only editor text should still be treated as missing."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    editor_script = tmp_path / "indented_placeholder_editor.sh"
    editor_script.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "printf '   # Decisions / Findings\\n' > \"$1\"",
            ]
        ),
        encoding="utf-8",
    )
    editor_script.chmod(0o755)
    env["EDITOR"] = str(editor_script)

    failed = _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--editor",
            "--no-prompt",
            "--objective",
            "Editor indented placeholder objective",
            "--next-step",
            "Run resume json",
            "--risks",
            "none",
            "--command",
            "echo noop",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "--no-prompt requires --objective, --decisions, and at least one --next-step." in output
    assert "Traceback" not in output


def test_save_editor_ignores_repeated_scaffold_lines(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Repeated scaffold lines should be stripped before persistence."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    editor_script = tmp_path / "repeated_scaffold_editor.sh"
    editor_script.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "printf '# Decisions / Findings\\n# Decisions / Findings\\nCore editor decision\\n' > \"$1\"",
            ]
        ),
        encoding="utf-8",
    )
    editor_script.chmod(0o755)
    env["EDITOR"] = str(editor_script)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--editor",
            "--no-prompt",
            "--objective",
            "Editor repeated scaffold objective",
            "--next-step",
            "Run resume json",
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
    payload = json.loads(_run_dock(["resume", "--json"], cwd=git_repo, env=env).stdout)
    assert payload["decisions"] == "Core editor decision"


def test_save_editor_preserves_non_scaffold_hash_lines(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Non-scaffold hash-prefixed lines from editor should be preserved."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    editor_script = tmp_path / "heading_editor.sh"
    editor_script.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "printf '# Keep this heading\\nDecision detail\\n' > \"$1\"",
            ]
        ),
        encoding="utf-8",
    )
    editor_script.chmod(0o755)
    env["EDITOR"] = str(editor_script)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--editor",
            "--no-prompt",
            "--objective",
            "Editor heading objective",
            "--next-step",
            "Run resume json",
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
    payload = json.loads(_run_dock(["resume", "--json"], cwd=git_repo, env=env).stdout)
    assert payload["decisions"] == "# Keep this heading\nDecision detail"


def test_save_editor_preserves_intentional_blank_lines(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Editor text normalization should preserve internal blank lines."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    editor_script = tmp_path / "paragraph_editor.sh"
    editor_script.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "printf '# Decisions / Findings\\n\\nFirst paragraph\\n\\nSecond paragraph\\n' > \"$1\"",
            ]
        ),
        encoding="utf-8",
    )
    editor_script.chmod(0o755)
    env["EDITOR"] = str(editor_script)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--editor",
            "--no-prompt",
            "--objective",
            "Editor paragraph objective",
            "--next-step",
            "Run resume json",
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
    payload = json.loads(_run_dock(["resume", "--json"], cwd=git_repo, env=env).stdout)
    assert payload["decisions"] == "First paragraph\n\nSecond paragraph"


def test_save_editor_trims_outer_blank_lines(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Editor normalization should trim leading/trailing empty lines."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    editor_script = tmp_path / "trim_editor.sh"
    editor_script.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "printf '# Decisions / Findings\\n\\n\\nCore decision line\\n\\n' > \"$1\"",
            ]
        ),
        encoding="utf-8",
    )
    editor_script.chmod(0o755)
    env["EDITOR"] = str(editor_script)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--editor",
            "--no-prompt",
            "--objective",
            "Editor trimming objective",
            "--next-step",
            "Run resume json",
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
    payload = json.loads(_run_dock(["resume", "--json"], cwd=git_repo, env=env).stdout)
    assert payload["decisions"] == "Core decision line"


@pytest.mark.parametrize(
    "case",
    RUN_DEFAULT_SUCCESS_CASES,
    ids=RUN_DEFAULT_SUCCESS_IDS,
)
def test_run_default_scope_executes_commands_on_success(
    git_repo: Path,
    tmp_path: Path,
    case: RunDefaultSuccessCaseMeta,
) -> None:
    """`<command> --run` should execute all recorded commands."""
    _assert_run_executes_commands_on_success(
        git_repo=git_repo,
        tmp_path=tmp_path,
        objective=case.objective,
        decisions=case.decisions,
        next_step=case.next_step,
        resume_commands=case.resume_commands,
        run_args=_build_run_args(case.command_name, git_repo=git_repo),
        run_cwd=git_repo,
    )


@pytest.mark.parametrize(
    "case",
    RUN_DEFAULT_FAILURE_CASES,
    ids=RUN_DEFAULT_FAILURE_IDS,
)
def test_run_default_scope_stops_on_failure(
    git_repo: Path,
    tmp_path: Path,
    case: RunDefaultFailureCaseMeta,
) -> None:
    """`<command> --run` should stop execution on first failing command."""
    _assert_run_stops_on_first_failure(
        git_repo=git_repo,
        tmp_path=tmp_path,
        objective=case.objective,
        decisions=case.decisions,
        next_step=case.next_step,
        first_command=case.first_command,
        skipped_command=case.skipped_command,
        run_args=_build_run_args(case.command_name, git_repo=git_repo),
        run_cwd=git_repo,
    )


def test_resume_run_compacts_multiline_command_labels(git_repo: Path, tmp_path: Path) -> None:
    """Resume --run output should compact multiline command labels."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Run multiline command label baseline",
            "--decisions",
            "Mutate command payload to include line breaks",
            "--next-step",
            "run resume --run",
            "--risks",
            "none",
            "--command",
            "echo baseline",
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

    db_path = dock_home / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE checkpoints SET resume_commands_json = ?",
        (json.dumps(["echo run-one\necho run-two"]),),
    )
    conn.commit()
    conn.close()

    run_result = _run_dock(["resume", "--run"], cwd=git_repo, env=env)
    assert "$ echo run-one echo run-two -> exit 0" in run_result.stdout


@pytest.mark.parametrize(
    "case",
    RUN_BRANCH_SUCCESS_CASES,
    ids=RUN_BRANCH_SUCCESS_IDS,
)
def test_run_branch_scopes_execute_commands_on_success(
    git_repo: Path,
    tmp_path: Path,
    case: RunBranchSuccessCaseMeta,
) -> None:
    """Branch-scoped run variants should execute recorded commands."""
    _assert_run_executes_commands_for_scope(
        git_repo=git_repo,
        tmp_path=tmp_path,
        command_name=case.command_name,
        include_berth=case.include_berth,
        include_branch=case.include_branch,
        run_cwd_kind=case.run_cwd_kind,
        objective=case.objective,
        decisions=case.decisions,
        next_step=case.next_step,
        resume_commands=case.resume_commands,
    )


@pytest.mark.parametrize(
    "case",
    RUN_BRANCH_FAILURE_CASES,
    ids=RUN_BRANCH_FAILURE_IDS,
)
def test_run_branch_scopes_stop_on_failure(
    git_repo: Path,
    tmp_path: Path,
    case: RunBranchFailureCaseMeta,
) -> None:
    """Branch-scoped run variants should stop on first failing command."""
    _assert_run_stops_on_failure_for_scope(
        git_repo=git_repo,
        tmp_path=tmp_path,
        command_name=case.command_name,
        include_berth=case.include_berth,
        include_branch=case.include_branch,
        run_cwd_kind=case.run_cwd_kind,
        objective=case.objective,
        decisions=case.decisions,
        next_step=case.next_step,
        first_command=case.first_command,
        skipped_command=case.skipped_command,
    )


def test_resume_handles_scalar_list_payload_fields(git_repo: Path, tmp_path: Path) -> None:
    """Resume handoff/run should coerce scalar list payloads safely."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Scalar list payload baseline",
            "--decisions",
            "Mutate list fields to scalar strings",
            "--next-step",
            "seed step",
            "--risks",
            "none",
            "--command",
            "echo seed",
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

    db_path = dock_home / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE checkpoints SET next_steps_json = ?, resume_commands_json = ?",
        (json.dumps("step one\nstep two"), json.dumps("echo run-one\necho run-two")),
    )
    conn.commit()
    conn.close()

    handoff_output = _run_dock(["resume", "--handoff"], cwd=git_repo, env=env).stdout
    assert "  - step one step two" in handoff_output

    run_output = _run_dock(["resume", "--run"], cwd=git_repo, env=env).stdout
    assert "$ echo run-one echo run-two -> exit 0" in run_output
    assert "$ e -> exit" not in run_output


def _seed_checkpoint_for_run(
    *,
    git_repo: Path,
    tmp_path: Path,
    objective: str,
    decisions: str,
    next_step: str,
    resume_commands: RunCommands,
) -> dict[str, str]:
    """Save a checkpoint with optional resume commands.

    Args:
        git_repo: Repository path for save command context.
        tmp_path: Temporary path used for Dockyard home.
        objective: Save objective text.
        decisions: Save decisions text.
        next_step: Save next-step text.
        resume_commands: Resume commands to persist with checkpoint.

    Returns:
        Environment mapping configured with Dockyard home.
    """
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    save_args = [
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
        "none",
    ]
    for command in resume_commands:
        save_args.extend(["--command", command])
    save_args.extend(
        [
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
    )

    _run_dock(save_args, cwd=git_repo, env=env)
    return env


def _assert_run_executes_commands_on_success(
    *,
    git_repo: Path,
    tmp_path: Path,
    objective: str,
    decisions: str,
    next_step: str,
    resume_commands: RunCommands,
    run_args: RunArgs,
    run_cwd: Path,
) -> None:
    """Assert that run mode executes each recorded command successfully."""
    env = _seed_checkpoint_for_run(
        git_repo=git_repo,
        tmp_path=tmp_path,
        objective=objective,
        decisions=decisions,
        next_step=next_step,
        resume_commands=resume_commands,
    )
    output = _run_dock(run_args, cwd=run_cwd, env=env).stdout
    for command in resume_commands:
        assert f"$ {command} -> exit 0" in output


def _assert_run_stops_on_first_failure(
    *,
    git_repo: Path,
    tmp_path: Path,
    objective: str,
    decisions: str,
    next_step: str,
    first_command: str,
    skipped_command: str,
    run_args: RunArgs,
    run_cwd: Path,
) -> None:
    """Assert that run mode stops executing commands at first failure."""
    env = _seed_checkpoint_for_run(
        git_repo=git_repo,
        tmp_path=tmp_path,
        objective=objective,
        decisions=decisions,
        next_step=next_step,
        resume_commands=[first_command, "false", skipped_command],
    )
    output = _run_dock(run_args, cwd=run_cwd, env=env, expect_code=1).stdout
    assert f"$ {first_command} -> exit 0" in output
    assert "$ false -> exit 1" in output
    assert f"$ {skipped_command} -> exit" not in output


def _assert_run_no_commands_noop(
    *,
    git_repo: Path,
    tmp_path: Path,
    objective: str,
    decisions: str,
    next_step: str,
    run_args: RunArgs,
    run_cwd: Path,
) -> None:
    """Seed checkpoint without commands and assert run path is no-op."""
    env = _seed_checkpoint_for_run(
        git_repo=git_repo,
        tmp_path=tmp_path,
        objective=objective,
        decisions=decisions,
        next_step=next_step,
        resume_commands=[],
    )
    result = _run_dock(run_args, cwd=run_cwd, env=env)
    assert "-> exit" not in result.stdout


def _assert_run_executes_commands_for_scope(
    *,
    git_repo: Path,
    tmp_path: Path,
    command_name: RunCommandName,
    include_berth: bool,
    include_branch: bool,
    run_cwd_kind: RunCwdKind,
    objective: str,
    decisions: str,
    next_step: str,
    resume_commands: RunCommands,
) -> None:
    """Assert scoped run mode executes recorded commands successfully."""
    branch = _git_current_branch(git_repo) if include_branch else None
    _assert_run_executes_commands_on_success(
        git_repo=git_repo,
        tmp_path=tmp_path,
        objective=objective,
        decisions=decisions,
        next_step=next_step,
        resume_commands=resume_commands,
        run_args=_build_run_args(
            command_name,
            git_repo=git_repo,
            branch=branch,
            include_berth=include_berth,
        ),
        run_cwd=_resolve_run_cwd(git_repo, tmp_path, run_cwd_kind),
    )


def _assert_run_stops_on_failure_for_scope(
    *,
    git_repo: Path,
    tmp_path: Path,
    command_name: RunCommandName,
    include_berth: bool,
    include_branch: bool,
    run_cwd_kind: RunCwdKind,
    objective: str,
    decisions: str,
    next_step: str,
    first_command: str,
    skipped_command: str,
) -> None:
    """Assert scoped run mode stops on first failing command."""
    branch = _git_current_branch(git_repo) if include_branch else None
    _assert_run_stops_on_first_failure(
        git_repo=git_repo,
        tmp_path=tmp_path,
        objective=objective,
        decisions=decisions,
        next_step=next_step,
        first_command=first_command,
        skipped_command=skipped_command,
        run_args=_build_run_args(
            command_name,
            git_repo=git_repo,
            branch=branch,
            include_berth=include_berth,
        ),
        run_cwd=_resolve_run_cwd(git_repo, tmp_path, run_cwd_kind),
    )


def _assert_run_no_commands_noop_for_scope(
    *,
    git_repo: Path,
    tmp_path: Path,
    command_name: RunCommandName,
    include_berth: bool,
    include_branch: bool,
    run_cwd_kind: RunCwdKind,
    objective: str,
    decisions: str,
    next_step: str,
) -> None:
    """Assert no-command run behavior for a scoped command variant.

    Args:
        git_repo: Repository path used for checkpoint save context.
        tmp_path: Temporary path used for Dockyard home and optional run cwd.
        command_name: Command token (resume/r/undock).
        include_berth: Whether run args should include trimmed berth selector.
        include_branch: Whether run args should include trimmed branch selector.
        run_cwd_kind: Selector for run command working directory.
        objective: Checkpoint objective text.
        decisions: Checkpoint decisions text.
        next_step: Checkpoint next-step text.
    """
    branch = _git_current_branch(git_repo) if include_branch else None
    _assert_run_no_commands_noop(
        git_repo=git_repo,
        tmp_path=tmp_path,
        objective=objective,
        decisions=decisions,
        next_step=next_step,
        run_args=_build_run_args(
            command_name,
            git_repo=git_repo,
            branch=branch,
            include_berth=include_berth,
        ),
        run_cwd=_resolve_run_cwd(git_repo, tmp_path, run_cwd_kind),
    )


@pytest.mark.parametrize(
    "case",
    RUN_NO_COMMAND_CASES,
    ids=RUN_NO_COMMAND_IDS,
)
def test_run_scopes_with_no_commands_are_noop_success(
    git_repo: Path,
    tmp_path: Path,
    case: RunNoCommandCaseMeta,
) -> None:
    """Run scope variants should no-op when no commands are recorded."""
    _assert_run_no_commands_noop_for_scope(
        git_repo=git_repo,
        tmp_path=tmp_path,
        command_name=case.command_name,
        include_berth=case.include_berth,
        include_branch=case.include_branch,
        run_cwd_kind=case.run_cwd_kind,
        objective=case.objective,
        decisions=case.decisions,
        next_step=case.next_step,
    )


def test_resume_run_skips_blank_command_entries(git_repo: Path, tmp_path: Path) -> None:
    """Resume --run should ignore blank entries and normalize command spacing."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Blank run command baseline",
            "--decisions",
            "Mutate run command payload with blank entries",
            "--next-step",
            "run resume --run",
            "--risks",
            "none",
            "--command",
            "echo keep-me",
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

    db_path = dock_home / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE checkpoints SET resume_commands_json = ?",
        (json.dumps(["   ", "\n\t", "  echo keep-me  "]),),
    )
    conn.commit()
    conn.close()

    output = _run_dock(["resume", "--run"], cwd=git_repo, env=env).stdout
    assert "$ echo keep-me -> exit 0" in output
    assert "$   echo keep-me   -> exit" not in output
    assert "$  -> exit" not in output


def test_resume_run_all_blank_commands_is_noop_success(git_repo: Path, tmp_path: Path) -> None:
    """Resume --run should no-op successfully when all commands are blank."""
    env = _seed_checkpoint_for_run(
        git_repo=git_repo,
        tmp_path=tmp_path,
        objective="All blank run commands",
        decisions="Rewrite commands payload to blank values",
        next_step="Run resume --run",
        resume_commands=["echo placeholder"],
    )

    db_path = Path(env["DOCKYARD_HOME"]) / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE checkpoints SET resume_commands_json = ?",
        (json.dumps(["   ", "\n\t", ""]),),
    )
    conn.commit()
    conn.close()

    output = _run_dock(["resume", "--run"], cwd=git_repo, env=env).stdout
    assert "-> exit" not in output


def test_resume_run_with_berth_executes_in_repo_root(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Resume --run with berth arg should execute commands in repo root."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Run from berth context",
            "--decisions",
            "Ensure execution cwd resolves from berth root path",
            "--next-step",
            "Run resume with berth outside repo",
            "--risks",
            "none",
            "--command",
            "pwd > run_pwd.txt",
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

    _run_dock(["resume", git_repo.name, "--run"], cwd=tmp_path, env=env)
    marker = git_repo / "run_pwd.txt"
    assert marker.exists()
    assert marker.read_text(encoding="utf-8").strip() == str(git_repo)


def test_resume_alias_run_with_berth_executes_in_repo_root(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Resume alias `r` with berth should execute commands in repo root."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Alias run from berth context",
            "--decisions",
            "Ensure alias execution cwd resolves from berth root path",
            "--next-step",
            "Run alias with berth outside repo",
            "--risks",
            "none",
            "--command",
            "pwd > run_pwd_alias_r.txt",
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

    _run_dock(["r", f"  {git_repo.name}  ", "--run"], cwd=tmp_path, env=env)
    marker = git_repo / "run_pwd_alias_r.txt"
    assert marker.exists()
    assert marker.read_text(encoding="utf-8").strip() == str(git_repo)


def test_undock_alias_run_with_berth_executes_in_repo_root(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Undock alias with berth should execute commands in repo root."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Undock run from berth context",
            "--decisions",
            "Ensure undock execution cwd resolves from berth root path",
            "--next-step",
            "Run undock with berth outside repo",
            "--risks",
            "none",
            "--command",
            "pwd > run_pwd_alias_undock.txt",
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

    _run_dock(["undock", f"  {git_repo.name}  ", "--run"], cwd=tmp_path, env=env)
    marker = git_repo / "run_pwd_alias_undock.txt"
    assert marker.exists()
    assert marker.read_text(encoding="utf-8").strip() == str(git_repo)


def test_resume_run_with_berth_missing_root_path_is_actionable(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Resume --run should fail cleanly when persisted berth root is missing."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Missing run root path objective",
            "--decisions",
            "Ensure run path validation is actionable",
            "--next-step",
            "Attempt resume --run with stale berth root",
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

    payload = json.loads(_run_dock(["resume", "--json"], cwd=git_repo, env=env).stdout)
    repo_id = payload["repo_id"]
    db_path = dock_home / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE berths SET root_path = ? WHERE repo_id = ?",
        (str(tmp_path / "missing-run-root"), repo_id),
    )
    conn.commit()
    conn.close()

    failed = _run_dock(["resume", git_repo.name, "--run"], cwd=tmp_path, env=env, expect_code=2)
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "Repository root for --run does not exist:" in output
    assert "Traceback" not in output


@pytest.mark.parametrize("command_name", ["r", "undock"])
def test_resume_alias_run_with_berth_missing_root_path_is_actionable(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Resume aliases should fail cleanly when persisted berth root is missing."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Missing alias run root path objective",
            "--decisions",
            "Ensure alias run path validation is actionable",
            "--next-step",
            "Attempt alias --run with stale berth root",
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

    payload = json.loads(_run_dock(["resume", "--json"], cwd=git_repo, env=env).stdout)
    repo_id = payload["repo_id"]
    db_path = dock_home / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE berths SET root_path = ? WHERE repo_id = ?",
        (str(tmp_path / f"missing-run-root-{command_name}"), repo_id),
    )
    conn.commit()
    conn.close()

    failed = _run_dock([command_name, git_repo.name, "--run"], cwd=tmp_path, env=env, expect_code=2)
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "Repository root for --run does not exist:" in output
    assert "Traceback" not in output


@pytest.mark.parametrize("command_name", ["resume", "r", "undock"])
def test_run_with_branch_and_missing_root_path_is_actionable(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Run-enabled resume commands should fail cleanly with branch + stale root."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)
    branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Missing branch-scoped run root path objective",
            "--decisions",
            "Ensure branch-scoped run path validation is actionable",
            "--next-step",
            "Attempt branch-scoped --run with stale berth root",
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

    payload = json.loads(_run_dock(["resume", "--json"], cwd=git_repo, env=env).stdout)
    repo_id = payload["repo_id"]
    db_path = dock_home / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE berths SET root_path = ? WHERE repo_id = ?",
        (str(tmp_path / f"missing-run-root-branch-{command_name}"), repo_id),
    )
    conn.commit()
    conn.close()

    failed = _run_dock(
        [command_name, git_repo.name, "--branch", branch, "--run"],
        cwd=tmp_path,
        env=env,
        expect_code=2,
    )
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "Repository root for --run does not exist:" in output
    assert "Traceback" not in output


def test_save_truncates_next_steps_and_commands_to_mvp_limits(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Save should cap next steps to 3 and resume commands to 5."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Truncation behavior",
            "--decisions",
            "Verify cap on next steps and commands",
            "--next-step",
            "step-1",
            "--next-step",
            "step-2",
            "--next-step",
            "step-3",
            "--next-step",
            "step-4",
            "--next-step",
            "step-5",
            "--risks",
            "none",
            "--command",
            "cmd-1",
            "--command",
            "cmd-2",
            "--command",
            "cmd-3",
            "--command",
            "cmd-4",
            "--command",
            "cmd-5",
            "--command",
            "cmd-6",
            "--command",
            "cmd-7",
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

    payload = json.loads(_run_dock(["resume", "--json"], cwd=git_repo, env=env).stdout)
    assert payload["next_steps"] == ["step-1", "step-2", "step-3"]
    assert payload["resume_commands"] == ["cmd-1", "cmd-2", "cmd-3", "cmd-4", "cmd-5"]


def test_save_normalizes_tag_and_link_values(git_repo: Path, tmp_path: Path) -> None:
    """Save should trim and de-duplicate tag/link values."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Tag/link normalization objective",
            "--decisions",
            "Trim and de-duplicate save tag/link values",
            "--next-step",
            "run normalized filters",
            "--risks",
            "none",
            "--command",
            "echo normalized",
            "--tag",
            " alpha ",
            "--tag",
            "alpha",
            "--tag",
            "   ",
            "--tag",
            "beta",
            "--link",
            " https://example.com/trimmed ",
            "--link",
            "https://example.com/trimmed",
            "--link",
            "   ",
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

    alpha_rows = json.loads(_run_dock(["ls", "--tag", "alpha", "--json"], cwd=tmp_path, env=env).stdout)
    beta_rows = json.loads(_run_dock(["ls", "--tag", "beta", "--json"], cwd=tmp_path, env=env).stdout)
    assert len(alpha_rows) == 1
    assert len(beta_rows) == 1
    assert "alpha " not in json.dumps(alpha_rows, ensure_ascii=False)

    links_output = _run_dock(["links"], cwd=git_repo, env=env).stdout
    assert links_output.count("https://example.com/trimmed") == 1
    assert " https://example.com/trimmed " not in links_output


def test_error_output_has_no_traceback(tmp_path: Path) -> None:
    """Dockyard user-facing errors should be actionable without traceback spam."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    result = _run_dock(["resume"], cwd=tmp_path, env=env, expect_code=2)
    output = f"{result.stdout}\n{result.stderr}"
    assert "Error:" in output
    assert "Traceback" not in output


def test_resume_unknown_berth_is_actionable(tmp_path: Path) -> None:
    """Unknown berth resume should fail cleanly with guidance."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    result = _run_dock(["resume", "missing-berth"], cwd=tmp_path, env=env, expect_code=2)
    output = f"{result.stdout}\n{result.stderr}"
    assert "Unknown berth: missing-berth" in output
    assert "Traceback" not in output


@pytest.mark.parametrize("command_name", ["r", "undock"])
def test_resume_alias_unknown_berth_is_actionable(
    tmp_path: Path,
    command_name: str,
) -> None:
    """Resume aliases should fail cleanly for unknown berth names."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    result = _run_dock([command_name, "missing-berth"], cwd=tmp_path, env=env, expect_code=2)
    output = f"{result.stdout}\n{result.stderr}"
    assert "Unknown berth: missing-berth" in output
    assert "Traceback" not in output


@pytest.mark.parametrize("command_name", ["resume", "r", "undock"])
@pytest.mark.parametrize("output_flag", ["", "--json", "--handoff"], ids=["default", "json", "handoff"])
def test_resume_unknown_berth_output_modes_are_actionable(
    tmp_path: Path,
    command_name: str,
    output_flag: str,
) -> None:
    """Unknown-berth failures should stay actionable across output modes."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    args = [command_name, "missing-berth"]
    if output_flag:
        args.append(output_flag)

    result = _run_dock(args, cwd=tmp_path, env=env, expect_code=2)
    output = f"{result.stdout}\n{result.stderr}"
    assert "Unknown berth: missing-berth" in output
    assert "Traceback" not in output


def test_resume_unknown_berth_preserves_literal_markup_text(tmp_path: Path) -> None:
    """Unknown-berth errors should preserve literal bracketed tokens."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    result = _run_dock(["resume", "[red]missing[/red]"], cwd=tmp_path, env=env, expect_code=2)
    output = f"{result.stdout}\n{result.stderr}"
    assert "Unknown berth: [red]missing[/red]" in output
    assert "Traceback" not in output


@pytest.mark.parametrize("command_name", ["r", "undock"])
def test_resume_alias_unknown_berth_preserves_literal_markup_text(
    tmp_path: Path,
    command_name: str,
) -> None:
    """Resume aliases should preserve literal bracketed tokens in berth errors."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    result = _run_dock([command_name, "[red]missing[/red]"], cwd=tmp_path, env=env, expect_code=2)
    output = f"{result.stdout}\n{result.stderr}"
    assert "Unknown berth: [red]missing[/red]" in output
    assert "Traceback" not in output


@pytest.mark.parametrize("command_name", ["resume", "r", "undock"])
@pytest.mark.parametrize("output_flag", ["", "--json", "--handoff"], ids=["default", "json", "handoff"])
def test_resume_unknown_berth_literal_markup_output_modes_preserved(
    tmp_path: Path,
    command_name: str,
    output_flag: str,
) -> None:
    """Literal markup text in unknown-berth errors should survive output modes."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    args = [command_name, "[red]missing[/red]"]
    if output_flag:
        args.append(output_flag)

    result = _run_dock(args, cwd=tmp_path, env=env, expect_code=2)
    output = f"{result.stdout}\n{result.stderr}"
    assert "Unknown berth: [red]missing[/red]" in output
    assert "Traceback" not in output


def test_resume_rejects_blank_berth_argument(tmp_path: Path) -> None:
    """Resume should reject blank berth argument values."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    result = _run_dock(["resume", "   "], cwd=tmp_path, env=env, expect_code=2)
    output = f"{result.stdout}\n{result.stderr}"
    assert "Berth must be a non-empty string." in output
    assert "Traceback" not in output


def test_resume_alias_rejects_blank_berth_argument(tmp_path: Path) -> None:
    """Resume alias should reject blank berth argument values."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    result = _run_dock(["r", "   "], cwd=tmp_path, env=env, expect_code=2)
    output = f"{result.stdout}\n{result.stderr}"
    assert "Berth must be a non-empty string." in output
    assert "Traceback" not in output


def test_undock_rejects_blank_berth_argument(tmp_path: Path) -> None:
    """Undock alias should reject blank berth argument values."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    result = _run_dock(["undock", "   "], cwd=tmp_path, env=env, expect_code=2)
    output = f"{result.stdout}\n{result.stderr}"
    assert "Berth must be a non-empty string." in output
    assert "Traceback" not in output


@pytest.mark.parametrize("command_name", ["resume", "r", "undock"])
@pytest.mark.parametrize("output_flag", ["", "--json", "--handoff"], ids=["default", "json", "handoff"])
def test_resume_blank_berth_output_modes_are_rejected(
    tmp_path: Path,
    command_name: str,
    output_flag: str,
) -> None:
    """Blank berth arguments should be rejected across output modes."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    args = [command_name, "   "]
    if output_flag:
        args.append(output_flag)

    result = _run_dock(args, cwd=tmp_path, env=env, expect_code=2)
    output = f"{result.stdout}\n{result.stderr}"
    assert "Berth must be a non-empty string." in output
    assert "Traceback" not in output


def test_resume_rejects_blank_branch_option(git_repo: Path, tmp_path: Path) -> None:
    """Resume should reject blank --branch option values."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    failed = _run_dock(["resume", "--branch", "   "], cwd=git_repo, env=env, expect_code=2)
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "--branch must be a non-empty string." in output
    assert "Traceback" not in output


def test_resume_alias_rejects_blank_branch_option(git_repo: Path, tmp_path: Path) -> None:
    """Resume alias should reject blank --branch option values."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    failed = _run_dock(["r", "--branch", "   "], cwd=git_repo, env=env, expect_code=2)
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "--branch must be a non-empty string." in output
    assert "Traceback" not in output


def test_resume_alias_branch_flag_accepts_trimmed_value(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Resume alias should resolve --branch values after trimming."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Alias trimmed branch objective",
            "--decisions",
            "Resolve alias branch values with surrounding whitespace",
            "--next-step",
            "resume alias with branch",
            "--risks",
            "none",
            "--command",
            "echo alias-branch",
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

    selected = json.loads(
        _run_dock(["r", "--branch", f"  {branch}  ", "--json"], cwd=git_repo, env=env).stdout
    )
    assert selected["branch"] == branch
    assert selected["objective"] == "Alias trimmed branch objective"


def test_no_subcommand_defaults_to_harbor(git_repo: Path, tmp_path: Path) -> None:
    """Invoking dockyard without subcommand should run harbor listing."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Seed default listing",
            "--decisions",
            "Need default command behavior",
            "--next-step",
            "Run bare dock command",
            "--risks",
            "None",
            "--command",
            "echo ok",
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

    result = _run_dock([], cwd=tmp_path, env=env)
    assert "Dockyard Harbor" in result.stdout


def test_root_help_includes_no_subcommand_ls_flags(tmp_path: Path) -> None:
    """Root help should advertise ls-style flags for bare callback usage."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    result = _run_dock(["--help"], cwd=tmp_path, env=env)
    help_text = result.stdout
    assert "--stale" in help_text
    assert "--tag" in help_text
    assert "--limit" in help_text
    assert "--json" in help_text


def test_no_subcommand_json_empty_store_returns_array(tmp_path: Path) -> None:
    """Bare dock JSON mode should return [] for an empty dataset."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    payload = json.loads(_run_dock(["--json"], cwd=tmp_path, env=env).stdout)
    assert payload == []


def test_no_subcommand_supports_ls_flags(git_repo: Path, tmp_path: Path) -> None:
    """Bare dock invocation should honor ls-style filter/output flags."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Default callback flag parity",
            "--decisions",
            "Support bare command ls flags",
            "--next-step",
            "run bare dock json with filters",
            "--risks",
            "none",
            "--command",
            "echo noop",
            "--tag",
            "callback-flags",
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

    payload = json.loads(
        _run_dock(["--json", "--tag", "callback-flags", "--limit", "1"], cwd=tmp_path, env=env).stdout
    )
    assert len(payload) == 1
    assert payload[0]["objective"] == "Default callback flag parity"
    assert "callback-flags" in payload[0]["tags"]


def test_no_subcommand_supports_stale_flag(git_repo: Path, tmp_path: Path) -> None:
    """Bare dock invocation should accept stale filter flag like ls."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Default callback stale flag parity",
            "--decisions",
            "Support bare command stale flag",
            "--next-step",
            "run bare dock stale filter",
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

    payload = json.loads(_run_dock(["--json", "--stale", "0"], cwd=tmp_path, env=env).stdout)
    assert len(payload) == 1
    assert payload[0]["objective"] == "Default callback stale flag parity"


def test_no_subcommand_supports_stale_flag_in_repo_context(git_repo: Path, tmp_path: Path) -> None:
    """Bare dock invocation should honor stale filter flag from repo cwd."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Default callback stale flag parity in repo",
            "--decisions",
            "Support bare command stale flag from repo cwd",
            "--next-step",
            "run bare dock stale filter from repo",
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

    payload = json.loads(_run_dock(["--json", "--stale", "0"], cwd=git_repo, env=env).stdout)
    assert len(payload) == 1
    assert payload[0]["objective"] == "Default callback stale flag parity in repo"


def test_no_subcommand_rejects_invalid_stale_flag(tmp_path: Path) -> None:
    """Bare dock invocation should validate stale option bounds."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    failed = _run_dock(["--stale", "-1"], cwd=tmp_path, env=env, expect_code=2)
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "--stale must be >= 0." in output
    assert "Traceback" not in output


def test_no_subcommand_rejects_invalid_limit_flag(tmp_path: Path) -> None:
    """Bare dock invocation should validate limit option bounds."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    failed = _run_dock(["--limit", "0"], cwd=tmp_path, env=env, expect_code=2)
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "--limit must be >= 1." in output
    assert "Traceback" not in output


def test_no_subcommand_rejects_blank_tag_filter(tmp_path: Path) -> None:
    """Bare dock invocation should reject blank tag filter values."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    failed = _run_dock(["--tag", "   "], cwd=tmp_path, env=env, expect_code=2)
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "--tag must be a non-empty string." in output
    assert "Traceback" not in output


@pytest.mark.parametrize(
    ("args", "expected_fragment"),
    [
        (("--tag", "alpha", "--stale", "-1", "--limit", "1"), "--stale must be >= 0."),
        (("--tag", "alpha", "--stale", "0", "--limit", "0"), "--limit must be >= 1."),
        (("--tag", "   ", "--stale", "0", "--limit", "1"), "--tag must be a non-empty string."),
    ],
)
def test_no_subcommand_rejects_invalid_combined_filters(
    tmp_path: Path,
    args: tuple[str, ...],
    expected_fragment: str,
) -> None:
    """Bare dock should reject invalid values in combined filter sets."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    failed = _run_dock(list(args), cwd=tmp_path, env=env, expect_code=2)
    output = f"{failed.stdout}\n{failed.stderr}"
    assert expected_fragment in output
    assert "Traceback" not in output


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
def test_no_subcommand_rejects_invalid_filters_in_repo_context(
    git_repo: Path,
    tmp_path: Path,
    args: tuple[str, ...],
    expected_fragment: str,
) -> None:
    """Bare dock invalid-filter validation should match in-repo behavior."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    failed = _run_dock(list(args), cwd=git_repo, env=env, expect_code=2)
    output = f"{failed.stdout}\n{failed.stderr}"
    assert expected_fragment in output
    assert "Traceback" not in output


def test_no_subcommand_trims_tag_filter(git_repo: Path, tmp_path: Path) -> None:
    """Bare dock invocation should trim tag filter values before lookup."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Default callback trimmed tag parity",
            "--decisions",
            "Trim tag value in bare callback path",
            "--next-step",
            "run bare dock with trimmed tag",
            "--risks",
            "none",
            "--command",
            "echo noop",
            "--tag",
            "alpha",
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

    rows = json.loads(_run_dock(["--json", "--tag", "  alpha  "], cwd=tmp_path, env=env).stdout)
    assert len(rows) == 1
    assert rows[0]["objective"] == "Default callback trimmed tag parity"


def test_no_subcommand_supports_combined_tag_stale_filters(git_repo: Path, tmp_path: Path) -> None:
    """Bare dock callback should honor combined tag and stale filters."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    base_branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Default callback combined filters alpha",
            "--decisions",
            "Validate combined tag/stale filters",
            "--next-step",
            "run bare dock combined filters alpha",
            "--risks",
            "none",
            "--command",
            "echo alpha",
            "--tag",
            "alpha",
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
    subprocess.run(
        ["git", "checkout", "-b", "feature/no-subcommand-combined-filter"],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Default callback combined filters beta",
            "--decisions",
            "Ensure other tag is filtered out",
            "--next-step",
            "run bare dock combined filters beta",
            "--risks",
            "none",
            "--command",
            "echo beta",
            "--tag",
            "beta",
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
    subprocess.run(["git", "checkout", base_branch], cwd=str(git_repo), check=True, capture_output=True)

    rows = json.loads(_run_dock(["--json", "--tag", "alpha", "--stale", "0"], cwd=tmp_path, env=env).stdout)
    assert len(rows) == 1
    assert rows[0]["objective"] == "Default callback combined filters alpha"
    assert "alpha" in rows[0]["tags"]
    table_output = _run_dock(["--tag", "alpha", "--stale", "0"], cwd=tmp_path, env=env).stdout
    assert "Dockyard Harbor" in table_output
    assert base_branch in table_output
    assert "feature/no-subcommand-combined-filter" not in table_output
    assert "No checkpoints yet." not in table_output
    assert "Traceback" not in table_output


def test_no_subcommand_supports_combined_tag_stale_filters_in_repo_context(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Bare callback should honor tag+stale filters when run in repo cwd."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    base_branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Default callback combined filters alpha in repo",
            "--decisions",
            "Validate combined tag/stale filters in repo context",
            "--next-step",
            "run bare dock combined filters alpha in repo",
            "--risks",
            "none",
            "--command",
            "echo alpha",
            "--tag",
            "alpha",
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
    subprocess.run(
        ["git", "checkout", "-b", "feature/no-subcommand-combined-filter-in-repo"],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Default callback combined filters beta in repo",
            "--decisions",
            "Ensure other tag is filtered out in repo context",
            "--next-step",
            "run bare dock combined filters beta in repo",
            "--risks",
            "none",
            "--command",
            "echo beta",
            "--tag",
            "beta",
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
    subprocess.run(["git", "checkout", base_branch], cwd=str(git_repo), check=True, capture_output=True)

    rows = json.loads(_run_dock(["--json", "--tag", "alpha", "--stale", "0"], cwd=git_repo, env=env).stdout)
    assert len(rows) == 1
    assert rows[0]["objective"] == "Default callback combined filters alpha in repo"
    assert "alpha" in rows[0]["tags"]
    table_output = _run_dock(["--tag", "alpha", "--stale", "0"], cwd=git_repo, env=env).stdout
    assert "Dockyard Harbor" in table_output
    assert base_branch in table_output
    assert "feature/no-subcommand-combined-filter-in-repo" not in table_output
    assert "No checkpoints yet." not in table_output
    assert "Traceback" not in table_output


def test_no_subcommand_supports_combined_tag_stale_limit_filters(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Bare callback should honor combined tag/stale/limit constraints."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    base_branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Default callback combined filter limit alpha base",
            "--decisions",
            "Validate combined tag/stale/limit filters (base branch)",
            "--next-step",
            "run bare dock combined filters with limit",
            "--risks",
            "none",
            "--command",
            "echo alpha-base",
            "--tag",
            "alpha",
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
    subprocess.run(
        ["git", "checkout", "-b", "feature/no-subcommand-combined-filter-limit"],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Default callback combined filter limit alpha feature",
            "--decisions",
            "Second alpha entry should be pruned by limit",
            "--next-step",
            "validate combined filters with limit",
            "--risks",
            "none",
            "--command",
            "echo alpha-feature",
            "--tag",
            "alpha",
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
    subprocess.run(["git", "checkout", base_branch], cwd=str(git_repo), check=True, capture_output=True)

    rows = json.loads(
        _run_dock(
            ["--json", "--tag", "alpha", "--stale", "0", "--limit", "1"],
            cwd=tmp_path,
            env=env,
        ).stdout
    )
    assert len(rows) == 1
    assert rows[0]["objective"] in {
        "Default callback combined filter limit alpha base",
        "Default callback combined filter limit alpha feature",
    }
    assert "alpha" in rows[0]["tags"]
    table_output = _run_dock(["--tag", "alpha", "--limit", "1"], cwd=tmp_path, env=env).stdout
    shows_base_branch = base_branch in table_output
    shows_feature_branch = "feature/no-subcommand-combined-filter-limit" in table_output
    assert shows_base_branch ^ shows_feature_branch
    assert "No checkpoints yet." not in table_output
    assert "Traceback" not in table_output


def test_no_subcommand_supports_combined_tag_stale_limit_filters_in_repo_context(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Bare callback should honor tag+stale+limit in repo cwd."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    base_branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Default callback combined filter limit alpha base in repo",
            "--decisions",
            "Validate combined tag/stale/limit filters in repo (base branch)",
            "--next-step",
            "run bare dock combined filters with limit in repo",
            "--risks",
            "none",
            "--command",
            "echo alpha-base",
            "--tag",
            "alpha",
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
    subprocess.run(
        ["git", "checkout", "-b", "feature/no-subcommand-combined-filter-limit-in-repo"],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Default callback combined filter limit alpha feature in repo",
            "--decisions",
            "Second alpha entry should be pruned by limit in repo context",
            "--next-step",
            "validate combined filters with limit in repo",
            "--risks",
            "none",
            "--command",
            "echo alpha-feature",
            "--tag",
            "alpha",
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
    subprocess.run(["git", "checkout", base_branch], cwd=str(git_repo), check=True, capture_output=True)

    rows = json.loads(
        _run_dock(
            ["--json", "--tag", "alpha", "--stale", "0", "--limit", "1"],
            cwd=git_repo,
            env=env,
        ).stdout
    )
    assert len(rows) == 1
    assert rows[0]["objective"] in {
        "Default callback combined filter limit alpha base in repo",
        "Default callback combined filter limit alpha feature in repo",
    }
    assert "alpha" in rows[0]["tags"]
    table_output = _run_dock(["--tag", "alpha", "--stale", "0", "--limit", "1"], cwd=git_repo, env=env).stdout
    shows_base_branch = base_branch in table_output
    shows_feature_branch = "feature/no-subcommand-combined-filter-limit-in-repo" in table_output
    assert shows_base_branch ^ shows_feature_branch
    assert "No checkpoints yet." not in table_output
    assert "Traceback" not in table_output


def test_no_subcommand_tag_filter_no_match_is_informative(git_repo: Path, tmp_path: Path) -> None:
    """Bare callback should handle missing tag filters cleanly."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Default callback missing tag baseline",
            "--decisions",
            "ensure callback no-match semantics are stable",
            "--next-step",
            "run bare dock with missing tag filter",
            "--risks",
            "none",
            "--command",
            "echo alpha-base",
            "--tag",
            "alpha",
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

    table_output = _run_dock(["--tag", "missing-tag"], cwd=tmp_path, env=env)
    assert "Dockyard Harbor" in table_output.stdout
    assert "Default callback missing tag baseline" not in table_output.stdout
    assert "Traceback" not in f"{table_output.stdout}\n{table_output.stderr}"

    json_output = _run_dock(["--tag", "missing-tag", "--json"], cwd=tmp_path, env=env)
    assert json.loads(json_output.stdout) == []
    assert "Traceback" not in f"{json_output.stdout}\n{json_output.stderr}"


def test_no_subcommand_tag_filter_no_match_is_informative_in_repo(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Bare callback should handle missing tag filters in repository cwd."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Default callback missing tag baseline in repo",
            "--decisions",
            "ensure in-repo callback no-match semantics stay stable",
            "--next-step",
            "run bare dock with missing tag filter in repo",
            "--risks",
            "none",
            "--command",
            "echo alpha-base",
            "--tag",
            "alpha",
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

    table_output = _run_dock(["--tag", "missing-tag"], cwd=git_repo, env=env)
    assert "Dockyard Harbor" in table_output.stdout
    assert "Default callback missing tag baseline in repo" not in table_output.stdout
    assert "Traceback" not in f"{table_output.stdout}\n{table_output.stderr}"

    json_output = _run_dock(["--tag", "missing-tag", "--json"], cwd=git_repo, env=env)
    assert json.loads(json_output.stdout) == []
    assert "Traceback" not in f"{json_output.stdout}\n{json_output.stderr}"


def test_no_subcommand_tag_filter_no_match_with_limit_is_informative_in_repo(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Bare callback should handle missing tag+limit filters in repo cwd."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Default callback missing tag+limit baseline in repo",
            "--decisions",
            "ensure in-repo callback no-match semantics stay stable",
            "--next-step",
            "run bare dock with missing tag+limit filter in repo",
            "--risks",
            "none",
            "--command",
            "echo alpha-base",
            "--tag",
            "alpha",
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

    table_output = _run_dock(["--tag", "missing-tag", "--limit", "1"], cwd=git_repo, env=env)
    assert "Dockyard Harbor" in table_output.stdout
    assert "Default callback missing tag+limit baseline in repo" not in table_output.stdout
    assert "Traceback" not in f"{table_output.stdout}\n{table_output.stderr}"

    json_output = _run_dock(["--tag", "missing-tag", "--limit", "1", "--json"], cwd=git_repo, env=env)
    assert json.loads(json_output.stdout) == []
    assert "Traceback" not in f"{json_output.stdout}\n{json_output.stderr}"


def test_no_subcommand_tag_filter_no_match_with_stale_is_informative_in_repo(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Bare callback should handle missing tag+stale filters in repo cwd."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Default callback missing tag+stale baseline in repo",
            "--decisions",
            "ensure in-repo callback no-match stale semantics stay stable",
            "--next-step",
            "run bare dock with missing tag+stale filter in repo",
            "--risks",
            "none",
            "--command",
            "echo alpha-base",
            "--tag",
            "alpha",
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

    table_output = _run_dock(
        ["--tag", "missing-tag", "--stale", "0"],
        cwd=git_repo,
        env=env,
    )
    assert "Dockyard Harbor" in table_output.stdout
    assert "Default callback missing tag+stale baseline in repo" not in table_output.stdout
    assert "Traceback" not in f"{table_output.stdout}\n{table_output.stderr}"

    json_output = _run_dock(
        ["--tag", "missing-tag", "--stale", "0", "--json"],
        cwd=git_repo,
        env=env,
    )
    assert json.loads(json_output.stdout) == []
    assert "Traceback" not in f"{json_output.stdout}\n{json_output.stderr}"


def test_no_subcommand_tag_filter_no_match_with_stale_limit_is_informative_in_repo(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Bare callback should handle missing tag+stale+limit filters in repo cwd."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Default callback missing tag+stale+limit baseline in repo",
            "--decisions",
            "ensure in-repo callback no-match stale semantics stay stable",
            "--next-step",
            "run bare dock with missing tag+stale+limit filter in repo",
            "--risks",
            "none",
            "--command",
            "echo alpha-base",
            "--tag",
            "alpha",
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

    table_output = _run_dock(
        ["--tag", "missing-tag", "--stale", "0", "--limit", "1"],
        cwd=git_repo,
        env=env,
    )
    assert "Dockyard Harbor" in table_output.stdout
    assert "Default callback missing tag+stale+limit baseline in repo" not in table_output.stdout
    assert "Traceback" not in f"{table_output.stdout}\n{table_output.stderr}"

    json_output = _run_dock(
        ["--tag", "missing-tag", "--stale", "0", "--limit", "1", "--json"],
        cwd=git_repo,
        env=env,
    )
    assert json.loads(json_output.stdout) == []
    assert "Traceback" not in f"{json_output.stdout}\n{json_output.stderr}"


def test_harbor_json_empty_store_returns_array(tmp_path: Path) -> None:
    """Harbor alias should support JSON mode for empty datasets."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    payload = json.loads(_run_dock(["harbor", "--json"], cwd=tmp_path, env=env).stdout)
    assert payload == []


def test_ls_json_empty_store_returns_array(tmp_path: Path) -> None:
    """Primary ls command should return [] for empty JSON output."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    payload = json.loads(_run_dock(["ls", "--json"], cwd=tmp_path, env=env).stdout)
    assert payload == []


def test_ls_json_handles_long_objective_text(git_repo: Path, tmp_path: Path) -> None:
    """Ls JSON output should remain parseable with long objective text."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    long_objective = "objtoken " + ("y" * 500)
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            long_objective,
            "--decisions",
            "long objective regression",
            "--next-step",
            "run ls json",
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

    rows = json.loads(_run_dock(["ls", "--json"], cwd=tmp_path, env=env).stdout)
    assert len(rows) >= 1
    assert long_objective in [row["objective"] for row in rows]
    harbor_rows = json.loads(_run_dock(["harbor", "--json"], cwd=tmp_path, env=env).stdout)
    assert long_objective in [row["objective"] for row in harbor_rows]
    callback_rows = json.loads(_run_dock(["--json"], cwd=tmp_path, env=env).stdout)
    assert long_objective in [row["objective"] for row in callback_rows]


def test_ls_json_preserves_unicode_objective(git_repo: Path, tmp_path: Path) -> None:
    """Ls JSON output should preserve unicode objective text."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    unicode_objective = "Unicode objective: façade safety"
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            unicode_objective,
            "--decisions",
            "unicode ls regression",
            "--next-step",
            "run ls json",
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

    rows = json.loads(_run_dock(["ls", "--json"], cwd=tmp_path, env=env).stdout)
    assert unicode_objective in [row["objective"] for row in rows]
    harbor_rows = json.loads(_run_dock(["harbor", "--json"], cwd=tmp_path, env=env).stdout)
    assert unicode_objective in [row["objective"] for row in harbor_rows]
    callback_rows = json.loads(_run_dock(["--json"], cwd=tmp_path, env=env).stdout)
    assert unicode_objective in [row["objective"] for row in callback_rows]


def test_ls_json_preserves_multiline_objective(git_repo: Path, tmp_path: Path) -> None:
    """Ls JSON should preserve multiline objective text without parse issues."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    multiline_objective = "line one\nline two"
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            multiline_objective,
            "--decisions",
            "multiline objective regression",
            "--next-step",
            "run ls json",
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

    rows = json.loads(_run_dock(["ls", "--json"], cwd=tmp_path, env=env).stdout)
    assert multiline_objective in [row["objective"] for row in rows]
    harbor_rows = json.loads(_run_dock(["harbor", "--json"], cwd=tmp_path, env=env).stdout)
    assert multiline_objective in [row["objective"] for row in harbor_rows]
    callback_rows = json.loads(_run_dock(["--json"], cwd=tmp_path, env=env).stdout)
    assert multiline_objective in [row["objective"] for row in callback_rows]


def test_harbor_json_preserves_multiline_next_steps(git_repo: Path, tmp_path: Path) -> None:
    """Harbor and callback JSON should preserve multiline next-step entries."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    objective = "Multiline next steps harbor json"
    multiline_next_step = "line one\nline two"
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            objective,
            "--decisions",
            "multiline next-step regression",
            "--next-step",
            multiline_next_step,
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

    ls_rows = json.loads(_run_dock(["ls", "--json"], cwd=tmp_path, env=env).stdout)
    harbor_rows = json.loads(_run_dock(["harbor", "--json"], cwd=tmp_path, env=env).stdout)
    callback_rows = json.loads(_run_dock(["--json"], cwd=tmp_path, env=env).stdout)

    ls_target = next(row for row in ls_rows if row.get("objective") == objective)
    harbor_target = next(row for row in harbor_rows if row.get("objective") == objective)
    callback_target = next(row for row in callback_rows if row.get("objective") == objective)
    assert multiline_next_step in ls_target.get("next_steps", [])
    assert multiline_next_step in harbor_target.get("next_steps", [])
    assert multiline_next_step in callback_target.get("next_steps", [])


def test_harbor_json_preserves_unicode_next_steps(git_repo: Path, tmp_path: Path) -> None:
    """Dashboard JSON paths should preserve unicode next-step entries."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    objective = "Unicode next steps harbor json"
    unicode_next_step = "Validate façade before mañana handoff"
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            objective,
            "--decisions",
            "unicode next-step regression",
            "--next-step",
            unicode_next_step,
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

    ls_rows = json.loads(_run_dock(["ls", "--json"], cwd=tmp_path, env=env).stdout)
    harbor_rows = json.loads(_run_dock(["harbor", "--json"], cwd=tmp_path, env=env).stdout)
    callback_rows = json.loads(_run_dock(["--json"], cwd=tmp_path, env=env).stdout)

    ls_target = next(row for row in ls_rows if row.get("objective") == objective)
    harbor_target = next(row for row in harbor_rows if row.get("objective") == objective)
    callback_target = next(row for row in callback_rows if row.get("objective") == objective)
    assert unicode_next_step in ls_target.get("next_steps", [])
    assert unicode_next_step in harbor_target.get("next_steps", [])
    assert unicode_next_step in callback_target.get("next_steps", [])


def test_harbor_alias_supports_tag_filter(git_repo: Path, tmp_path: Path) -> None:
    """Harbor alias should honor tag filtering like ls."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Harbor tag filter objective",
            "--decisions",
            "Use harbor alias with tag filter",
            "--next-step",
            "run harbor alias",
            "--risks",
            "none",
            "--command",
            "echo noop",
            "--tag",
            "harbor-tag",
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

    rows = json.loads(_run_dock(["harbor", "--tag", "harbor-tag", "--json"], cwd=tmp_path, env=env).stdout)
    assert len(rows) == 1
    assert "harbor-tag" in rows[0]["tags"]


def test_harbor_alias_tag_filter_applies_before_limit(git_repo: Path, tmp_path: Path) -> None:
    """Harbor alias should apply tag filtering before --limit truncation."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    base_branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "harbor-limit-tagged",
            "--decisions",
            "tagged harbor baseline",
            "--next-step",
            "run harbor tag+limit",
            "--risks",
            "none",
            "--command",
            "echo tagged",
            "--tag",
            "alpha",
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
    subprocess.run(
        ["git", "checkout", "-b", "feature/harbor-tag-limit"],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "harbor-limit-untagged",
            "--decisions",
            "newer untagged harbor row should be filtered before limit",
            "--next-step",
            "run harbor tag+limit",
            "--risks",
            "none",
            "--command",
            "echo untagged",
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
    subprocess.run(
        ["git", "checkout", base_branch],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )

    rows = json.loads(_run_dock(["harbor", "--tag", "alpha", "--limit", "1", "--json"], cwd=tmp_path, env=env).stdout)
    assert len(rows) == 1
    assert rows[0]["objective"] == "harbor-limit-tagged"

    output = _run_dock(["harbor", "--tag", "alpha", "--limit", "1"], cwd=tmp_path, env=env).stdout
    assert base_branch in output
    assert "feature/harbor-tag-limit" not in output
    assert "No checkpoints yet." not in output
    assert "Traceback" not in output


def test_harbor_alias_tag_filter_no_match_is_informative(git_repo: Path, tmp_path: Path) -> None:
    """Harbor alias should show empty guidance for missing tag filters."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Harbor tag no-match objective",
            "--decisions",
            "harbor tag no-match baseline",
            "--next-step",
            "run harbor tag no-match",
            "--risks",
            "none",
            "--command",
            "echo noop",
            "--tag",
            "alpha",
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

    table_output = _run_dock(["harbor", "--tag", "missing-tag"], cwd=tmp_path, env=env)
    assert "Dockyard Harbor" in table_output.stdout
    assert "Harbor tag no-match objective" not in table_output.stdout
    assert "Traceback" not in f"{table_output.stdout}\n{table_output.stderr}"

    json_output = _run_dock(["harbor", "--tag", "missing-tag", "--json"], cwd=tmp_path, env=env)
    assert json.loads(json_output.stdout) == []
    assert "Traceback" not in f"{json_output.stdout}\n{json_output.stderr}"


@pytest.mark.parametrize(
    ("command_prefix", "label"),
    [
        (["ls"], "ls"),
        (["harbor"], "harbor"),
        ([], "callback"),
    ],
)
def test_dashboard_tag_filter_no_match_is_informative(
    git_repo: Path,
    tmp_path: Path,
    command_prefix: list[str],
    label: str,
) -> None:
    """Dashboard commands should handle missing tag filters cleanly."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"Dashboard {label} tag no-match objective",
            "--decisions",
            "dashboard tag no-match baseline",
            "--next-step",
            "run dashboard tag no-match",
            "--risks",
            "none",
            "--command",
            "echo noop",
            "--tag",
            "alpha",
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

    table_output = _run_dock([*command_prefix, "--tag", "missing-tag"], cwd=tmp_path, env=env)
    assert "Dockyard Harbor" in table_output.stdout
    assert f"Dashboard {label} tag no-match objective" not in table_output.stdout
    assert "Traceback" not in f"{table_output.stdout}\n{table_output.stderr}"

    json_output = _run_dock([*command_prefix, "--tag", "missing-tag", "--json"], cwd=tmp_path, env=env)
    assert json.loads(json_output.stdout) == []
    assert "Traceback" not in f"{json_output.stdout}\n{json_output.stderr}"


@pytest.mark.parametrize(
    ("command_prefix", "label"),
    [
        (["ls"], "ls"),
        (["harbor"], "harbor"),
        ([], "callback"),
    ],
)
def test_dashboard_tag_filter_no_match_with_limit_is_informative(
    git_repo: Path,
    tmp_path: Path,
    command_prefix: list[str],
    label: str,
) -> None:
    """Dashboard commands should stay informative for tag misses with limit."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"Dashboard {label} tag limit no-match objective",
            "--decisions",
            "dashboard tag+limit no-match baseline",
            "--next-step",
            "run dashboard tag+limit no-match",
            "--risks",
            "none",
            "--command",
            "echo noop",
            "--tag",
            "alpha",
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

    table_output = _run_dock(
        [*command_prefix, "--tag", "missing-tag", "--limit", "1"],
        cwd=tmp_path,
        env=env,
    )
    assert "Dockyard Harbor" in table_output.stdout
    assert f"Dashboard {label} tag limit no-match objective" not in table_output.stdout
    assert "Traceback" not in f"{table_output.stdout}\n{table_output.stderr}"

    json_output = _run_dock(
        [*command_prefix, "--tag", "missing-tag", "--limit", "1", "--json"],
        cwd=tmp_path,
        env=env,
    )
    assert json.loads(json_output.stdout) == []
    assert "Traceback" not in f"{json_output.stdout}\n{json_output.stderr}"


@pytest.mark.parametrize(
    ("command_prefix", "label"),
    [
        (["ls"], "ls"),
        (["harbor"], "harbor"),
        ([], "callback"),
    ],
)
def test_dashboard_tag_filter_no_match_with_stale_limit_is_informative(
    git_repo: Path,
    tmp_path: Path,
    command_prefix: list[str],
    label: str,
) -> None:
    """Dashboard commands should stay informative for tag misses with stale+limit."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"Dashboard {label} tag stale limit no-match objective",
            "--decisions",
            "dashboard tag+stale+limit no-match baseline",
            "--next-step",
            "run dashboard tag+stale+limit no-match",
            "--risks",
            "none",
            "--command",
            "echo noop",
            "--tag",
            "alpha",
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

    table_output = _run_dock(
        [*command_prefix, "--tag", "missing-tag", "--stale", "0", "--limit", "1"],
        cwd=tmp_path,
        env=env,
    )
    assert "Dockyard Harbor" in table_output.stdout
    assert f"Dashboard {label} tag stale limit no-match objective" not in table_output.stdout
    assert "Traceback" not in f"{table_output.stdout}\n{table_output.stderr}"

    json_output = _run_dock(
        [*command_prefix, "--tag", "missing-tag", "--stale", "0", "--limit", "1", "--json"],
        cwd=tmp_path,
        env=env,
    )
    assert json.loads(json_output.stdout) == []
    assert "Traceback" not in f"{json_output.stdout}\n{json_output.stderr}"


@pytest.mark.parametrize(
    ("command_prefix", "label"),
    [
        (["ls"], "ls"),
        (["harbor"], "harbor"),
        ([], "callback"),
    ],
)
def test_dashboard_tag_filter_no_match_with_stale_limit_is_informative_in_repo(
    git_repo: Path,
    tmp_path: Path,
    command_prefix: list[str],
    label: str,
) -> None:
    """Dashboard commands should stay informative in repo for tag+stale+limit misses."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"Dashboard {label} tag stale limit no-match objective in repo",
            "--decisions",
            "dashboard tag+stale+limit no-match baseline in repo",
            "--next-step",
            "run dashboard tag+stale+limit no-match in repo",
            "--risks",
            "none",
            "--command",
            "echo noop",
            "--tag",
            "alpha",
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

    table_output = _run_dock(
        [*command_prefix, "--tag", "missing-tag", "--stale", "0", "--limit", "1"],
        cwd=git_repo,
        env=env,
    )
    assert "Dockyard Harbor" in table_output.stdout
    assert f"Dashboard {label} tag stale limit no-match objective in repo" not in table_output.stdout
    assert "Traceback" not in f"{table_output.stdout}\n{table_output.stderr}"

    json_output = _run_dock(
        [*command_prefix, "--tag", "missing-tag", "--stale", "0", "--limit", "1", "--json"],
        cwd=git_repo,
        env=env,
    )
    assert json.loads(json_output.stdout) == []
    assert "Traceback" not in f"{json_output.stdout}\n{json_output.stderr}"


def test_no_subcommand_defaults_to_harbor_inside_repo(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Default no-subcommand path should work when invoked inside repo."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Default command in-repo baseline",
            "--decisions",
            "Ensure callback path is stable in repo cwd",
            "--next-step",
            "run bare dock command",
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
    result = _run_dock([], cwd=git_repo, env=env)
    assert "Dockyard Harbor" in result.stdout


def test_resume_output_includes_required_summary_fields(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Resume output should include required summary fields in top lines."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Validate summary contract",
            "--decisions",
            "Ensure first lines are actionable",
            "--next-step",
            "Read first lines only",
            "--next-step",
            "Run next command",
            "--risks",
            "None",
            "--command",
            "echo go",
            "--tests-run",
            "--tests-command",
            "pytest -q",
            "--build-ok",
            "--build-command",
            "echo build",
            "--lint-ok",
            "--lint-command",
            "ruff check",
            "--smoke-fail",
            "--no-auto-review",
        ],
        cwd=git_repo,
        env=env,
    )

    result = _run_dock(["resume"], cwd=git_repo, env=env)
    _assert_resume_top_lines_contract(result.stdout)


@pytest.mark.parametrize("command_name", ["resume", "r", "undock"])
def test_resume_branch_in_repo_preserves_top_lines_contract(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Branch-scoped in-repo resume paths should keep top-lines contract."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"{command_name} in-repo branch top-lines objective",
            "--decisions",
            "Validate in-repo branch top-lines contract",
            "--next-step",
            "Resume by branch in repo",
            "--next-step",
            "Continue work",
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

    result = _run_dock([command_name, "--branch", branch], cwd=git_repo, env=env)
    _assert_resume_top_lines_contract(result.stdout)


@pytest.mark.parametrize("command_name", ["resume", "r", "undock"])
def test_resume_trimmed_branch_in_repo_preserves_top_lines_contract(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Trimmed branch-scoped in-repo resume paths should keep top-lines contract."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"{command_name} in-repo trimmed branch top-lines objective",
            "--decisions",
            "Validate in-repo trimmed branch top-lines contract",
            "--next-step",
            "Resume by trimmed branch in repo",
            "--next-step",
            "Continue work",
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

    result = _run_dock([command_name, "--branch", f"  {branch}  "], cwd=git_repo, env=env)
    _assert_resume_top_lines_contract(result.stdout)


@pytest.mark.parametrize("command_name", ["resume", "r", "undock"])
def test_resume_trimmed_branch_in_repo_reports_expected_header(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Trimmed in-repo branch resume should render canonical header."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"{command_name} trimmed in-repo branch header objective",
            "--decisions",
            "Validate canonical project/branch header rendering for trimmed in-repo branch",
            "--next-step",
            "Resume by trimmed branch in repo",
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

    result = _run_dock([command_name, "--branch", f"  {branch}  "], cwd=git_repo, env=env)
    assert f"Project/Branch: {git_repo.name} / {branch}" in result.stdout


@pytest.mark.parametrize("command_name", ["resume", "r", "undock"])
def test_resume_by_berth_from_outside_repo_preserves_top_lines_contract(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Explicit-berth resume paths should keep top-lines contract outside repos."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"{command_name} outside-repo top-lines objective",
            "--decisions",
            "Validate explicit berth top-lines contract outside repo context",
            "--next-step",
            "Resume by berth from outside repo",
            "--next-step",
            "Continue work",
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

    result = _run_dock([command_name, git_repo.name], cwd=tmp_path, env=env)
    _assert_resume_top_lines_contract(result.stdout)


@pytest.mark.parametrize("command_name", ["resume", "r", "undock"])
def test_resume_by_berth_from_outside_repo_reports_expected_header(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Explicit-berth outside-repo resume should render canonical header."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"{command_name} berth header objective",
            "--decisions",
            "Validate canonical project/branch header rendering for explicit berth",
            "--next-step",
            "Resume by berth from outside repo",
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

    result = _run_dock([command_name, git_repo.name], cwd=tmp_path, env=env)
    assert f"Project/Branch: {git_repo.name} / {branch}" in result.stdout


@pytest.mark.parametrize("command_name", ["resume", "r", "undock"])
def test_resume_by_trimmed_berth_from_outside_repo_preserves_top_lines_contract(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Trimmed explicit-berth resume paths should keep top-lines contract outside repos."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"{command_name} outside-repo trimmed berth top-lines objective",
            "--decisions",
            "Validate trimmed explicit berth top-lines contract outside repo context",
            "--next-step",
            "Resume by trimmed berth from outside repo",
            "--next-step",
            "Continue work",
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

    result = _run_dock([command_name, f"  {git_repo.name}  "], cwd=tmp_path, env=env)
    _assert_resume_top_lines_contract(result.stdout)


@pytest.mark.parametrize("command_name", ["resume", "r", "undock"])
def test_resume_by_trimmed_berth_from_outside_repo_reports_expected_header(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Trimmed explicit-berth outside-repo resume should render canonical header."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"{command_name} trimmed berth header objective",
            "--decisions",
            "Validate canonical project/branch header rendering for trimmed berth",
            "--next-step",
            "Resume by trimmed berth from outside repo",
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

    result = _run_dock([command_name, f"  {git_repo.name}  "], cwd=tmp_path, env=env)
    assert f"Project/Branch: {git_repo.name} / {branch}" in result.stdout


@pytest.mark.parametrize("command_name", ["resume", "r", "undock"])
def test_resume_by_berth_branch_from_outside_repo_preserves_top_lines_contract(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Branch-scoped explicit-berth resume paths should keep top-lines contract."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"{command_name} outside-repo berth+branch top-lines objective",
            "--decisions",
            "Validate explicit berth+branch top-lines contract outside repo context",
            "--next-step",
            "Resume by berth+branch from outside repo",
            "--next-step",
            "Continue work",
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

    result = _run_dock(
        [command_name, git_repo.name, "--branch", branch],
        cwd=tmp_path,
        env=env,
    )
    _assert_resume_top_lines_contract(result.stdout)


@pytest.mark.parametrize("command_name", ["resume", "r", "undock"])
def test_resume_by_trimmed_berth_branch_from_outside_repo_preserves_top_lines_contract(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Trimmed berth/branch outside-repo resume paths should keep top-lines contract."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"{command_name} outside-repo trimmed berth+branch top-lines objective",
            "--decisions",
            "Validate trimmed explicit berth+branch top-lines contract outside repo context",
            "--next-step",
            "Resume by trimmed berth+branch from outside repo",
            "--next-step",
            "Continue work",
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

    result = _run_dock(
        [command_name, f"  {git_repo.name}  ", "--branch", f"  {branch}  "],
        cwd=tmp_path,
        env=env,
    )
    _assert_resume_top_lines_contract(result.stdout)


@pytest.mark.parametrize("command_name", ["resume", "r", "undock"])
def test_resume_by_trimmed_berth_branch_from_outside_repo_reports_expected_header(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Trimmed berth/branch outside-repo resume should render canonical header."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"{command_name} trimmed berth+branch header objective",
            "--decisions",
            "Validate canonical project/branch header rendering",
            "--next-step",
            "Resume by trimmed berth+branch from outside repo",
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

    result = _run_dock(
        [command_name, f"  {git_repo.name}  ", "--branch", f"  {branch}  "],
        cwd=tmp_path,
        env=env,
    )
    assert f"Project/Branch: {git_repo.name} / {branch}" in result.stdout


def test_resume_output_handles_empty_next_steps_payload(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Resume output should show placeholder when checkpoint has no next steps."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Empty next steps rendering",
            "--decisions",
            "Corrupt next-steps list to validate fallback",
            "--next-step",
            "original step",
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

    db_path = dock_home / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE checkpoints SET next_steps_json = ?",
        ("[]",),
    )
    conn.commit()
    conn.close()

    result = _run_dock(["resume"], cwd=git_repo, env=env)
    assert "Next Steps:" in result.stdout
    assert "(none recorded)" in result.stdout

    payload = json.loads(_run_dock(["resume", "--json"], cwd=git_repo, env=env).stdout)
    assert payload["next_steps"] == []


def test_resume_handoff_shows_placeholders_for_empty_lists(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Handoff output should show placeholders when steps/commands are empty."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Empty handoff list baseline",
            "--decisions",
            "Corrupt list payload fields to empty arrays",
            "--next-step",
            "seed initial step",
            "--risks",
            "none",
            "--command",
            "echo seed",
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

    db_path = dock_home / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE checkpoints SET next_steps_json = ?, resume_commands_json = ?",
        ("[]", "[]"),
    )
    conn.commit()
    conn.close()

    output = _run_dock(["resume", "--handoff"], cwd=git_repo, env=env).stdout
    assert "- Next Steps:" in output
    assert "- Commands:" in output
    assert output.count("  - (none recorded)") >= 2


def test_resume_handoff_falls_back_for_blank_objective_and_risks(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Handoff should render explicit fallbacks for blank objective/risks."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Handoff fallback baseline",
            "--decisions",
            "Corrupt objective and risk fields to blanks",
            "--next-step",
            "seed step",
            "--risks",
            "seed risk",
            "--command",
            "echo seed",
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

    db_path = dock_home / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE checkpoints SET objective = ?, risks_review = ?",
        ("   ", "   "),
    )
    conn.commit()
    conn.close()

    output = _run_dock(["resume", "--handoff"], cwd=git_repo, env=env).stdout
    assert "- Objective: (none)" in output
    assert "- Risks: (none)" in output


def test_resume_output_compacts_multiline_summary_fields(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Resume output should compact multiline objective and next-step text."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Line one\nLine two",
            "--decisions",
            "Normalize multiline summary fields",
            "--next-step",
            "Step one\nStep two",
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

    result = _run_dock(["resume"], cwd=git_repo, env=env)
    assert "Objective: Line one Line two" in result.stdout
    assert "1. Step one Step two" in result.stdout


def test_resume_output_compacts_multiline_project_label(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Resume output should compact multiline berth labels in header."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)
    branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Project label compaction",
            "--decisions",
            "Normalize berth label line breaks",
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

    db_path = dock_home / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE berths SET name = ?",
        ("Repo line 1\nRepo line 2",),
    )
    conn.commit()
    conn.close()

    result = _run_dock(["resume"], cwd=git_repo, env=env)
    assert f"Project/Branch: Repo line 1 Repo line 2 / {branch}" in result.stdout


def test_resume_output_compacts_multiline_checkpoint_timestamp(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Resume output should compact multiline checkpoint timestamp values."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Checkpoint timestamp compaction",
            "--decisions",
            "Normalize multiline checkpoint timestamp display",
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

    db_path = dock_home / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE checkpoints SET created_at = ?",
        ("2000-01-01\n00:00:00+00:00",),
    )
    conn.commit()
    conn.close()

    result = _run_dock(["resume"], cwd=git_repo, env=env)
    assert "Last Checkpoint: 2000-01-01 00:00:00+00:00 (" in result.stdout


def test_resume_output_falls_back_for_blank_checkpoint_timestamp(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Resume output should fallback when checkpoint timestamp is blank."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Checkpoint timestamp fallback",
            "--decisions",
            "Keep resume top-lines resilient for blank timestamps",
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

    db_path = dock_home / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE checkpoints SET created_at = ?",
        ("   ",),
    )
    conn.commit()
    conn.close()

    result = _run_dock(["resume"], cwd=git_repo, env=env)
    assert "Last Checkpoint: (unknown) (unknown ago)" in result.stdout


def test_resume_output_falls_back_for_blank_project_label(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Resume output should fallback to unknown when berth label is blank."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)
    branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Project label blank fallback",
            "--decisions",
            "Ensure resume label fallback remains explicit",
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

    db_path = dock_home / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE berths SET name = ?",
        ("   ",),
    )
    conn.commit()
    conn.close()

    result = _run_dock(["resume"], cwd=git_repo, env=env)
    assert f"Project/Branch: (unknown) / {branch}" in result.stdout


def test_resume_handoff_preserves_literal_markup_like_text(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Resume and handoff output should preserve literal bracketed text."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "[red]Literal objective[/red]",
            "--decisions",
            "[bold]Literal decision[/bold]",
            "--next-step",
            "[green]Literal step[/green]",
            "--risks",
            "[yellow]Literal risk[/yellow]",
            "--command",
            "[blue]echo literal[/blue]",
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

    resume_output = _run_dock(["resume"], cwd=git_repo, env=env).stdout
    assert "Objective: [red]Literal objective[/red]" in resume_output
    assert "1. [green]Literal step[/green]" in resume_output

    handoff_output = _run_dock(["resume", "--handoff"], cwd=git_repo, env=env).stdout
    assert "- Objective: [red]Literal objective[/red]" in handoff_output
    assert "  - [green]Literal step[/green]" in handoff_output
    assert "- Risks: [yellow]Literal risk[/yellow]" in handoff_output
    assert "  - [blue]echo literal[/blue]" in handoff_output


def test_resume_handoff_compacts_multiline_fields(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Handoff output should compact multiline objective/step/risk/command text."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "objective line one\nline two",
            "--decisions",
            "handoff compaction baseline",
            "--next-step",
            "step one\nstep two",
            "--risks",
            "risk one\nrisk two",
            "--command",
            "echo one\necho two",
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

    handoff_output = _run_dock(["resume", "--handoff"], cwd=git_repo, env=env).stdout
    assert "- Objective: objective line one line two" in handoff_output
    assert "  - step one step two" in handoff_output
    assert "- Risks: risk one risk two" in handoff_output
    assert "  - echo one echo two" in handoff_output


def test_resume_by_berth_from_outside_repo_with_handoff(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Resume should work outside repo when berth is provided explicitly."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Cross-repo resume lookup",
            "--decisions",
            "Use berth argument from outside repo context",
            "--next-step",
            "Resume by berth",
            "--risks",
            "None",
            "--command",
            "echo continue",
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

    result = _run_dock(
        ["resume", git_repo.name, "--handoff"],
        cwd=tmp_path,
        env=env,
    )
    assert "Project/Branch: repo / " in result.stdout
    assert "Cross-repo resume lookup" in result.stdout
    assert "### Dockyard Handoff" in result.stdout

    payload = json.loads(
        _run_dock(["resume", git_repo.name, "--json"], cwd=tmp_path, env=env).stdout
    )
    assert payload["project_name"] == git_repo.name


def test_resume_supports_handoff_and_json_for_trimmed_explicit_berth(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Resume should support handoff/json output with trimmed explicit berth."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Resume trimmed berth handoff/json objective",
            "--decisions",
            "Validate resume parity for handoff/json output with trimmed berth",
            "--next-step",
            "Run resume outside repo with trimmed berth",
            "--risks",
            "none",
            "--command",
            "echo resume-trimmed",
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

    handoff = _run_dock(["resume", f"  {git_repo.name}  ", "--handoff"], cwd=tmp_path, env=env).stdout
    assert "Resume trimmed berth handoff/json objective" in handoff
    assert "### Dockyard Handoff" in handoff

    payload = json.loads(
        _run_dock(["resume", f"  {git_repo.name}  ", "--json"], cwd=tmp_path, env=env).stdout
    )
    assert payload["project_name"] == git_repo.name
    assert payload["objective"] == "Resume trimmed berth handoff/json objective"


def test_resume_by_berth_accepts_trimmed_lookup_value(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Resume should resolve berth lookup values after whitespace trimming."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Trimmed berth resume objective",
            "--decisions",
            "Resolve berth value with surrounding whitespace",
            "--next-step",
            "resume outside repo",
            "--risks",
            "none",
            "--command",
            "echo continue",
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

    result = _run_dock(["resume", f"  {git_repo.name}  "], cwd=tmp_path, env=env)
    assert "Trimmed berth resume objective" in result.stdout


def test_resume_alias_accepts_trimmed_berth_lookup_value(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Resume alias should resolve berth lookup after whitespace trimming."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Alias trimmed berth objective",
            "--decisions",
            "Resolve alias berth value with surrounding whitespace",
            "--next-step",
            "resume outside repo via alias",
            "--risks",
            "none",
            "--command",
            "echo continue",
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

    result = _run_dock(["r", f"  {git_repo.name}  "], cwd=tmp_path, env=env)
    assert "Alias trimmed berth objective" in result.stdout


def test_resume_alias_supports_handoff_and_json_for_explicit_berth(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Resume alias should support handoff/json output with explicit berth."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Resume alias handoff/json objective",
            "--decisions",
            "Validate resume alias handoff and json parity",
            "--next-step",
            "run alias outside repo",
            "--risks",
            "none",
            "--command",
            "echo alias-resume",
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

    handoff = _run_dock(["r", f"  {git_repo.name}  ", "--handoff"], cwd=tmp_path, env=env).stdout
    assert "Resume alias handoff/json objective" in handoff
    assert "### Dockyard Handoff" in handoff

    payload = json.loads(_run_dock(["r", f"  {git_repo.name}  ", "--json"], cwd=tmp_path, env=env).stdout)
    assert payload["project_name"] == git_repo.name
    assert payload["objective"] == "Resume alias handoff/json objective"


@pytest.mark.parametrize("command_name", ["resume", "r", "undock"])
def test_resume_commands_support_handoff_and_json_for_explicit_berth_branch_outside_repo(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Resume commands should support berth+branch handoff/json outside repos."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    branch = _git_current_branch(git_repo)
    objective = f"{command_name} berth+branch handoff/json objective"

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            objective,
            "--decisions",
            "Validate berth+branch handoff/json parity outside repo context",
            "--next-step",
            "run resume command from outside repo with berth+branch",
            "--risks",
            "none",
            "--command",
            "echo alias-resume-branch",
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

    handoff = _run_dock(
        [command_name, f"  {git_repo.name}  ", "--branch", f"  {branch}  ", "--handoff"],
        cwd=tmp_path,
        env=env,
    ).stdout
    assert objective in handoff
    assert "### Dockyard Handoff" in handoff

    payload = json.loads(
        _run_dock(
            [command_name, f"  {git_repo.name}  ", "--branch", f"  {branch}  ", "--json"],
            cwd=tmp_path,
            env=env,
        ).stdout
    )
    assert payload["project_name"] == git_repo.name
    assert payload["branch"] == branch
    assert payload["objective"] == objective


def test_resume_branch_flag_selects_requested_branch(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Resume --branch should return checkpoint for selected branch context."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    base_branch = _git_current_branch(git_repo)
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Main branch objective",
            "--decisions",
            "baseline",
            "--next-step",
            "main task",
            "--risks",
            "none",
            "--command",
            "echo main",
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

    subprocess.run(
        ["git", "checkout", "-b", "feature/resume-target"],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Feature branch objective",
            "--decisions",
            "feature baseline",
            "--next-step",
            "feature task",
            "--risks",
            "none",
            "--command",
            "echo feature",
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
    subprocess.run(
        ["git", "checkout", base_branch],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )

    selected = json.loads(
        _run_dock(
            ["resume", "--branch", "feature/resume-target", "--json"],
            cwd=git_repo,
            env=env,
        ).stdout
    )
    assert selected["branch"] == "feature/resume-target"
    assert selected["objective"] == "Feature branch objective"


def test_resume_branch_flag_accepts_trimmed_value(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Resume --branch should resolve values after whitespace trimming."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Trimmed branch resume objective",
            "--decisions",
            "Validate trimmed branch filter handling",
            "--next-step",
            "resume with padded branch",
            "--risks",
            "none",
            "--command",
            "echo branch",
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

    selected = json.loads(
        _run_dock(["resume", "--branch", f"  {branch}  ", "--json"], cwd=git_repo, env=env).stdout
    )
    assert selected["branch"] == branch
    assert selected["objective"] == "Trimmed branch resume objective"


def test_resume_by_berth_accepts_trimmed_branch_option(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Resume should trim --branch when combined with explicit berth lookup."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Berth + branch trim objective",
            "--decisions",
            "Use trimmed branch with explicit berth context",
            "--next-step",
            "resume by berth+branch",
            "--risks",
            "none",
            "--command",
            "echo branch",
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

    payload = json.loads(
        _run_dock(
            ["resume", f"  {git_repo.name}  ", "--branch", f"  {branch}  ", "--json"],
            cwd=tmp_path,
            env=env,
        ).stdout
    )
    assert payload["branch"] == branch
    assert payload["project_name"] == git_repo.name


def test_resume_unknown_branch_for_known_repo_is_actionable(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Resume should fail cleanly when requested branch has no checkpoint."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Known repo checkpoint",
            "--decisions",
            "Used to validate unknown branch handling",
            "--next-step",
            "resume missing branch",
            "--risks",
            "none",
            "--command",
            "echo main",
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

    failed = _run_dock(
        ["resume", "--branch", "missing/branch"],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "No checkpoint found for the requested context." in output
    assert "Traceback" not in output


@pytest.mark.parametrize("command_name", ["resume", "r", "undock"])
@pytest.mark.parametrize("output_flag", ["", "--json", "--handoff"], ids=["default", "json", "handoff"])
def test_resume_commands_unknown_explicit_berth_branch_is_actionable(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
    output_flag: str,
) -> None:
    """Resume commands should fail cleanly for unknown branch + explicit berth."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"{command_name} unknown explicit berth branch objective",
            "--decisions",
            "Validate unknown explicit berth+branch handling",
            "--next-step",
            "resume missing explicit berth+branch",
            "--risks",
            "none",
            "--command",
            "echo main",
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

    args = [command_name, f"  {git_repo.name}  ", "--branch", "  missing/branch  "]
    if output_flag:
        args.append(output_flag)

    failed = _run_dock(args, cwd=tmp_path, env=env, expect_code=2)
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "No checkpoint found for the requested context." in output
    assert "Traceback" not in output


@pytest.mark.parametrize("command_name", ["resume", "r", "undock"])
def test_resume_commands_prefer_repo_id_lookup_over_colliding_berth_name(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Resume commands should prioritize exact repo-id lookup over berth name collisions."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    other_repo = tmp_path / "resume-collision-other"
    other_repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=str(other_repo), check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "dockyard@example.com"],
        cwd=str(other_repo),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Dockyard Test"],
        cwd=str(other_repo),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", "git@github.com:org/resume-other.git"],
        cwd=str(other_repo),
        check=True,
        capture_output=True,
    )
    (other_repo / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=str(other_repo), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=str(other_repo), check=True, capture_output=True)

    _run_dock(
        [
            "save",
            "--root",
            str(other_repo),
            "--no-prompt",
            "--objective",
            "resume-collision-other",
            "--decisions",
            "other repo checkpoint for resume lookup collision test",
            "--next-step",
            "query resume by repo id",
            "--risks",
            "none",
            "--command",
            "echo other",
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
        cwd=other_repo,
        env=env,
    )
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "resume-collision-target",
            "--decisions",
            "target repo checkpoint for resume lookup collision test",
            "--next-step",
            "query resume by repo id",
            "--risks",
            "none",
            "--command",
            "echo target",
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

    db_path = tmp_path / ".dockyard_data" / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    target_repo_id = conn.execute(
        "SELECT repo_id FROM berths WHERE root_path = ?",
        (str(git_repo),),
    ).fetchone()[0]
    other_repo_id = conn.execute(
        "SELECT repo_id FROM berths WHERE root_path = ?",
        (str(other_repo),),
    ).fetchone()[0]
    conn.execute("UPDATE berths SET name = ? WHERE repo_id = ?", (target_repo_id, other_repo_id))
    conn.commit()
    conn.close()

    payload = json.loads(_run_dock([command_name, target_repo_id, "--json"], cwd=tmp_path, env=env).stdout)
    assert payload["repo_id"] == target_repo_id
    assert payload["objective"] == "resume-collision-target"


def test_alias_commands_harbor_search_and_resume(git_repo: Path, tmp_path: Path) -> None:
    """Hidden aliases should mirror primary command behavior."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Alias coverage objective",
            "--decisions",
            "Verify harbor/f/r aliases route correctly",
            "--next-step",
            "Use alias commands",
            "--risks",
            "None",
            "--command",
            "echo alias",
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

    harbor_result = _run_dock(["harbor"], cwd=tmp_path, env=env)
    assert "Dockyard Harbor" in harbor_result.stdout

    search_alias = _run_dock(["f", "Alias coverage"], cwd=tmp_path, env=env)
    assert "Dockyard Search Results" in search_alias.stdout
    assert "master" in search_alias.stdout or "main" in search_alias.stdout
    search_alias_json = json.loads(_run_dock(["f", "Alias coverage", "--json"], cwd=tmp_path, env=env).stdout)
    assert len(search_alias_json) >= 1
    assert "branch" in search_alias_json[0]
    no_match_alias = _run_dock(["f", "definitely-no-match", "--json"], cwd=tmp_path, env=env)
    assert json.loads(no_match_alias.stdout) == []
    assert "Traceback" not in f"{no_match_alias.stdout}\n{no_match_alias.stderr}"
    filtered_alias_result = _run_dock(["f", "Alias coverage", "--tag", "missing-tag", "--json"], cwd=tmp_path, env=env)
    filtered_alias_json = json.loads(filtered_alias_result.stdout)
    assert filtered_alias_json == []
    assert "Traceback" not in f"{filtered_alias_result.stdout}\n{filtered_alias_result.stderr}"

    resume_alias = _run_dock(["r"], cwd=git_repo, env=env)
    assert "Objective: Alias coverage objective" in resume_alias.stdout


def test_search_alias_json_handles_unicode_query(git_repo: Path, tmp_path: Path) -> None:
    """Search alias should handle unicode query strings in JSON mode."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Unicode façade objective",
            "--decisions",
            "unicode alias search coverage",
            "--next-step",
            "run alias json search",
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

    rows = json.loads(_run_dock(["f", "façade", "--json"], cwd=tmp_path, env=env).stdout)
    assert len(rows) == 1
    assert "façade" in rows[0]["objective"]


def test_search_alias_repo_filter_accepts_berth_name(git_repo: Path, tmp_path: Path) -> None:
    """Search alias repo filter should accept berth names."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Alias repo filter objective",
            "--decisions",
            "Alias repo filter decision",
            "--next-step",
            "run alias repo filter",
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

    rows = json.loads(
        _run_dock(
            ["f", "Alias repo filter objective", "--repo", git_repo.name, "--json"],
            cwd=tmp_path,
            env=env,
        ).stdout
    )
    assert len(rows) == 1
    assert rows[0]["berth_name"] == git_repo.name


@pytest.mark.parametrize("command_name", ["search", "f"])
def test_search_json_repo_filtered_rows_follow_expected_schema(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Repo-filtered JSON search rows should expose a stable schema."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"Search json schema objective ({command_name})",
            "--decisions",
            "Validate JSON row schema for repo-filtered search results",
            "--next-step",
            "run json search with --repo filter",
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

    rows = json.loads(
        _run_dock(
            [
                command_name,
                f"Search json schema objective ({command_name})",
                "--repo",
                git_repo.name,
                "--json",
            ],
            cwd=tmp_path,
            env=env,
        ).stdout
    )
    assert len(rows) >= 1
    assert {row["berth_name"] for row in rows} == {git_repo.name}

    expected_keys = {"id", "repo_id", "berth_name", "branch", "created_at", "snippet", "objective"}
    for row in rows:
        assert set(row) == expected_keys
        assert isinstance(row["snippet"], str)


def test_search_alias_repo_filter_no_match_returns_empty_json(git_repo: Path, tmp_path: Path) -> None:
    """Search alias repo filter should return [] when berth does not match."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Alias repo filter no-match objective",
            "--decisions",
            "Alias repo filter no-match decision",
            "--next-step",
            "run alias repo filter miss",
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

    result = _run_dock(
        ["f", "Alias repo filter no-match objective", "--repo", "missing-berth", "--json"],
        cwd=tmp_path,
        env=env,
    )
    assert json.loads(result.stdout) == []
    assert "Traceback" not in f"{result.stdout}\n{result.stderr}"


def test_search_alias_supports_tag_filter(git_repo: Path, tmp_path: Path) -> None:
    """Search alias should honor --tag filtering semantics."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    default_branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Alias tag filter objective default",
            "--decisions",
            "default tag checkpoint",
            "--next-step",
            "validate tag filtering",
            "--risks",
            "none",
            "--command",
            "echo default",
            "--tag",
            "alpha",
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
    subprocess.run(
        ["git", "checkout", "-b", "feature/alias-tag-filter"],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Alias tag filter objective feature",
            "--decisions",
            "feature tag checkpoint",
            "--next-step",
            "validate feature tag filtering",
            "--risks",
            "none",
            "--command",
            "echo feature",
            "--tag",
            "beta",
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
    subprocess.run(
        ["git", "checkout", default_branch],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )

    alpha_rows = json.loads(
        _run_dock(
            ["f", "Alias tag filter objective", "--tag", "alpha", "--json"],
            cwd=tmp_path,
            env=env,
        ).stdout
    )
    assert len(alpha_rows) == 1
    assert alpha_rows[0]["branch"] == default_branch

    beta_rows = json.loads(
        _run_dock(
            ["f", "Alias tag filter objective", "--tag", "beta", "--json"],
            cwd=tmp_path,
            env=env,
        ).stdout
    )
    assert len(beta_rows) == 1
    assert beta_rows[0]["branch"] == "feature/alias-tag-filter"
    beta_repo_rows = json.loads(
        _run_dock(
            ["f", "Alias tag filter objective", "--tag", "beta", "--repo", git_repo.name, "--json"],
            cwd=tmp_path,
            env=env,
        ).stdout
    )
    assert len(beta_repo_rows) == 1
    assert beta_repo_rows[0]["branch"] == "feature/alias-tag-filter"
    beta_repo_table = _run_dock(
        ["f", "Alias tag filter objective", "--tag", "beta", "--repo", git_repo.name],
        cwd=tmp_path,
        env=env,
    ).stdout
    assert "feature" in beta_repo_table
    assert "default" not in beta_repo_table
    assert "Traceback" not in beta_repo_table
    missing_repo_result = _run_dock(
        ["f", "Alias tag filter objective", "--tag", "beta", "--repo", "missing-berth", "--json"],
        cwd=tmp_path,
        env=env,
    )
    assert json.loads(missing_repo_result.stdout) == []
    assert "Traceback" not in f"{missing_repo_result.stdout}\n{missing_repo_result.stderr}"
    beta_feature_rows = json.loads(
        _run_dock(
            [
                "f",
                "Alias tag filter objective",
                "--tag",
                "beta",
                "--branch",
                "feature/alias-tag-filter",
                "--json",
            ],
            cwd=tmp_path,
            env=env,
        ).stdout
    )
    assert len(beta_feature_rows) == 1
    assert beta_feature_rows[0]["branch"] == "feature/alias-tag-filter"
    beta_feature_table = _run_dock(
        [
            "f",
            "Alias tag filter objective",
            "--tag",
            "beta",
            "--branch",
            "feature/alias-tag-filter",
        ],
        cwd=tmp_path,
        env=env,
    ).stdout
    assert "feature" in beta_feature_table
    assert "default" not in beta_feature_table
    assert "Traceback" not in beta_feature_table
    beta_repo_branch_rows = json.loads(
        _run_dock(
            [
                "f",
                "Alias tag filter objective",
                "--tag",
                "beta",
                "--repo",
                git_repo.name,
                "--branch",
                "feature/alias-tag-filter",
                "--json",
            ],
            cwd=tmp_path,
            env=env,
        ).stdout
    )
    assert len(beta_repo_branch_rows) == 1
    assert beta_repo_branch_rows[0]["branch"] == "feature/alias-tag-filter"
    wrong_branch_result = _run_dock(
        [
            "f",
            "Alias tag filter objective",
            "--tag",
            "beta",
            "--branch",
            default_branch,
            "--json",
        ],
        cwd=tmp_path,
        env=env,
    )
    assert json.loads(wrong_branch_result.stdout) == []
    assert "Traceback" not in f"{wrong_branch_result.stdout}\n{wrong_branch_result.stderr}"


def test_search_alias_supports_branch_filter(git_repo: Path, tmp_path: Path) -> None:
    """Search alias should honor --branch filtering semantics."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    default_branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "asbf-default",
            "--decisions",
            "default branch checkpoint",
            "--next-step",
            "run alias branch filters",
            "--risks",
            "none",
            "--command",
            "echo default",
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
    subprocess.run(
        ["git", "checkout", "-b", "feature/alias-branch-filter"],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "asbf-feature",
            "--decisions",
            "feature branch checkpoint",
            "--next-step",
            "run feature alias branch filters",
            "--risks",
            "none",
            "--command",
            "echo feature",
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
    subprocess.run(
        ["git", "checkout", default_branch],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )

    rows = json.loads(
        _run_dock(
            ["f", "asbf", "--branch", "feature/alias-branch-filter", "--json"],
            cwd=tmp_path,
            env=env,
        ).stdout
    )
    assert len(rows) == 1
    assert rows[0]["branch"] == "feature/alias-branch-filter"
    default_rows = json.loads(
        _run_dock(
            ["f", "asbf", "--branch", default_branch, "--json"],
            cwd=tmp_path,
            env=env,
        ).stdout
    )
    assert len(default_rows) == 1
    assert default_rows[0]["branch"] == default_branch
    missing_branch_result = _run_dock(
        ["f", "asbf", "--branch", "missing/branch", "--json"],
        cwd=tmp_path,
        env=env,
    )
    assert json.loads(missing_branch_result.stdout) == []
    assert "Traceback" not in f"{missing_branch_result.stdout}\n{missing_branch_result.stderr}"
    combo_rows = json.loads(
        _run_dock(
            [
                "f",
                "asbf",
                "--repo",
                git_repo.name,
                "--branch",
                "feature/alias-branch-filter",
                "--json",
            ],
            cwd=tmp_path,
            env=env,
        ).stdout
    )
    assert len(combo_rows) == 1
    assert combo_rows[0]["branch"] == "feature/alias-branch-filter"
    feature_table = _run_dock(
        ["f", "asbf", "--branch", "feature/alias-branch-filter"],
        cwd=tmp_path,
        env=env,
    ).stdout
    assert "asbf-feature" in feature_table
    assert "asbf-default" not in feature_table
    assert "Traceback" not in feature_table


def test_search_alias_repo_branch_filter_semantics_non_json(git_repo: Path, tmp_path: Path) -> None:
    """Alias search should honor combined repo+branch filters in table mode."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    default_branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Alias repo branch semantics objective default",
            "--decisions",
            "default branch checkpoint for alias repo+branch filtering",
            "--next-step",
            "run alias repo+branch filter",
            "--risks",
            "none",
            "--command",
            "echo default",
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
    subprocess.run(
        ["git", "checkout", "-b", "feature/alias-repo-branch-filter"],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Alias repo branch semantics objective feature",
            "--decisions",
            "feature branch checkpoint for alias repo+branch filtering",
            "--next-step",
            "run alias repo+branch filter",
            "--risks",
            "none",
            "--command",
            "echo feature",
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
    subprocess.run(
        ["git", "checkout", default_branch],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )

    filtered = _run_dock(
        [
            "f",
            "Alias repo branch semantics objective",
            "--repo",
            git_repo.name,
            "--branch",
            "feature/alias-repo-branch-filter",
        ],
        cwd=tmp_path,
        env=env,
    ).stdout
    assert "feature" in filtered
    assert "default" not in filtered


def test_search_alias_shows_no_match_message(tmp_path: Path) -> None:
    """Search alias should show empty-result guidance in non-JSON mode."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    result = _run_dock(["f", "no-match-query"], cwd=tmp_path, env=env)
    assert result.returncode == 0
    assert "No checkpoint matches found." in result.stdout
    assert "Traceback" not in f"{result.stdout}\n{result.stderr}"


def test_search_alias_repo_filter_no_match_message(git_repo: Path, tmp_path: Path) -> None:
    """Search alias should show no-match guidance for repo-filter misses."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Alias repo filter message objective",
            "--decisions",
            "Alias repo filter message decision",
            "--next-step",
            "validate repo filter miss message",
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

    result = _run_dock(
        ["f", "Alias repo filter message objective", "--repo", "missing-berth"],
        cwd=tmp_path,
        env=env,
    )
    assert "No checkpoint matches found." in result.stdout
    assert "Traceback" not in f"{result.stdout}\n{result.stderr}"


def test_search_alias_repo_branch_filter_no_match_json(git_repo: Path, tmp_path: Path) -> None:
    """Search alias should return [] when combined repo+branch filters miss."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Alias repo branch json no-match objective",
            "--decisions",
            "Alias repo branch json no-match decision",
            "--next-step",
            "validate repo+branch json miss",
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

    result = _run_dock(
        [
            "f",
            "Alias repo branch json no-match objective",
            "--repo",
            "missing-berth",
            "--branch",
            "missing/branch",
            "--json",
        ],
        cwd=tmp_path,
        env=env,
    )
    assert json.loads(result.stdout) == []
    assert "Traceback" not in f"{result.stdout}\n{result.stderr}"


def test_search_alias_repo_branch_filter_no_match_message(git_repo: Path, tmp_path: Path) -> None:
    """Search alias should show no-match guidance for repo+branch misses."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Alias repo branch message objective",
            "--decisions",
            "Alias repo branch message decision",
            "--next-step",
            "validate repo+branch miss message",
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

    result = _run_dock(
        [
            "f",
            "Alias repo branch message objective",
            "--repo",
            "missing-berth",
            "--branch",
            "missing/branch",
        ],
        cwd=tmp_path,
        env=env,
    )
    assert "No checkpoint matches found." in result.stdout
    assert "Traceback" not in f"{result.stdout}\n{result.stderr}"


def test_search_alias_tag_filter_no_match_message(git_repo: Path, tmp_path: Path) -> None:
    """Search alias should show no-match guidance for tag-filter misses."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Alias tag filter message objective",
            "--decisions",
            "Alias tag filter message decision",
            "--next-step",
            "validate tag filter miss message",
            "--risks",
            "none",
            "--command",
            "echo noop",
            "--tag",
            "alpha",
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

    result = _run_dock(
        ["f", "Alias tag filter message objective", "--tag", "missing-tag"],
        cwd=tmp_path,
        env=env,
    )
    assert "No checkpoint matches found." in result.stdout
    assert "Traceback" not in f"{result.stdout}\n{result.stderr}"


def test_search_alias_branch_filter_no_match_message(git_repo: Path, tmp_path: Path) -> None:
    """Search alias should show no-match guidance for branch-filter misses."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Alias branch filter message objective",
            "--decisions",
            "Alias branch filter message decision",
            "--next-step",
            "validate branch filter miss message",
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

    result = _run_dock(
        ["f", "Alias branch filter message objective", "--branch", "missing/branch"],
        cwd=tmp_path,
        env=env,
    )
    assert "No checkpoint matches found." in result.stdout
    assert "Traceback" not in f"{result.stdout}\n{result.stderr}"


def test_search_alias_tag_branch_filter_no_match_json(git_repo: Path, tmp_path: Path) -> None:
    """Search alias JSON should return [] for combined tag+branch misses."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Alias tag branch json objective",
            "--decisions",
            "Alias tag branch json decision",
            "--next-step",
            "validate tag+branch json miss",
            "--risks",
            "none",
            "--command",
            "echo noop",
            "--tag",
            "alpha",
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

    result = _run_dock(
        ["f", "Alias tag branch json objective", "--tag", "alpha", "--branch", "missing/branch", "--json"],
        cwd=tmp_path,
        env=env,
    )
    assert json.loads(result.stdout) == []
    assert "Traceback" not in f"{result.stdout}\n{result.stderr}"


def test_search_alias_tag_branch_filter_no_match_message(git_repo: Path, tmp_path: Path) -> None:
    """Search alias should show no-match guidance for combined tag+branch misses."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Alias tag branch message objective",
            "--decisions",
            "Alias tag branch message decision",
            "--next-step",
            "validate tag+branch miss message",
            "--risks",
            "none",
            "--command",
            "echo noop",
            "--tag",
            "alpha",
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

    result = _run_dock(
        ["f", "Alias tag branch message objective", "--tag", "alpha", "--branch", "missing/branch"],
        cwd=tmp_path,
        env=env,
    )
    assert "No checkpoint matches found." in result.stdout
    assert "Traceback" not in f"{result.stdout}\n{result.stderr}"


def test_search_alias_tag_repo_filter_no_match_message(git_repo: Path, tmp_path: Path) -> None:
    """Search alias should show no-match guidance for tag+repo misses."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Alias tag repo message objective",
            "--decisions",
            "Alias tag repo message decision",
            "--next-step",
            "validate tag+repo miss message",
            "--risks",
            "none",
            "--command",
            "echo noop",
            "--tag",
            "alpha",
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

    result = _run_dock(
        ["f", "Alias tag repo message objective", "--tag", "alpha", "--repo", "missing-berth"],
        cwd=tmp_path,
        env=env,
    )
    assert "No checkpoint matches found." in result.stdout
    assert "Traceback" not in f"{result.stdout}\n{result.stderr}"


def test_search_alias_tag_repo_filter_no_match_json(git_repo: Path, tmp_path: Path) -> None:
    """Search alias JSON should return [] for combined tag+repo misses."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Alias tag repo json objective",
            "--decisions",
            "Alias tag repo json decision",
            "--next-step",
            "validate tag+repo json miss",
            "--risks",
            "none",
            "--command",
            "echo noop",
            "--tag",
            "alpha",
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

    result = _run_dock(
        ["f", "Alias tag repo json objective", "--tag", "alpha", "--repo", "missing-berth", "--json"],
        cwd=tmp_path,
        env=env,
    )
    assert json.loads(result.stdout) == []
    assert "Traceback" not in f"{result.stdout}\n{result.stderr}"


def test_search_alias_tag_repo_branch_filter_no_match_json(git_repo: Path, tmp_path: Path) -> None:
    """Search alias should return [] for combined tag+repo+branch misses."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Alias tag repo branch json objective",
            "--decisions",
            "Alias tag repo branch json decision",
            "--next-step",
            "validate tag+repo+branch json miss",
            "--risks",
            "none",
            "--command",
            "echo noop",
            "--tag",
            "alpha",
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

    result = _run_dock(
        [
            "f",
            "Alias tag repo branch json objective",
            "--tag",
            "alpha",
            "--repo",
            "missing-berth",
            "--branch",
            "missing/branch",
            "--json",
        ],
        cwd=tmp_path,
        env=env,
    )
    assert json.loads(result.stdout) == []
    assert "Traceback" not in f"{result.stdout}\n{result.stderr}"


def test_search_alias_tag_repo_branch_filter_no_match_message(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Search alias should show no-match guidance for tag+repo+branch misses."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Alias tag repo branch message objective",
            "--decisions",
            "Alias tag repo branch message decision",
            "--next-step",
            "validate tag+repo+branch miss",
            "--risks",
            "none",
            "--command",
            "echo noop",
            "--tag",
            "alpha",
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

    result = _run_dock(
        [
            "f",
            "Alias tag repo branch message objective",
            "--tag",
            "alpha",
            "--repo",
            "missing-berth",
            "--branch",
            "missing/branch",
        ],
        cwd=tmp_path,
        env=env,
    )
    assert "No checkpoint matches found." in result.stdout
    assert "Traceback" not in f"{result.stdout}\n{result.stderr}"


def test_undock_alias_matches_resume_behavior(git_repo: Path, tmp_path: Path) -> None:
    """`undock` alias should resolve to the same resume behavior."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Undock alias objective",
            "--decisions",
            "Undock should mirror resume command output",
            "--next-step",
            "Run undock alias",
            "--risks",
            "none",
            "--command",
            "echo undock",
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

    output = _run_dock(["undock"], cwd=git_repo, env=env).stdout
    assert "Objective: Undock alias objective" in output


def test_undock_alias_rejects_blank_berth_argument(tmp_path: Path) -> None:
    """Undock alias should reject blank berth argument values."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    failed = _run_dock(["undock", "   "], cwd=tmp_path, env=env, expect_code=2)
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "Berth must be a non-empty string." in output
    assert "Traceback" not in output


def test_undock_alias_rejects_blank_branch_option(git_repo: Path, tmp_path: Path) -> None:
    """Undock alias should reject blank --branch option values."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    failed = _run_dock(["undock", "--branch", "   "], cwd=git_repo, env=env, expect_code=2)
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "--branch must be a non-empty string." in output
    assert "Traceback" not in output


def test_undock_alias_accepts_trimmed_berth_lookup_value(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Undock alias should resolve berth lookup after whitespace trimming."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Undock trimmed berth objective",
            "--decisions",
            "Resolve undock berth value with surrounding whitespace",
            "--next-step",
            "resume outside repo via undock",
            "--risks",
            "none",
            "--command",
            "echo undock",
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

    result = _run_dock(["undock", f"  {git_repo.name}  "], cwd=tmp_path, env=env)
    assert "Undock trimmed berth objective" in result.stdout


def test_undock_alias_branch_flag_accepts_trimmed_value(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Undock alias should resolve --branch values after trimming."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Undock trimmed branch objective",
            "--decisions",
            "Resolve undock branch values with surrounding whitespace",
            "--next-step",
            "resume undock with branch",
            "--risks",
            "none",
            "--command",
            "echo undock-branch",
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

    selected = json.loads(
        _run_dock(["undock", "--branch", f"  {branch}  ", "--json"], cwd=git_repo, env=env).stdout
    )
    assert selected["branch"] == branch
    assert selected["objective"] == "Undock trimmed branch objective"


def test_undock_alias_supports_handoff_and_json_for_explicit_berth(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Undock alias should mirror resume handoff/json berth lookup behavior."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Undock handoff/json objective",
            "--decisions",
            "Validate undock alias parity for handoff and json output",
            "--next-step",
            "Run undock alias outside repo",
            "--risks",
            "none",
            "--command",
            "echo undock",
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

    handoff = _run_dock(["undock", f"  {git_repo.name}  ", "--handoff"], cwd=tmp_path, env=env).stdout
    assert "Undock handoff/json objective" in handoff
    assert "### Dockyard Handoff" in handoff

    payload = json.loads(
        _run_dock(["undock", f"  {git_repo.name}  ", "--json"], cwd=tmp_path, env=env).stdout
    )
    assert payload["project_name"] == git_repo.name
    assert payload["objective"] == "Undock handoff/json objective"


@pytest.mark.parametrize("command_name", ["save", "s", "dock"])
def test_review_open_shows_associated_checkpoint(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Auto-created review should link back to associated checkpoint details."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    security_dir = git_repo / "security"
    security_dir.mkdir(exist_ok=True)
    (security_dir / "guard.py").write_text("print('guard')\n", encoding="utf-8")

    _run_dock(
        [
            command_name,
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"Trigger risky review linkage ({command_name})",
            "--decisions",
            "Touch security path to create heuristic review",
            "--next-step",
            "Inspect review open output",
            "--risks",
            "Security review required",
            "--command",
            "echo review",
            "--no-tests-run",
            "--build-fail",
            "--lint-fail",
            "--smoke-fail",
        ],
        cwd=git_repo,
        env=env,
    )

    list_result = _run_dock(["review"], cwd=tmp_path, env=env)
    review_match = re.search(r"rev_[a-f0-9]+", list_result.stdout)
    assert review_match is not None
    review_id = review_match.group(0)

    open_result = _run_dock(["review", "open", review_id], cwd=tmp_path, env=env)
    assert "Review Item" in open_result.stdout
    assert "checkpoint_id: cp_" in open_result.stdout
    assert "Associated Checkpoint" in open_result.stdout
    assert f"Trigger risky review linkage ({command_name})" in open_result.stdout


@pytest.mark.parametrize("command_name", ["save", "s", "dock"])
def test_review_open_shows_missing_checkpoint_notice(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Review open should indicate when checkpoint link is missing."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            command_name,
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"Missing checkpoint notice baseline ({command_name})",
            "--decisions",
            "Create manual review tied to fake checkpoint id",
            "--next-step",
            "Open review and inspect message",
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

    created = _run_dock(
        [
            "review",
            "add",
            "--reason",
            "manual_missing_link",
            "--severity",
            "low",
            "--checkpoint-id",
            "cp_missing_123",
        ],
        cwd=git_repo,
        env=env,
    )
    review_match = re.search(r"rev_[a-f0-9]+", created.stdout)
    assert review_match is not None
    review_id = review_match.group(0)

    opened = _run_dock(["review", "open", review_id], cwd=tmp_path, env=env)
    assert "Associated Checkpoint" in opened.stdout
    assert "checkpoint_id: cp_missing_123" in opened.stdout
    assert "status: missing from index" in opened.stdout


@pytest.mark.parametrize("command_name", ["save", "s", "dock"])
def test_review_open_displays_file_list(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Review open output should include associated file paths."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            command_name,
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"Review file display baseline ({command_name})",
            "--decisions",
            "Create review with file metadata",
            "--next-step",
            "Open review details",
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
    created = _run_dock(
        [
            "review",
            "add",
            "--reason",
            "file_display",
            "--severity",
            "low",
            "--file",
            "src/a.py",
            "--file",
            "src/b.py",
        ],
        cwd=git_repo,
        env=env,
    )
    review_match = re.search(r"rev_[a-f0-9]+", created.stdout)
    assert review_match is not None
    review_id = review_match.group(0)

    opened = _run_dock(["review", "open", review_id], cwd=tmp_path, env=env)
    assert "files: src/a.py, src/b.py" in opened.stdout


@pytest.mark.parametrize("command_name", ["save", "s", "dock"])
def test_review_open_displays_notes(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Review open output should include optional notes text."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            command_name,
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"Review notes baseline ({command_name})",
            "--decisions",
            "Create review with notes",
            "--next-step",
            "Open review details",
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
    created = _run_dock(
        [
            "review",
            "add",
            "--reason",
            "notes_display",
            "--severity",
            "low",
            "--notes",
            "needs careful review",
        ],
        cwd=git_repo,
        env=env,
    )
    review_match = re.search(r"rev_[a-f0-9]+", created.stdout)
    assert review_match is not None
    review_id = review_match.group(0)

    opened = _run_dock(["review", "open", review_id], cwd=tmp_path, env=env)
    assert "created_at:" in opened.stdout
    assert "checkpoint_id: (none)" in opened.stdout
    assert "notes: needs careful review" in opened.stdout


def test_review_add_outside_repo_requires_explicit_context(tmp_path: Path) -> None:
    """Review add should fail outside git repo when repo/branch are omitted."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    failed = _run_dock(
        ["review", "add", "--reason", "no_context", "--severity", "low"],
        cwd=tmp_path,
        env=env,
        expect_code=2,
    )
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "not inside a git repository" in output
    assert "Traceback" not in output


def test_review_add_outside_repo_with_explicit_context_succeeds(tmp_path: Path) -> None:
    """Review add should work outside repo when repo and branch are provided."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    created = _run_dock(
        [
            "review",
            "add",
            "--reason",
            "manual_outside_repo",
            "--severity",
            "med",
            "--repo",
            "manual_repo",
            "--branch",
            "manual_branch",
        ],
        cwd=tmp_path,
        env=env,
    )
    assert "Created review" in created.stdout

    listed = _run_dock(["review", "--all"], cwd=tmp_path, env=env).stdout
    assert "manual_repo/manual_branch" in listed
    assert "manual_outside_repo" in listed


def test_review_add_partial_override_requires_both_repo_and_branch(tmp_path: Path) -> None:
    """Partial context overrides should fail with actionable guidance."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    failed = _run_dock(
        [
            "review",
            "add",
            "--reason",
            "partial_override",
            "--severity",
            "low",
            "--repo",
            "manual_repo_only",
        ],
        cwd=tmp_path,
        env=env,
        expect_code=2,
    )
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "Provide both --repo and --branch when overriding context." in output
    assert "Traceback" not in output

    failed_branch_only = _run_dock(
        [
            "review",
            "add",
            "--reason",
            "partial_override_branch_only",
            "--severity",
            "low",
            "--branch",
            "manual_branch_only",
        ],
        cwd=tmp_path,
        env=env,
        expect_code=2,
    )
    output_branch_only = f"{failed_branch_only.stdout}\n{failed_branch_only.stderr}"
    assert "Provide both --repo and --branch when overriding context." in output_branch_only
    assert "Traceback" not in output_branch_only


def test_review_add_rejects_blank_repo_or_branch_override(tmp_path: Path) -> None:
    """Review add should reject blank repo/branch override values."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    blank_repo = _run_dock(
        [
            "review",
            "add",
            "--reason",
            "blank_repo",
            "--severity",
            "low",
            "--repo",
            "   ",
            "--branch",
            "main",
        ],
        cwd=tmp_path,
        env=env,
        expect_code=2,
    )
    blank_repo_output = f"{blank_repo.stdout}\n{blank_repo.stderr}"
    assert "--repo must be a non-empty string." in blank_repo_output
    assert "Traceback" not in blank_repo_output

    blank_branch = _run_dock(
        [
            "review",
            "add",
            "--reason",
            "blank_branch",
            "--severity",
            "low",
            "--repo",
            "manual_repo",
            "--branch",
            "   ",
        ],
        cwd=tmp_path,
        env=env,
        expect_code=2,
    )
    blank_branch_output = f"{blank_branch.stdout}\n{blank_branch.stderr}"
    assert "--branch must be a non-empty string." in blank_branch_output
    assert "Traceback" not in blank_branch_output


def test_review_add_accepts_berth_name_override(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Review add should resolve berth name in --repo override."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Berth name review add baseline",
            "--decisions",
            "Need berth metadata available",
            "--next-step",
            "create manual review by berth name",
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
    repo_id = json.loads(_run_dock(["resume", "--json"], cwd=git_repo, env=env).stdout)["repo_id"]

    _run_dock(
        [
            "review",
            "add",
            "--reason",
            "berth_name_override",
            "--severity",
            "low",
            "--repo",
            git_repo.name,
            "--branch",
            branch,
        ],
        cwd=tmp_path,
        env=env,
    )
    listed = _run_dock(["review"], cwd=tmp_path, env=env).stdout
    assert f"{repo_id}/{branch}" in listed
    assert "berth_name_override" in listed


def test_review_add_prefers_repo_id_over_colliding_berth_name(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Review add should resolve exact repo-id before colliding berth names."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    branch = _git_current_branch(git_repo)

    other_repo = tmp_path / "review-collision-other"
    other_repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=str(other_repo), check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "dockyard@example.com"],
        cwd=str(other_repo),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Dockyard Test"],
        cwd=str(other_repo),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", "git@github.com:org/review-other.git"],
        cwd=str(other_repo),
        check=True,
        capture_output=True,
    )
    (other_repo / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=str(other_repo), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=str(other_repo), check=True, capture_output=True)

    _run_dock(
        [
            "save",
            "--root",
            str(other_repo),
            "--no-prompt",
            "--objective",
            "review-collision-other",
            "--decisions",
            "other berth setup for review override collision test",
            "--next-step",
            "add review using repo id",
            "--risks",
            "none",
            "--command",
            "echo other",
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
        cwd=other_repo,
        env=env,
    )
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "review-collision-target",
            "--decisions",
            "target berth setup for review override collision test",
            "--next-step",
            "add review using repo id",
            "--risks",
            "none",
            "--command",
            "echo target",
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

    db_path = tmp_path / ".dockyard_data" / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    target_repo_id = conn.execute(
        "SELECT repo_id FROM berths WHERE root_path = ?",
        (str(git_repo),),
    ).fetchone()[0]
    other_repo_id = conn.execute(
        "SELECT repo_id FROM berths WHERE root_path = ?",
        (str(other_repo),),
    ).fetchone()[0]
    conn.execute("UPDATE berths SET name = ? WHERE repo_id = ?", (target_repo_id, other_repo_id))
    conn.commit()
    conn.close()

    _run_dock(
        [
            "review",
            "add",
            "--reason",
            "review_repo_id_collision",
            "--severity",
            "low",
            "--repo",
            target_repo_id,
            "--branch",
            branch,
        ],
        cwd=tmp_path,
        env=env,
    )
    listed = _run_dock(["review"], cwd=tmp_path, env=env).stdout
    assert f"{target_repo_id}/{branch}" in listed
    assert f"{other_repo_id}/{branch}" not in listed
    assert "review_repo_id_collision" in listed


def test_save_repo_id_uses_non_origin_remote_when_origin_missing(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Save/resume flow should derive repo id from non-origin remote fallback."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    subprocess.run(
        ["git", "remote", "remove", "origin"],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )
    upstream_url = "https://example.com/team/fallback-upstream.git"
    subprocess.run(
        ["git", "remote", "add", "upstream", upstream_url],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Repo id non-origin fallback objective",
            "--decisions",
            "Derive repo id from upstream remote",
            "--next-step",
            "assert deterministic repo id fallback",
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

    payload = json.loads(_run_dock(["resume", "--json"], cwd=git_repo, env=env).stdout)
    assert payload["repo_id"] == hashlib.sha1(upstream_url.encode("utf-8")).hexdigest()[:16]


def test_save_repo_id_falls_back_to_path_hash_when_origin_is_blank(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Save/resume flow should path-hash repo id when remotes are unusable."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    subprocess.run(
        ["git", "config", "remote.origin.url", ""],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Repo id path fallback objective",
            "--decisions",
            "Derive repo id from repo path hash",
            "--next-step",
            "assert deterministic path fallback repo id",
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

    payload = json.loads(_run_dock(["resume", "--json"], cwd=git_repo, env=env).stdout)
    assert payload["repo_id"] == hashlib.sha1(str(git_repo).encode("utf-8")).hexdigest()[:16]


def test_save_repo_id_prefers_origin_when_multiple_remotes_exist(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Save/resume flow should prioritize origin URL over other remotes."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    origin_url = subprocess.run(
        ["git", "config", "--get", "remote.origin.url"],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "remote", "add", "upstream", "https://example.com/team/upstream.git"],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Repo id origin preference objective",
            "--decisions",
            "Use origin even when other remotes exist",
            "--next-step",
            "assert origin preference repo id",
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

    payload = json.loads(_run_dock(["resume", "--json"], cwd=git_repo, env=env).stdout)
    assert payload["repo_id"] == hashlib.sha1(origin_url.encode("utf-8")).hexdigest()[:16]


@pytest.mark.parametrize("command_name", ["save", "s", "dock"])
def test_save_aliases_use_non_origin_remote_for_repo_id_fallback(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Save command aliases should honor non-origin remote repo-id fallback."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    subprocess.run(
        ["git", "remote", "remove", "origin"],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )
    upstream_url = "https://example.com/team/alias-fallback-upstream.git"
    subprocess.run(
        ["git", "remote", "add", "upstream", upstream_url],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )

    _run_dock(
        [
            command_name,
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"{command_name} alias non-origin repo-id objective",
            "--decisions",
            "Use non-origin remote in alias fallback flow",
            "--next-step",
            "assert alias fallback repo id",
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

    payload = json.loads(_run_dock(["resume", "--json"], cwd=git_repo, env=env).stdout)
    assert payload["repo_id"] == hashlib.sha1(upstream_url.encode("utf-8")).hexdigest()[:16]


@pytest.mark.parametrize("command_name", ["save", "s", "dock"])
def test_save_aliases_use_path_hash_repo_id_fallback_when_origin_blank(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Save command aliases should path-hash repo id when origin URL is blank."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    subprocess.run(
        ["git", "config", "remote.origin.url", ""],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )

    _run_dock(
        [
            command_name,
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"{command_name} alias path-hash repo-id objective",
            "--decisions",
            "Use path-hash fallback when origin URL is blank",
            "--next-step",
            "assert alias path-hash repo id fallback",
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

    payload = json.loads(_run_dock(["resume", "--json"], cwd=git_repo, env=env).stdout)
    assert payload["repo_id"] == hashlib.sha1(str(git_repo).encode("utf-8")).hexdigest()[:16]


def test_save_repo_id_fallback_remote_ordering_is_case_insensitive(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Save/resume should choose fallback remotes using case-insensitive sort."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    subprocess.run(
        ["git", "remote", "remove", "origin"],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )
    alpha_url = "https://example.com/team/alpha.git"
    subprocess.run(
        ["git", "remote", "add", "Zeta", "https://example.com/team/zeta.git"],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "remote", "add", "alpha", alpha_url],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Repo id case-insensitive fallback objective",
            "--decisions",
            "Prefer alpha before Zeta in fallback ordering",
            "--next-step",
            "assert case-insensitive fallback ordering",
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

    payload = json.loads(_run_dock(["resume", "--json"], cwd=git_repo, env=env).stdout)
    assert payload["repo_id"] == hashlib.sha1(alpha_url.encode("utf-8")).hexdigest()[:16]


def test_save_repo_id_fallback_remote_case_collision_ordering_is_deterministic(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Save/resume should deterministically resolve case-colliding remotes."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    subprocess.run(
        ["git", "remote", "remove", "origin"],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )
    alpha_upper_url = "https://example.com/team/alpha-upper.git"
    subprocess.run(
        ["git", "remote", "add", "alpha", "https://example.com/team/alpha-lower.git"],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "remote", "add", "Alpha", alpha_upper_url],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Repo id case-collision fallback objective",
            "--decisions",
            "Use deterministic ordering for case-colliding remote names",
            "--next-step",
            "assert deterministic case-collision ordering",
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

    payload = json.loads(_run_dock(["resume", "--json"], cwd=git_repo, env=env).stdout)
    assert payload["repo_id"] == hashlib.sha1(alpha_upper_url.encode("utf-8")).hexdigest()[:16]


def test_review_add_accepts_trimmed_repo_and_branch_override(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Review add should trim repo/branch override values."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Trimmed override baseline",
            "--decisions",
            "Ensure override values are normalized",
            "--next-step",
            "create manual review",
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
    repo_id = json.loads(_run_dock(["resume", "--json"], cwd=git_repo, env=env).stdout)["repo_id"]

    _run_dock(
        [
            "review",
            "add",
            "--reason",
            "trimmed_override",
            "--severity",
            "low",
            "--repo",
            f"  {git_repo.name}  ",
            "--branch",
            f"  {branch}  ",
        ],
        cwd=tmp_path,
        env=env,
    )
    listed = _run_dock(["review"], cwd=tmp_path, env=env).stdout
    assert f"{repo_id}/{branch}" in listed
    assert "trimmed_override" in listed


def test_review_lifecycle_recomputes_slip_status(git_repo: Path, tmp_path: Path) -> None:
    """Slip status should reflect review add/done transitions."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Status recompute baseline",
            "--decisions",
            "Start with verified checkpoint so status is green",
            "--next-step",
            "Add high review then resolve it",
            "--risks",
            "None",
            "--command",
            "echo status",
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

    initial_rows = json.loads(_run_dock(["ls", "--json"], cwd=tmp_path, env=env).stdout)
    assert initial_rows[0]["status"] == "green"

    review_added = _run_dock(
        [
            "review",
            "add",
            "--reason",
            "critical_validation",
            "--severity",
            "high",
        ],
        cwd=git_repo,
        env=env,
    )
    review_match = re.search(r"rev_[a-f0-9]+", review_added.stdout)
    assert review_match is not None
    review_id = review_match.group(0)

    after_add_rows = json.loads(_run_dock(["ls", "--json"], cwd=tmp_path, env=env).stdout)
    assert after_add_rows[0]["status"] == "red"

    _run_dock(["review", "done", review_id], cwd=tmp_path, env=env)
    after_done_rows = json.loads(_run_dock(["ls", "--json"], cwd=tmp_path, env=env).stdout)
    assert after_done_rows[0]["status"] == "green"


def test_review_cli_list_prioritizes_high_severity(git_repo: Path, tmp_path: Path) -> None:
    """Review CLI listing should show high-severity items before lower ones."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Review ordering baseline",
            "--decisions",
            "Need slip context for manual review items",
            "--next-step",
            "Add low then high review items",
            "--risks",
            "None",
            "--command",
            "echo reviews",
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

    _run_dock(
        ["review", "add", "--reason", "low_item", "--severity", "low"],
        cwd=git_repo,
        env=env,
    )
    _run_dock(
        ["review", "add", "--reason", "high_item", "--severity", "high"],
        cwd=git_repo,
        env=env,
    )

    review_output = _run_dock(["review"], cwd=tmp_path, env=env).stdout
    lines = [line for line in review_output.splitlines() if line.strip()]
    assert len(lines) >= 2
    assert "high_item" in lines[0]
    assert "low_item" in lines[1]
    review_list_output = _run_dock(["review", "list"], cwd=tmp_path, env=env).stdout
    list_lines = [line for line in review_list_output.splitlines() if line.strip()]
    assert len(list_lines) >= 2
    assert "high_item" in list_lines[0]
    assert "low_item" in list_lines[1]


def test_review_default_command_supports_all_flag(git_repo: Path, tmp_path: Path) -> None:
    """`dock review --all` should include resolved items without subcommand."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Review all flag baseline",
            "--decisions",
            "Need context for manual review lifecycle",
            "--next-step",
            "Create and resolve review",
            "--risks",
            "None",
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
        ],
        cwd=git_repo,
        env=env,
    )

    created = _run_dock(
        ["review", "add", "--reason", "all_flag_item", "--severity", "low"],
        cwd=git_repo,
        env=env,
    )
    review_match = re.search(r"rev_[a-f0-9]+", created.stdout)
    assert review_match is not None
    review_id = review_match.group(0)

    _run_dock(["review", "done", review_id], cwd=tmp_path, env=env)

    open_only = _run_dock(["review"], cwd=tmp_path, env=env).stdout
    assert "all_flag_item" not in open_only

    with_all = _run_dock(["review", "--all"], cwd=tmp_path, env=env).stdout
    assert "all_flag_item" in with_all
    assert "done" in with_all
    with_all_subcommand = _run_dock(["review", "list", "--all"], cwd=tmp_path, env=env).stdout
    assert "all_flag_item" in with_all_subcommand
    assert "done" in with_all_subcommand


def test_review_listing_tie_breaks_by_recency_within_same_severity(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Review listings should order same-severity items by newest timestamp."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Review recency tie-break baseline",
            "--decisions",
            "Ensure same-severity reviews sort by recency",
            "--next-step",
            "list review items",
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
        ],
        cwd=git_repo,
        env=env,
    )

    created_older = _run_dock(
        ["review", "add", "--reason", "recency_older", "--severity", "med"],
        cwd=git_repo,
        env=env,
    )
    older_match = re.search(r"rev_[a-f0-9]+", created_older.stdout)
    assert older_match is not None
    older_id = older_match.group(0)

    created_newer = _run_dock(
        ["review", "add", "--reason", "recency_newer", "--severity", "med"],
        cwd=git_repo,
        env=env,
    )
    newer_match = re.search(r"rev_[a-f0-9]+", created_newer.stdout)
    assert newer_match is not None
    newer_id = newer_match.group(0)

    db_path = dock_home / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE review_items SET created_at = ? WHERE id = ?", ("2000-01-01T00:00:00+00:00", older_id))
    conn.execute("UPDATE review_items SET created_at = ? WHERE id = ?", ("2005-01-01T00:00:00+00:00", newer_id))
    conn.commit()
    conn.close()

    default_output = _run_dock(["review"], cwd=tmp_path, env=env).stdout
    list_output = _run_dock(["review", "list"], cwd=tmp_path, env=env).stdout

    default_ids = re.findall(r"rev_[a-f0-9]+", default_output)
    list_ids = re.findall(r"rev_[a-f0-9]+", list_output)
    assert newer_id in default_ids and older_id in default_ids
    assert newer_id in list_ids and older_id in list_ids
    assert default_ids.index(newer_id) < default_ids.index(older_id)
    assert list_ids.index(newer_id) < list_ids.index(older_id)


def test_review_list_subcommand_matches_default_listing(git_repo: Path, tmp_path: Path) -> None:
    """`review list` should mirror default `review` open-item listing."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Review list parity objective",
            "--decisions",
            "Validate review list subcommand parity",
            "--next-step",
            "compare review outputs",
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
        ],
        cwd=git_repo,
        env=env,
    )
    created = _run_dock(
        ["review", "add", "--reason", "list_parity_item", "--severity", "med"],
        cwd=git_repo,
        env=env,
    )
    review_match = re.search(r"rev_[a-f0-9]+", created.stdout)
    assert review_match is not None
    review_id = review_match.group(0)

    default_listing = _run_dock(["review"], cwd=tmp_path, env=env).stdout
    list_listing = _run_dock(["review", "list"], cwd=tmp_path, env=env).stdout
    assert review_id in default_listing
    assert review_id in list_listing
    assert "list_parity_item" in default_listing
    assert "list_parity_item" in list_listing


def test_review_list_all_subcommand_matches_default_all_listing(git_repo: Path, tmp_path: Path) -> None:
    """`review list --all` should mirror default `review --all` ordering/content."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Review list --all parity objective",
            "--decisions",
            "Validate review --all and review list --all parity",
            "--next-step",
            "compare all-review outputs",
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
        ],
        cwd=git_repo,
        env=env,
    )

    created_open = _run_dock(
        ["review", "add", "--reason", "all_parity_open", "--severity", "high"],
        cwd=git_repo,
        env=env,
    )
    open_match = re.search(r"rev_[a-f0-9]+", created_open.stdout)
    assert open_match is not None
    open_id = open_match.group(0)

    created_done = _run_dock(
        ["review", "add", "--reason", "all_parity_done", "--severity", "low"],
        cwd=git_repo,
        env=env,
    )
    done_match = re.search(r"rev_[a-f0-9]+", created_done.stdout)
    assert done_match is not None
    done_id = done_match.group(0)

    _run_dock(["review", "done", done_id], cwd=tmp_path, env=env)

    default_all = _run_dock(["review", "--all"], cwd=tmp_path, env=env).stdout
    list_all = _run_dock(["review", "list", "--all"], cwd=tmp_path, env=env).stdout

    assert open_id in default_all and done_id in default_all
    assert open_id in list_all and done_id in list_all
    assert "all_parity_open" in default_all and "all_parity_done" in default_all
    assert "all_parity_open" in list_all and "all_parity_done" in list_all
    assert re.findall(r"rev_[a-f0-9]+", default_all) == re.findall(r"rev_[a-f0-9]+", list_all)


def test_review_done_unknown_id_is_actionable(tmp_path: Path) -> None:
    """Unknown review id resolution should fail without traceback noise."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    failed = _run_dock(["review", "done", "rev_missing"], cwd=tmp_path, env=env, expect_code=2)
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "Review item not found: rev_missing" in output
    assert "Traceback" not in output


def test_review_done_accepts_trimmed_review_id(git_repo: Path, tmp_path: Path) -> None:
    """Review done should accept review IDs with surrounding whitespace."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Review done trimmed id baseline",
            "--decisions",
            "Need review context",
            "--next-step",
            "resolve review by padded id",
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
        ],
        cwd=git_repo,
        env=env,
    )
    created = _run_dock(
        ["review", "add", "--reason", "trimmed_done", "--severity", "low"],
        cwd=git_repo,
        env=env,
    )
    review_match = re.search(r"rev_[a-f0-9]+", created.stdout)
    assert review_match is not None
    review_id = review_match.group(0)

    resolved = _run_dock(["review", "done", f"  {review_id}  "], cwd=tmp_path, env=env).stdout
    assert f"Resolved review {review_id}" in resolved


def test_review_open_accepts_trimmed_review_id(git_repo: Path, tmp_path: Path) -> None:
    """Review open should accept review IDs with surrounding whitespace."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Review open trimmed id baseline",
            "--decisions",
            "Need review context",
            "--next-step",
            "open review by padded id",
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
        ],
        cwd=git_repo,
        env=env,
    )
    created = _run_dock(
        ["review", "add", "--reason", "trimmed_open", "--severity", "low"],
        cwd=git_repo,
        env=env,
    )
    review_match = re.search(r"rev_[a-f0-9]+", created.stdout)
    assert review_match is not None
    review_id = review_match.group(0)

    opened = _run_dock(["review", "open", f"  {review_id}  "], cwd=tmp_path, env=env).stdout
    assert f"id: {review_id}" in opened


def test_review_done_and_open_reject_blank_review_ids(tmp_path: Path) -> None:
    """Review done/open should reject blank review IDs."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    done_failed = _run_dock(["review", "done", "   "], cwd=tmp_path, env=env, expect_code=2)
    done_output = f"{done_failed.stdout}\n{done_failed.stderr}"
    assert "Review ID must be a non-empty string." in done_output
    assert "Traceback" not in done_output

    open_failed = _run_dock(["review", "open", "   "], cwd=tmp_path, env=env, expect_code=2)
    open_output = f"{open_failed.stdout}\n{open_failed.stderr}"
    assert "Review ID must be a non-empty string." in open_output
    assert "Traceback" not in open_output


def test_review_all_with_no_items_is_informative(tmp_path: Path) -> None:
    """Review --all should report no items when ledger is empty."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    result = _run_dock(["review", "--all"], cwd=tmp_path, env=env)
    assert "No review items." in result.stdout


def test_review_list_all_with_no_items_is_informative(tmp_path: Path) -> None:
    """`review list --all` should render empty-ledger guidance."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    result = _run_dock(["review", "list", "--all"], cwd=tmp_path, env=env)
    assert "No review items." in result.stdout


def test_review_list_with_no_items_is_informative(tmp_path: Path) -> None:
    """`review list` should render empty-ledger guidance."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    result = _run_dock(["review", "list"], cwd=tmp_path, env=env)
    assert "No review items." in result.stdout


def test_review_add_validates_severity(git_repo: Path, tmp_path: Path) -> None:
    """Review add should reject severities outside low/med/high."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Severity validation baseline",
            "--decisions",
            "Need repo context for review add",
            "--next-step",
            "Try invalid severity",
            "--risks",
            "None",
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

    bad = _run_dock(
        ["review", "add", "--reason", "invalid", "--severity", "critical"],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{bad.stdout}\n{bad.stderr}"
    assert "Invalid severity" in output
    assert "Traceback" not in output

    blank = _run_dock(
        ["review", "add", "--reason", "invalid", "--severity", "   "],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    blank_output = f"{blank.stdout}\n{blank.stderr}"
    assert "Severity must be a non-empty string." in blank_output
    assert "Traceback" not in blank_output

    # Upper-case values should normalize successfully.
    good = _run_dock(
        ["review", "add", "--reason", "valid", "--severity", "HIGH"],
        cwd=git_repo,
        env=env,
    )
    assert "Created review" in good.stdout


def test_review_add_requires_non_empty_reason(git_repo: Path, tmp_path: Path) -> None:
    """Review add should reject empty/whitespace reason strings."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Reason validation baseline",
            "--decisions",
            "Need repo context for review add",
            "--next-step",
            "try empty reason",
            "--risks",
            "None",
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

    bad = _run_dock(
        ["review", "add", "--reason", "   ", "--severity", "low"],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{bad.stdout}\n{bad.stderr}"
    assert "--reason must be a non-empty string." in output
    assert "Traceback" not in output


def test_review_add_trims_reason_whitespace(git_repo: Path, tmp_path: Path) -> None:
    """Review reason should be trimmed before persistence."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Reason trimming baseline",
            "--decisions",
            "Need context for manual review add",
            "--next-step",
            "create review with padded reason",
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
    created = _run_dock(
        ["review", "add", "--reason", "   padded_reason   ", "--severity", "low"],
        cwd=git_repo,
        env=env,
    )
    review_match = re.search(r"rev_[a-f0-9]+", created.stdout)
    assert review_match is not None
    review_id = review_match.group(0)

    opened = _run_dock(["review", "open", review_id], cwd=tmp_path, env=env)
    assert "reason: padded_reason" in opened.stdout


def test_review_add_trims_notes_and_checkpoint_id(git_repo: Path, tmp_path: Path) -> None:
    """Review add should trim notes and checkpoint-id fields."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Review optional field trimming baseline",
            "--decisions",
            "Ensure notes and checkpoint-id are normalized",
            "--next-step",
            "open review details",
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
    created = _run_dock(
        [
            "review",
            "add",
            "--reason",
            "trim optional fields",
            "--severity",
            "low",
            "--checkpoint-id",
            "  cp_trim_test  ",
            "--notes",
            "  keep this note  ",
        ],
        cwd=git_repo,
        env=env,
    )
    review_match = re.search(r"rev_[a-f0-9]+", created.stdout)
    assert review_match is not None
    review_id = review_match.group(0)

    opened = _run_dock(["review", "open", review_id], cwd=tmp_path, env=env).stdout
    assert "checkpoint_id: cp_trim_test" in opened
    assert "notes: keep this note" in opened
    assert "checkpoint_id:   cp_trim_test" not in opened
    assert "notes:   keep this note" not in opened


def test_review_add_blank_checkpoint_id_is_treated_as_missing(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Blank checkpoint-id input should not trigger missing-checkpoint panel."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Blank checkpoint id baseline",
            "--decisions",
            "Ensure blank checkpoint id normalizes to None",
            "--next-step",
            "open review",
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
    created = _run_dock(
        [
            "review",
            "add",
            "--reason",
            "blank checkpoint id",
            "--severity",
            "low",
            "--checkpoint-id",
            "   ",
            "--notes",
            "   ",
        ],
        cwd=git_repo,
        env=env,
    )
    review_match = re.search(r"rev_[a-f0-9]+", created.stdout)
    assert review_match is not None
    review_id = review_match.group(0)

    opened = _run_dock(["review", "open", review_id], cwd=tmp_path, env=env).stdout
    assert "checkpoint_id: (none)" in opened
    assert "notes: (none)" in opened
    assert "Associated Checkpoint" not in opened


def test_review_list_compacts_multiline_reason_text(git_repo: Path, tmp_path: Path) -> None:
    """Review list should compact multiline reasons into one-line previews."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Review list multiline reason baseline",
            "--decisions",
            "Need review context",
            "--next-step",
            "add multiline reason review",
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
    _run_dock(
        ["review", "add", "--reason", "line one\nline two", "--severity", "med"],
        cwd=git_repo,
        env=env,
    )

    listed = _run_dock(["review"], cwd=tmp_path, env=env).stdout
    assert "line one line two" in listed
    assert "line one\nline two" not in listed


def test_review_list_falls_back_for_blank_metadata_fields(git_repo: Path, tmp_path: Path) -> None:
    """Review list should show explicit fallbacks for blank row metadata."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Review fallback baseline",
            "--decisions",
            "Corrupt review row text fields",
            "--next-step",
            "run review list",
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
    created = _run_dock(
        ["review", "add", "--reason", "normal reason", "--severity", "med"],
        cwd=git_repo,
        env=env,
    )
    review_match = re.search(r"rev_[a-f0-9]+", created.stdout)
    assert review_match is not None
    review_id = review_match.group(0)

    db_path = dock_home / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        (
            "UPDATE review_items "
            "SET severity = ?, status = ?, repo_id = ?, branch = ?, reason = ? "
            "WHERE id = ?"
        ),
        ("   ", "   ", "   ", "   ", "   ", review_id),
    )
    conn.commit()
    conn.close()

    listed = _run_dock(["review", "--all"], cwd=tmp_path, env=env).stdout
    assert "(unknown) | (unknown)" in listed
    assert "(unknown)/(unknown)" in listed
    assert "| (none)" in listed


@pytest.mark.parametrize("command_name", ["save", "s", "dock"])
def test_review_outputs_preserve_literal_markup_like_text(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Review list/open output should preserve literal bracketed text."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            command_name,
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"Review literal text baseline ({command_name})",
            "--decisions",
            "Need context for manual review add",
            "--next-step",
            "create review with bracketed fields",
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
    created = _run_dock(
        [
            "review",
            "add",
            "--reason",
            "[red]urgent[/red]",
            "--severity",
            "low",
            "--notes",
            "[bold]needs eyes[/bold]",
            "--file",
            "[cyan]src/core.py[/cyan]",
        ],
        cwd=git_repo,
        env=env,
    )
    review_match = re.search(r"rev_[a-f0-9]+", created.stdout)
    assert review_match is not None
    review_id = review_match.group(0)

    listed = _run_dock(["review"], cwd=tmp_path, env=env).stdout
    assert "[red]urgent[/red]" in listed

    opened = _run_dock(["review", "open", review_id], cwd=tmp_path, env=env).stdout
    assert "reason: [red]urgent[/red]" in opened
    assert "notes: [bold]needs eyes[/bold]" in opened
    assert "files: [cyan]src/core.py[/cyan]" in opened


@pytest.mark.parametrize("command_name", ["save", "s", "dock"])
def test_review_open_compacts_multiline_metadata_fields(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Review open output should compact multiline metadata values."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            command_name,
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"Review open compaction baseline ({command_name})",
            "--decisions",
            "Need review context",
            "--next-step",
            "create multiline review metadata",
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
    created = _run_dock(
        [
            "review",
            "add",
            "--reason",
            "reason line one\nline two",
            "--severity",
            "med",
            "--notes",
            "notes line one\nline two",
            "--file",
            "src/one.py\nsrc/two.py",
        ],
        cwd=git_repo,
        env=env,
    )
    review_match = re.search(r"rev_[a-f0-9]+", created.stdout)
    assert review_match is not None
    review_id = review_match.group(0)

    opened = _run_dock(["review", "open", review_id], cwd=tmp_path, env=env).stdout
    assert "reason: reason line one line two" in opened
    assert "notes: notes line one line two" in opened
    assert "files: src/one.py src/two.py" in opened


@pytest.mark.parametrize("command_name", ["save", "s", "dock"])
def test_review_open_falls_back_for_blank_metadata_fields(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Review open should show explicit fallbacks for blank metadata."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)

    _run_dock(
        [
            command_name,
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"Review open fallback baseline ({command_name})",
            "--decisions",
            "Mutate review row metadata to blanks",
            "--next-step",
            "run review open",
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
    created = _run_dock(
        ["review", "add", "--reason", "normal reason", "--severity", "med"],
        cwd=git_repo,
        env=env,
    )
    review_match = re.search(r"rev_[a-f0-9]+", created.stdout)
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

    opened = _run_dock(["review", "open", review_id], cwd=tmp_path, env=env).stdout
    assert "repo: (unknown)" in opened
    assert "branch: (unknown)" in opened
    assert "created_at: (unknown)" in opened
    assert "checkpoint_id: (none)" in opened
    assert "severity: (unknown)" in opened
    assert "status: (unknown)" in opened
    assert "reason: (none)" in opened
    assert "notes: (none)" in opened
    assert "files: (none)" in opened


@pytest.mark.parametrize("command_name", ["save", "s", "dock"])
def test_review_open_handles_scalar_files_payload(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Review open should coerce scalar files payload to a single file string."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)

    _run_dock(
        [
            command_name,
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"Scalar files payload baseline ({command_name})",
            "--decisions",
            "Mutate review files to scalar string",
            "--next-step",
            "run review open",
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
    created = _run_dock(
        ["review", "add", "--reason", "files scalar", "--severity", "low"],
        cwd=git_repo,
        env=env,
    )
    review_match = re.search(r"rev_[a-f0-9]+", created.stdout)
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

    opened = _run_dock(["review", "open", review_id], cwd=tmp_path, env=env).stdout
    assert "files: src/scalar.py" in opened


def test_review_add_ignores_blank_file_entries(git_repo: Path, tmp_path: Path) -> None:
    """Review add should drop blank file entries before persistence."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Review file normalization baseline",
            "--decisions",
            "Ensure blank --file values are ignored",
            "--next-step",
            "open created review",
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
    created = _run_dock(
        [
            "review",
            "add",
            "--reason",
            "file normalization",
            "--severity",
            "low",
            "--file",
            "   ",
            "--file",
            "src/real.py",
        ],
        cwd=git_repo,
        env=env,
    )
    review_match = re.search(r"rev_[a-f0-9]+", created.stdout)
    assert review_match is not None
    review_id = review_match.group(0)

    opened = _run_dock(["review", "open", review_id], cwd=tmp_path, env=env).stdout
    assert "files: src/real.py" in opened
    assert "files: (none)" not in opened


def test_review_add_deduplicates_file_entries(git_repo: Path, tmp_path: Path) -> None:
    """Review add should de-duplicate repeated file entries."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Review file dedupe baseline",
            "--decisions",
            "Ensure repeated --file values are de-duplicated",
            "--next-step",
            "open created review",
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
    created = _run_dock(
        [
            "review",
            "add",
            "--reason",
            "file dedupe",
            "--severity",
            "low",
            "--file",
            " src/dup.py ",
            "--file",
            "src/dup.py",
            "--file",
            "src/other.py",
            "--file",
            "src/dup.py",
        ],
        cwd=git_repo,
        env=env,
    )
    review_match = re.search(r"rev_[a-f0-9]+", created.stdout)
    assert review_match is not None
    review_id = review_match.group(0)

    opened = _run_dock(["review", "open", review_id], cwd=tmp_path, env=env).stdout
    assert "files: src/dup.py, src/other.py" in opened
    assert "src/dup.py, src/dup.py" not in opened


def test_save_with_template_no_prompt(git_repo: Path, tmp_path: Path) -> None:
    """Template-based save should work in no-prompt mode."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    template_path = tmp_path / "save_template.json"
    template_path.write_text(
        json.dumps(
            {
                "objective": "Template checkpoint objective",
                "decisions": "Template decisions block",
                "next_steps": ["Template next step 1", "Template next step 2"],
                "risks_review": "Template risk notes",
                "resume_commands": ["echo template-cmd"],
                "tags": ["template", "mvp"],
                "links": ["https://example.com/template-doc"],
                "verification": {
                    "tests_run": True,
                    "tests_command": "pytest -q",
                    "build_ok": True,
                    "build_command": "echo build",
                    "lint_ok": False,
                    "smoke_ok": False,
                },
            }
        ),
        encoding="utf-8",
    )

    _run_dock(
        [
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

    resume_payload = json.loads(_run_dock(["resume", "--json"], cwd=git_repo, env=env).stdout)
    assert resume_payload["objective"] == "Template checkpoint objective"
    assert resume_payload["next_steps"] == ["Template next step 1", "Template next step 2"]
    assert resume_payload["verification"]["tests_run"] is True
    assert resume_payload["verification"]["build_ok"] is True
    assert resume_payload["verification"]["lint_ok"] is False

    links_output = _run_dock(["links"], cwd=git_repo, env=env).stdout
    assert "https://example.com/template-doc" in links_output
    tagged_rows = json.loads(_run_dock(["ls", "--tag", "template", "--json"], cwd=tmp_path, env=env).stdout)
    assert len(tagged_rows) == 1
    assert tagged_rows[0]["branch"] == _git_current_branch(git_repo)


def test_save_with_toml_template_no_prompt(git_repo: Path, tmp_path: Path) -> None:
    """TOML template should be accepted by save --template."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    template_path = tmp_path / "save_template.toml"
    template_path.write_text(
        "\n".join(
            [
                'objective = "TOML objective"',
                'decisions = "TOML decisions"',
                'risks_review = "TOML risk"',
                'next_steps = ["TOML next"]',
                'resume_commands = ["echo toml"]',
                'tags = ["toml"]',
                "",
                "[verification]",
                "tests_run = true",
                'tests_command = "pytest -q"',
                "build_ok = true",
                'build_command = "echo build"',
                "lint_ok = false",
                "smoke_ok = false",
            ]
        ),
        encoding="utf-8",
    )

    _run_dock(
        [
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

    resume_payload = json.loads(_run_dock(["resume", "--json"], cwd=git_repo, env=env).stdout)
    assert resume_payload["objective"] == "TOML objective"
    assert resume_payload["verification"]["tests_run"] is True
    assert resume_payload["verification"]["build_ok"] is True
    tagged_rows = json.loads(_run_dock(["ls", "--tag", "toml", "--json"], cwd=tmp_path, env=env).stdout)
    assert len(tagged_rows) == 1
    assert tagged_rows[0]["branch"] == _git_current_branch(git_repo)


def test_save_template_path_accepts_trimmed_value(git_repo: Path, tmp_path: Path) -> None:
    """Save should resolve template path values after whitespace trimming."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    template_path = tmp_path / "trimmed_template.json"
    template_path.write_text(
        json.dumps(
            {
                "objective": "Trimmed template objective",
                "decisions": "Template path trimming behavior",
                "next_steps": ["run resume"],
                "risks_review": "none",
                "resume_commands": ["echo trimmed-template"],
            }
        ),
        encoding="utf-8",
    )

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--template",
            f"  {template_path}  ",
            "--no-prompt",
            "--no-auto-review",
        ],
        cwd=git_repo,
        env=env,
    )
    payload = json.loads(_run_dock(["resume", "--json"], cwd=git_repo, env=env).stdout)
    assert payload["objective"] == "Trimmed template objective"


def test_save_rejects_blank_template_path(git_repo: Path, tmp_path: Path) -> None:
    """Save should reject blank template option values."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    failed = _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--template",
            "   ",
            "--no-prompt",
            "--objective",
            "fallback objective",
            "--decisions",
            "fallback decisions",
            "--next-step",
            "fallback step",
            "--risks",
            "none",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "--template must be a non-empty string." in output
    assert "Traceback" not in output


def test_save_template_directory_path_is_actionable(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Directory-valued template paths should fail with actionable error text."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    failed = _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--template",
            str(tmp_path),
            "--no-prompt",
            "--objective",
            "fallback objective",
            "--decisions",
            "fallback decisions",
            "--next-step",
            "fallback step",
            "--risks",
            "none",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "Failed to read template:" in output
    assert "Traceback" not in output


def test_save_template_non_utf8_file_is_actionable(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Non-UTF8 template files should fail with actionable read error."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    bad_template = tmp_path / "non_utf8_template.json"
    bad_template.write_bytes(b"\xff\xfe\x00")
    failed = _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--template",
            str(bad_template),
            "--no-prompt",
            "--objective",
            "fallback objective",
            "--decisions",
            "fallback decisions",
            "--next-step",
            "fallback step",
            "--risks",
            "none",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "Failed to read template:" in output
    assert "Traceback" not in output


def test_template_bool_like_strings_are_coerced(git_repo: Path, tmp_path: Path) -> None:
    """Template bool-like strings should coerce to verification booleans."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    template_path = tmp_path / "bool_like_template.json"
    template_path.write_text(
        json.dumps(
            {
                "objective": "Bool-like objective",
                "decisions": "Use string booleans in template",
                "next_steps": ["Run resume json"],
                "risks_review": "none",
                "verification": {
                    "tests_run": "yes",
                    "build_ok": "1",
                    "lint_ok": "no",
                    "smoke_ok": "false",
                },
            }
        ),
        encoding="utf-8",
    )

    _run_dock(
        [
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
    payload = json.loads(_run_dock(["resume", "--json"], cwd=git_repo, env=env).stdout)
    assert payload["verification"]["tests_run"] is True
    assert payload["verification"]["build_ok"] is True
    assert payload["verification"]["lint_ok"] is False
    assert payload["verification"]["smoke_ok"] is False


@pytest.mark.parametrize("command_name", ["save", "s", "dock"])
def test_template_verification_text_fields_are_normalized(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Template verification text fields should trim values and drop blanks."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    template_path = tmp_path / "verification_text_normalization_template.json"
    template_path.write_text(
        json.dumps(
            {
                "objective": "Template verification text normalization objective",
                "decisions": "Trim verification command and note text from template values",
                "next_steps": ["Inspect resume json"],
                "risks_review": "none",
                "verification": {
                    "tests_run": "yes",
                    "tests_command": "   ",
                    "build_ok": "1",
                    "build_command": "  make build  ",
                    "lint_ok": "true",
                    "lint_command": "  ruff check  ",
                    "smoke_ok": "y",
                    "smoke_notes": "  smoke passed  ",
                },
            }
        ),
        encoding="utf-8",
    )

    _run_dock(
        [
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

    payload = json.loads(_run_dock(["resume", "--json"], cwd=git_repo, env=env).stdout)
    verification = payload["verification"]
    assert verification["tests_run"] is True
    assert verification["build_ok"] is True
    assert verification["lint_ok"] is True
    assert verification["smoke_ok"] is True
    assert verification["tests_command"] is None
    assert verification["build_command"] == "make build"
    assert verification["lint_command"] == "ruff check"
    assert verification["smoke_notes"] == "smoke passed"


def test_template_bool_like_invalid_string_is_rejected(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Unknown bool-like strings in template verification should fail."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    bad_template = tmp_path / "bad_bool_like.json"
    bad_template.write_text(
        json.dumps(
            {
                "objective": "Invalid bool-like",
                "decisions": "bad tests_run value",
                "next_steps": ["step"],
                "risks_review": "none",
                "verification": {"tests_run": "maybe"},
            }
        ),
        encoding="utf-8",
    )
    failed = _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--template",
            str(bad_template),
            "--no-prompt",
            "--objective",
            "override",
            "--decisions",
            "override",
            "--next-step",
            "override",
            "--risks",
            "none",
            "--command",
            "echo noop",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "Template field 'tests_run' must be bool or bool-like string" in output
    assert "Traceback" not in output


def test_invalid_config_produces_actionable_error(git_repo: Path, tmp_path: Path) -> None:
    """Invalid config TOML should fail with concise actionable message."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)
    dock_home.mkdir(parents=True, exist_ok=True)
    (dock_home / "config.toml").write_text(
        "[review_heuristics\nfiles_changed_threshold = 4",
        encoding="utf-8",
    )

    result = _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Config parse failure case",
            "--decisions",
            "should fail before saving",
            "--next-step",
            "fix config",
            "--risks",
            "none",
            "--command",
            "echo noop",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{result.stdout}\n{result.stderr}"
    assert "Invalid config TOML" in output
    assert "Traceback" not in output


def test_invalid_regex_config_produces_actionable_error(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Invalid regex config should fail cleanly with actionable messaging."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)
    dock_home.mkdir(parents=True, exist_ok=True)
    (dock_home / "config.toml").write_text(
        "\n".join(
            [
                "[review_heuristics]",
                'risky_path_patterns = ["(^|/)[bad"]',
            ]
        ),
        encoding="utf-8",
    )

    result = _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Regex config failure case",
            "--decisions",
            "should fail before save",
            "--next-step",
            "fix regex",
            "--risks",
            "none",
            "--command",
            "echo noop",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{result.stdout}\n{result.stderr}"
    assert "Invalid regex" in output
    assert "Traceback" not in output


def test_invalid_config_section_type_is_actionable(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Invalid config section type should surface actionable error."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)
    dock_home.mkdir(parents=True, exist_ok=True)
    (dock_home / "config.toml").write_text(
        'review_heuristics = "bad-type"',
        encoding="utf-8",
    )

    result = _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Bad config section type",
            "--decisions",
            "should fail",
            "--next-step",
            "fix config",
            "--risks",
            "none",
            "--command",
            "echo noop",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{result.stdout}\n{result.stderr}"
    assert "Config section review_heuristics must be a table." in output
    assert "Traceback" not in output


def test_negative_threshold_config_is_actionable(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Negative heuristic thresholds should fail with actionable guidance."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)
    dock_home.mkdir(parents=True, exist_ok=True)
    (dock_home / "config.toml").write_text(
        "\n".join(
            [
                "[review_heuristics]",
                "churn_threshold = -5",
            ]
        ),
        encoding="utf-8",
    )

    result = _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Negative threshold config",
            "--decisions",
            "should fail before save",
            "--next-step",
            "fix config",
            "--risks",
            "none",
            "--command",
            "echo noop",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{result.stdout}\n{result.stderr}"
    assert "Config field review_heuristics.churn_threshold must be >= 0." in output
    assert "Traceback" not in output


@pytest.mark.parametrize("command_name", ["s", "dock"])
@pytest.mark.parametrize(
    ("config_text", "expected_fragment"),
    [
        ("[review_heuristics\nfiles_changed_threshold = 4", "Invalid config TOML"),
        ('review_heuristics = "bad-type"\n', "Config section review_heuristics must be a table."),
        ('[review_heuristics]\nrisky_path_patterns = ["(^|/)[bad"]\n', "Invalid regex"),
        ("[review_heuristics]\nchurn_threshold = -1\n", "Config field review_heuristics.churn_threshold must be >= 0."),
    ],
)
def test_save_alias_invalid_config_is_actionable(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
    config_text: str,
    expected_fragment: str,
) -> None:
    """Save aliases should surface actionable config validation errors."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)
    dock_home.mkdir(parents=True, exist_ok=True)
    (dock_home / "config.toml").write_text(config_text, encoding="utf-8")

    result = _run_dock(
        [
            command_name,
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Alias invalid config case",
            "--decisions",
            "should fail before save",
            "--next-step",
            "fix config",
            "--risks",
            "none",
            "--command",
            "echo noop",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{result.stdout}\n{result.stderr}"
    assert expected_fragment in output
    assert "Traceback" not in output


def test_unknown_config_sections_do_not_block_save(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Unknown config sections should be ignored in save flow."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)
    dock_home.mkdir(parents=True, exist_ok=True)
    (dock_home / "config.toml").write_text(
        "\n".join(
            [
                "[other_section]",
                'foo = "bar"',
            ]
        ),
        encoding="utf-8",
    )

    result = _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Unknown section config",
            "--decisions",
            "save should succeed",
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
    assert "Saved checkpoint" in result.stdout


@pytest.mark.parametrize("command_name", ["s", "dock"])
def test_save_alias_unknown_config_sections_do_not_block_save(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Save aliases should ignore unknown config sections and succeed."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)
    dock_home.mkdir(parents=True, exist_ok=True)
    (dock_home / "config.toml").write_text(
        "\n".join(
            [
                "[other_section]",
                'foo = "bar"',
            ]
        ),
        encoding="utf-8",
    )

    result = _run_dock(
        [
            command_name,
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"{command_name} unknown section config",
            "--decisions",
            "save should succeed",
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
    assert "Saved checkpoint" in result.stdout


def test_empty_review_heuristics_section_uses_default_save_behavior(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Empty review_heuristics section should preserve default trigger behavior."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)
    dock_home.mkdir(parents=True, exist_ok=True)
    (dock_home / "config.toml").write_text("[review_heuristics]\n", encoding="utf-8")

    security_dir = git_repo / "security"
    security_dir.mkdir(exist_ok=True)
    (security_dir / "guard.py").write_text("print('guard')\n", encoding="utf-8")

    save_result = _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Empty review section defaults",
            "--decisions",
            "Default risky-path trigger should still apply",
            "--next-step",
            "Confirm auto review is still generated",
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
        ],
        cwd=git_repo,
        env=env,
    )
    assert "Created review item" in save_result.stdout
    assert "Review triggers:" in save_result.stdout
    assert "Traceback" not in f"{save_result.stdout}\n{save_result.stderr}"

    review_list = _run_dock(["review"], cwd=tmp_path, env=env).stdout
    assert "No review items." not in review_list


@pytest.mark.parametrize("command_name", ["s", "dock"])
def test_save_alias_empty_review_heuristics_section_uses_default_behavior(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Save aliases should preserve defaults with empty review_heuristics."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)
    dock_home.mkdir(parents=True, exist_ok=True)
    (dock_home / "config.toml").write_text("[review_heuristics]\n", encoding="utf-8")

    security_dir = git_repo / "security"
    security_dir.mkdir(exist_ok=True)
    (security_dir / "guard.py").write_text("print('guard')\n", encoding="utf-8")

    save_result = _run_dock(
        [
            command_name,
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"{command_name} empty review section defaults",
            "--decisions",
            "Default risky-path trigger should still apply",
            "--next-step",
            "Confirm auto review is still generated",
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
        ],
        cwd=git_repo,
        env=env,
    )
    assert "Created review item" in save_result.stdout
    assert "Review triggers:" in save_result.stdout
    assert "Traceback" not in f"{save_result.stdout}\n{save_result.stderr}"

    review_list = _run_dock(["review"], cwd=tmp_path, env=env).stdout
    assert "No review items." not in review_list


def test_missing_template_path_produces_actionable_error(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Missing save template path should fail with actionable error."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    missing_path = tmp_path / "not-there.json"
    result = _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--template",
            str(missing_path),
            "--no-prompt",
            "--objective",
            "Missing template",
            "--decisions",
            "should not save",
            "--next-step",
            "fix path",
            "--risks",
            "none",
            "--command",
            "echo noop",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{result.stdout}\n{result.stderr}"
    assert "Template not found" in output
    assert "Traceback" not in output


def test_invalid_template_content_produces_actionable_error(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Malformed template should fail cleanly with parse error message."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    bad_template = tmp_path / "bad_template.toml"
    bad_template.write_text("[broken\nvalue = 1", encoding="utf-8")
    result = _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--template",
            str(bad_template),
            "--no-prompt",
            "--objective",
            "Invalid template",
            "--decisions",
            "should not save",
            "--next-step",
            "fix template",
            "--risks",
            "none",
            "--command",
            "echo noop",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{result.stdout}\n{result.stderr}"
    assert "Failed to parse template" in output
    assert "Traceback" not in output


def test_unsupported_template_extension_produces_actionable_error(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Unsupported template extension should fail with clear guidance."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    bad_template = tmp_path / "template.yaml"
    bad_template.write_text("objective: bad extension\n", encoding="utf-8")
    result = _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--template",
            str(bad_template),
            "--no-prompt",
            "--objective",
            "Unsupported template extension",
            "--decisions",
            "should fail before save",
            "--next-step",
            "use json or toml",
            "--risks",
            "none",
            "--command",
            "echo noop",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{result.stdout}\n{result.stderr}"
    assert "Template must be .json or .toml" in output
    assert "Traceback" not in output


def test_template_tml_extension_is_rejected(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """`.tml` template extension should be rejected as unsupported."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    bad_template = tmp_path / "template.tml"
    bad_template.write_text('objective = "bad extension"\n', encoding="utf-8")
    result = _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--template",
            str(bad_template),
            "--no-prompt",
            "--objective",
            "Unsupported template extension",
            "--decisions",
            "should fail before save",
            "--next-step",
            "use json or toml",
            "--risks",
            "none",
            "--command",
            "echo noop",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{result.stdout}\n{result.stderr}"
    assert "Template must be .json or .toml" in output
    assert "Traceback" not in output


def test_template_type_validation_for_list_fields(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Template should reject invalid types for list-based fields."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    bad_template = tmp_path / "bad_types.json"
    bad_template.write_text(
        json.dumps(
            {
                "objective": "bad list shape",
                "decisions": "invalid next_steps type",
                "next_steps": "not-a-list",
            }
        ),
        encoding="utf-8",
    )
    result = _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--template",
            str(bad_template),
            "--no-prompt",
            "--objective",
            "override",
            "--decisions",
            "override",
            "--next-step",
            "override",
            "--risks",
            "none",
            "--command",
            "echo noop",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{result.stdout}\n{result.stderr}"
    assert "Template field 'next_steps' must be an array of strings" in output
    assert "Traceback" not in output


def test_template_must_be_object_or_table(git_repo: Path, tmp_path: Path) -> None:
    """Template payload must be an object/table and not other JSON types."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    bad_template = tmp_path / "list_template.json"
    bad_template.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
    result = _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--template",
            str(bad_template),
            "--no-prompt",
            "--objective",
            "override",
            "--decisions",
            "override",
            "--next-step",
            "override",
            "--risks",
            "none",
            "--command",
            "echo noop",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{result.stdout}\n{result.stderr}"
    assert "Template must contain an object/table" in output
    assert "Traceback" not in output


def test_template_type_validation_for_verification_fields(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Template should reject invalid types inside verification object."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    bad_template = tmp_path / "bad_verification.toml"
    bad_template.write_text(
        "\n".join(
            [
                'objective = "bad verification"',
                'decisions = "verification section malformed"',
                'next_steps = ["step"]',
                "",
                "[verification]",
                "tests_run = 123",
            ]
        ),
        encoding="utf-8",
    )
    result = _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--template",
            str(bad_template),
            "--no-prompt",
            "--objective",
            "override",
            "--decisions",
            "override",
            "--next-step",
            "override",
            "--risks",
            "none",
            "--command",
            "echo noop",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{result.stdout}\n{result.stderr}"
    assert "Template field 'tests_run' must be bool or bool-like string" in output
    assert "Traceback" not in output


def test_template_verification_section_must_be_object_or_table(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Template should reject non-object verification section payloads."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    bad_template = tmp_path / "bad_verification_shape.json"
    bad_template.write_text(
        json.dumps(
            {
                "objective": "bad verification shape",
                "decisions": "verification section is not object-like",
                "next_steps": ["step"],
                "verification": "not-a-table",
            }
        ),
        encoding="utf-8",
    )
    result = _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--template",
            str(bad_template),
            "--no-prompt",
            "--objective",
            "override",
            "--decisions",
            "override",
            "--next-step",
            "override",
            "--risks",
            "none",
            "--command",
            "echo noop",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{result.stdout}\n{result.stderr}"
    assert "Template field 'verification' must be a table/object" in output
    assert "Traceback" not in output


@pytest.mark.parametrize(
    ("template_payload", "expected_fragment"),
    [
        (
            {
                "objective": 123,
                "decisions": "invalid objective type",
                "next_steps": ["step"],
            },
            "Template field 'objective' must be a string",
        ),
        (
            {
                "objective": "invalid list item type",
                "decisions": "resume_commands contains non-string",
                "next_steps": ["step"],
                "resume_commands": ["echo good", 7],
            },
            "Template field 'resume_commands' must be an array of strings",
        ),
        (
            {
                "objective": "invalid verification command type",
                "decisions": "tests_command should be a string",
                "next_steps": ["step"],
                "verification": {"tests_command": 123},
            },
            "Template field 'tests_command' must be a string",
        ),
    ],
)
def test_template_type_validation_for_string_and_list_item_fields(
    git_repo: Path,
    tmp_path: Path,
    template_payload: dict[str, Any],
    expected_fragment: str,
) -> None:
    """Template should reject invalid string fields and list item types."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    bad_template = tmp_path / "bad_string_or_list_item_types.json"
    bad_template.write_text(json.dumps(template_payload), encoding="utf-8")

    result = _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--template",
            str(bad_template),
            "--no-prompt",
            "--objective",
            "override",
            "--decisions",
            "override",
            "--next-step",
            "override",
            "--risks",
            "none",
            "--command",
            "echo noop",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{result.stdout}\n{result.stderr}"
    assert expected_fragment in output
    assert "Traceback" not in output


@pytest.mark.parametrize(
    ("template_payload", "expected_fragment"),
    [
        (
            {
                "objective": "invalid risks type",
                "decisions": "risks_review should be a string",
                "next_steps": ["step"],
                "risks_review": 123,
            },
            "Template field 'risks_review' must be a string",
        ),
        (
            {
                "objective": "invalid tags list item type",
                "decisions": "tags should contain only strings",
                "next_steps": ["step"],
                "tags": ["alpha", 7],
            },
            "Template field 'tags' must be an array of strings",
        ),
        (
            {
                "objective": "invalid links list item type",
                "decisions": "links should contain only strings",
                "next_steps": ["step"],
                "links": ["https://example.invalid", 7],
            },
            "Template field 'links' must be an array of strings",
        ),
        (
            {
                "objective": "invalid build bool-like value",
                "decisions": "build_ok should be bool-like",
                "next_steps": ["step"],
                "verification": {"build_ok": "maybe"},
            },
            "Template field 'build_ok' must be bool or bool-like string",
        ),
        (
            {
                "objective": "invalid lint bool-like value",
                "decisions": "lint_ok should be bool-like",
                "next_steps": ["step"],
                "verification": {"lint_ok": "maybe"},
            },
            "Template field 'lint_ok' must be bool or bool-like string",
        ),
        (
            {
                "objective": "invalid smoke bool-like value",
                "decisions": "smoke_ok should be bool-like",
                "next_steps": ["step"],
                "verification": {"smoke_ok": "perhaps"},
            },
            "Template field 'smoke_ok' must be bool or bool-like string",
        ),
        (
            {
                "objective": "invalid build command type",
                "decisions": "build_command should be a string",
                "next_steps": ["step"],
                "verification": {"build_command": 123},
            },
            "Template field 'build_command' must be a string",
        ),
        (
            {
                "objective": "invalid lint command type",
                "decisions": "lint_command should be a string",
                "next_steps": ["step"],
                "verification": {"lint_command": 123},
            },
            "Template field 'lint_command' must be a string",
        ),
        (
            {
                "objective": "invalid smoke notes type",
                "decisions": "smoke_notes should be a string",
                "next_steps": ["step"],
                "verification": {"smoke_notes": 123},
            },
            "Template field 'smoke_notes' must be a string",
        ),
    ],
)
def test_template_type_validation_for_remaining_schema_fields(
    git_repo: Path,
    tmp_path: Path,
    template_payload: dict[str, Any],
    expected_fragment: str,
) -> None:
    """Template should reject invalid remaining schema field shapes/types."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    bad_template = tmp_path / "bad_remaining_schema_fields.json"
    bad_template.write_text(json.dumps(template_payload), encoding="utf-8")

    result = _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--template",
            str(bad_template),
            "--no-prompt",
            "--objective",
            "override",
            "--decisions",
            "override",
            "--next-step",
            "override",
            "--risks",
            "none",
            "--command",
            "echo noop",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{result.stdout}\n{result.stderr}"
    assert expected_fragment in output
    assert "Traceback" not in output


@pytest.mark.parametrize(
    ("template_payload", "expected_fragment"),
    [
        (
            {
                "objective": "invalid decisions type",
                "decisions": 123,
                "next_steps": ["step"],
            },
            "Template field 'decisions' must be a string",
        ),
        (
            {
                "objective": "invalid next steps list item type",
                "decisions": "next_steps should contain only strings",
                "next_steps": ["step", 7],
            },
            "Template field 'next_steps' must be an array of strings",
        ),
        (
            {
                "objective": "invalid resume_commands shape",
                "decisions": "resume_commands must be a list",
                "next_steps": ["step"],
                "resume_commands": "echo not-a-list",
            },
            "Template field 'resume_commands' must be an array of strings",
        ),
        (
            {
                "objective": "invalid tags shape",
                "decisions": "tags must be a list",
                "next_steps": ["step"],
                "tags": "alpha",
            },
            "Template field 'tags' must be an array of strings",
        ),
        (
            {
                "objective": "invalid links shape",
                "decisions": "links must be a list",
                "next_steps": ["step"],
                "links": "https://example.invalid",
            },
            "Template field 'links' must be an array of strings",
        ),
    ],
)
def test_template_type_validation_for_additional_top_level_fields(
    git_repo: Path,
    tmp_path: Path,
    template_payload: dict[str, Any],
    expected_fragment: str,
) -> None:
    """Template should reject invalid remaining top-level schema field shapes."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    bad_template = tmp_path / "bad_additional_top_level_fields.json"
    bad_template.write_text(json.dumps(template_payload), encoding="utf-8")

    result = _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--template",
            str(bad_template),
            "--no-prompt",
            "--objective",
            "override",
            "--decisions",
            "override",
            "--next-step",
            "override",
            "--risks",
            "none",
            "--command",
            "echo noop",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{result.stdout}\n{result.stderr}"
    assert expected_fragment in output
    assert "Traceback" not in output


def test_no_prompt_requires_risks_field(git_repo: Path, tmp_path: Path) -> None:
    """No-prompt save should require non-empty risks/review notes."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    result = _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Missing risks field",
            "--decisions",
            "Should fail without risks",
            "--next-step",
            "add risks",
            "--command",
            "echo noop",
        ],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{result.stdout}\n{result.stderr}"
    assert "Risks / Review Needed is required." in output
    assert "Traceback" not in output


def test_configured_heuristics_can_disable_default_review_trigger(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Configured heuristics should influence auto-review creation behavior."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)
    dock_home.mkdir(parents=True, exist_ok=True)
    (dock_home / "config.toml").write_text(
        "\n".join(
            [
                "[review_heuristics]",
                # Exclude default `security/` trigger; only `critical/` now.
                'risky_path_patterns = ["(^|/)critical/"]',
                # Keep other triggers intentionally high to avoid accidental matches.
                "files_changed_threshold = 999",
                "churn_threshold = 9999",
                "non_trivial_files_threshold = 999",
                "non_trivial_churn_threshold = 9999",
                'branch_prefixes = ["urgent/"]',
            ]
        ),
        encoding="utf-8",
    )

    security_dir = git_repo / "security"
    security_dir.mkdir(exist_ok=True)
    (security_dir / "guard.py").write_text("print('guard')\n", encoding="utf-8")

    save_result = _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Configurable review trigger behavior",
            "--decisions",
            "Custom heuristic should skip default security trigger",
            "--next-step",
            "Confirm no auto review generated",
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
        ],
        cwd=git_repo,
        env=env,
    )
    assert "Created review item" not in save_result.stdout
    assert "Review triggers:" not in save_result.stdout

    review_list = _run_dock(["review"], cwd=tmp_path, env=env)
    assert "No review items." in review_list.stdout


def test_configured_heuristics_can_force_review_trigger(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Configured thresholds should be able to force review creation."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)
    dock_home.mkdir(parents=True, exist_ok=True)
    (dock_home / "config.toml").write_text(
        "\n".join(
            [
                "[review_heuristics]",
                # Force trigger even on clean snapshots.
                "files_changed_threshold = 0",
                # Keep other trigger paths effectively disabled for clarity.
                "churn_threshold = 9999",
                "non_trivial_files_threshold = 999",
                "non_trivial_churn_threshold = 9999",
                'risky_path_patterns = ["(^|/)never-match/"]',
                'branch_prefixes = ["never/"]',
            ]
        ),
        encoding="utf-8",
    )

    save_result = _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Configurable force review trigger behavior",
            "--decisions",
            "Threshold override should force review creation",
            "--next-step",
            "Confirm auto review generated",
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
        ],
        cwd=git_repo,
        env=env,
    )
    output = f"{save_result.stdout}\n{save_result.stderr}"
    assert "Created review item" in output
    assert "Review triggers:" in output
    assert "many_files_changed" in output
    assert "Traceback" not in output

    review_list = _run_dock(["review"], cwd=tmp_path, env=env).stdout
    assert "No review items." not in review_list


def test_cli_ls_and_search_filters(git_repo: Path, tmp_path: Path) -> None:
    """CLI filters for harbor and search should narrow results correctly."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Filter target objective main",
            "--decisions",
            "main branch checkpoint",
            "--next-step",
            "run filters",
            "--risks",
            "none",
            "--command",
            "echo main",
            "--tag",
            "alpha",
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

    subprocess.run(
        ["git", "checkout", "-b", "feature/filters"],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Filter target objective feature",
            "--decisions",
            "feature branch checkpoint",
            "--next-step",
            "run feature filters",
            "--risks",
            "none",
            "--command",
            "echo feature",
            "--tag",
            "beta",
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

    tagged_alpha = json.loads(_run_dock(["ls", "--tag", "alpha", "--json"], cwd=tmp_path, env=env).stdout)
    assert len(tagged_alpha) == 1
    assert tagged_alpha[0]["branch"] in {"main", "master"}

    tagged_beta = json.loads(_run_dock(["ls", "--tag", "beta", "--json"], cwd=tmp_path, env=env).stdout)
    assert len(tagged_beta) == 1
    assert tagged_beta[0]["branch"] == "feature/filters"

    db_path = dock_home / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE slips SET updated_at = ? WHERE branch = ?",
        ("2000-01-01T00:00:00+00:00", "feature/filters"),
    )
    conn.commit()
    conn.close()

    stale_rows = json.loads(_run_dock(["ls", "--stale", "1", "--json"], cwd=tmp_path, env=env).stdout)
    assert len(stale_rows) == 1
    assert stale_rows[0]["branch"] == "feature/filters"

    search_branch = _run_dock(
        ["search", "Filter target objective", "--branch", "feature/filters"],
        cwd=tmp_path,
        env=env,
    )
    assert "feature/filters" in search_branch.stdout

    search_repo_name = _run_dock(
        ["search", "Filter target objective", "--repo", git_repo.name],
        cwd=tmp_path,
        env=env,
    )
    assert "feature/filters" in search_repo_name.stdout
    search_repo_json = json.loads(
        _run_dock(
            ["search", "Filter target objective", "--repo", git_repo.name, "--json"],
            cwd=tmp_path,
            env=env,
        ).stdout
    )
    assert len(search_repo_json) >= 1
    assert {row["berth_name"] for row in search_repo_json} == {git_repo.name}
    assert "berth_name" in search_repo_json[0]
    assert {"id", "repo_id", "berth_name", "branch", "created_at", "snippet", "objective"} <= set(
        search_repo_json[0].keys()
    )
    assert search_repo_json[0]["snippet"]
    assert json.loads(
        _run_dock(
            ["search", "no-such-query", "--repo", git_repo.name, "--json"],
            cwd=tmp_path,
            env=env,
        ).stdout
    ) == []

    tag_filtered = _run_dock(
        ["search", "Filter target objective", "--tag", "beta", "--branch", "feature/filters"],
        cwd=tmp_path,
        env=env,
    )
    assert "feature/filters" in tag_filtered.stdout
    tag_filtered_json = json.loads(
        _run_dock(
            [
                "search",
                "Filter target objective",
                "--tag",
                "beta",
                "--branch",
                "feature/filters",
                "--json",
            ],
            cwd=tmp_path,
            env=env,
        ).stdout
    )
    assert len(tag_filtered_json) == 1
    assert tag_filtered_json[0]["branch"] == "feature/filters"
    tag_repo_branch_table = _run_dock(
        [
            "search",
            "Filter target objective",
            "--tag",
            "beta",
            "--repo",
            git_repo.name,
            "--branch",
            "feature/filters",
        ],
        cwd=tmp_path,
        env=env,
    ).stdout
    assert "feature/filters" in tag_repo_branch_table
    assert "No checkpoint matches found." not in tag_repo_branch_table
    assert "Traceback" not in tag_repo_branch_table
    tag_repo_branch_json = json.loads(
        _run_dock(
            [
                "search",
                "Filter target objective",
                "--tag",
                "beta",
                "--repo",
                git_repo.name,
                "--branch",
                "feature/filters",
                "--json",
            ],
            cwd=tmp_path,
            env=env,
        ).stdout
    )
    assert len(tag_repo_branch_json) == 1
    assert tag_repo_branch_json[0]["branch"] == "feature/filters"


def test_ls_json_ordering_prioritizes_open_review_count(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Harbor ordering should place slips with more open reviews first."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    base_branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Main ordering baseline",
            "--decisions",
            "main branch context",
            "--next-step",
            "add review debt",
            "--risks",
            "none",
            "--command",
            "echo main",
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
    _run_dock(
        ["review", "add", "--reason", "ordering_high", "--severity", "high"],
        cwd=git_repo,
        env=env,
    )

    subprocess.run(
        ["git", "checkout", "-b", "feature/no-review"],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Feature ordering baseline",
            "--decisions",
            "feature branch context",
            "--next-step",
            "no review debt",
            "--risks",
            "none",
            "--command",
            "echo feature",
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
    subprocess.run(
        ["git", "checkout", base_branch],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )

    rows = json.loads(_run_dock(["ls", "--json"], cwd=tmp_path, env=env).stdout)
    assert len(rows) >= 2
    assert rows[0]["open_review_count"] >= rows[1]["open_review_count"]
    assert rows[0]["branch"] == base_branch


def test_ls_json_ordering_uses_status_then_staleness_on_review_ties(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Harbor ordering should use status then staleness when reviews tie."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)
    base_branch = _git_current_branch(git_repo)

    def _save_branch_checkpoint(objective: str) -> None:
        _run_dock(
            [
                "save",
                "--root",
                str(git_repo),
                "--no-prompt",
                "--objective",
                objective,
                "--decisions",
                "ordering context",
                "--next-step",
                "inspect ordering",
                "--risks",
                "none",
                "--command",
                "echo ordering",
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

    branch_names = [
        "feature/order-red-old",
        "feature/order-red-new",
        "feature/order-yellow",
        "feature/order-green",
    ]
    for branch in branch_names:
        subprocess.run(
            ["git", "checkout", "-b", branch],
            cwd=str(git_repo),
            check=True,
            capture_output=True,
        )
        _save_branch_checkpoint(f"Ordering checkpoint for {branch}")
        subprocess.run(
            ["git", "checkout", base_branch],
            cwd=str(git_repo),
            check=True,
            capture_output=True,
        )

    db_path = dock_home / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE slips SET status = ?, updated_at = ? WHERE branch = ?",
        ("red", "2000-01-01T00:00:00+00:00", "feature/order-red-old"),
    )
    conn.execute(
        "UPDATE slips SET status = ?, updated_at = ? WHERE branch = ?",
        ("red", "2005-01-01T00:00:00+00:00", "feature/order-red-new"),
    )
    conn.execute(
        "UPDATE slips SET status = ?, updated_at = ? WHERE branch = ?",
        ("yellow", "1990-01-01T00:00:00+00:00", "feature/order-yellow"),
    )
    conn.execute(
        "UPDATE slips SET status = ?, updated_at = ? WHERE branch = ?",
        ("green", "1980-01-01T00:00:00+00:00", "feature/order-green"),
    )
    conn.commit()
    conn.close()

    ordered_rows = json.loads(_run_dock(["ls", "--json"], cwd=tmp_path, env=env).stdout)
    ordered_branches = [row["branch"] for row in ordered_rows]
    assert ordered_branches[:4] == [
        "feature/order-red-old",
        "feature/order-red-new",
        "feature/order-yellow",
        "feature/order-green",
    ]


def test_ls_limit_flag_restricts_result_count(git_repo: Path, tmp_path: Path) -> None:
    """CLI `ls --limit` should cap number of returned rows."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    base_branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Limit baseline one",
            "--decisions",
            "main branch checkpoint",
            "--next-step",
            "create second branch checkpoint",
            "--risks",
            "none",
            "--command",
            "echo one",
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

    subprocess.run(
        ["git", "checkout", "-b", "feature/limit-check"],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Limit baseline two",
            "--decisions",
            "feature branch checkpoint",
            "--next-step",
            "run ls limit",
            "--risks",
            "none",
            "--command",
            "echo two",
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
    subprocess.run(
        ["git", "checkout", base_branch],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )

    rows = json.loads(_run_dock(["ls", "--limit", "1", "--json"], cwd=tmp_path, env=env).stdout)
    assert len(rows) == 1


def test_ls_and_search_validate_limit_arguments(tmp_path: Path) -> None:
    """Limit/stale flags should reject invalid values with actionable errors."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    ls_bad = _run_dock(["ls", "--limit", "0"], cwd=tmp_path, env=env, expect_code=2)
    ls_output = f"{ls_bad.stdout}\n{ls_bad.stderr}"
    assert "--limit must be >= 1." in ls_output
    assert "Traceback" not in ls_output

    stale_bad = _run_dock(["ls", "--stale", "-1"], cwd=tmp_path, env=env, expect_code=2)
    stale_output = f"{stale_bad.stdout}\n{stale_bad.stderr}"
    assert "--stale must be >= 0." in stale_output
    assert "Traceback" not in stale_output

    search_bad = _run_dock(
        ["search", "anything", "--limit", "0"],
        cwd=tmp_path,
        env=env,
        expect_code=2,
    )
    search_output = f"{search_bad.stdout}\n{search_bad.stderr}"
    assert "--limit must be >= 1." in search_output
    assert "Traceback" not in search_output


def test_ls_rejects_blank_tag_filter(tmp_path: Path) -> None:
    """LS should reject blank tag filter values when provided."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    failed = _run_dock(["ls", "--tag", "   "], cwd=tmp_path, env=env, expect_code=2)
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "--tag must be a non-empty string." in output
    assert "Traceback" not in output


def test_search_rejects_blank_tag_filter(tmp_path: Path) -> None:
    """Search should reject blank tag filter values when provided."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    failed = _run_dock(["search", "query", "--tag", "   "], cwd=tmp_path, env=env, expect_code=2)
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "--tag must be a non-empty string." in output
    assert "Traceback" not in output


def test_ls_tag_filter_accepts_trimmed_value(git_repo: Path, tmp_path: Path) -> None:
    """LS should resolve tag filters after whitespace trimming."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Trimmed ls tag objective",
            "--decisions",
            "Verify ls tag filter trimming",
            "--next-step",
            "run ls tag filter",
            "--risks",
            "none",
            "--command",
            "echo noop",
            "--tag",
            "alpha",
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

    rows = json.loads(_run_dock(["ls", "--tag", "  alpha  ", "--json"], cwd=tmp_path, env=env).stdout)
    assert len(rows) >= 1


def test_search_tag_filter_accepts_trimmed_value(git_repo: Path, tmp_path: Path) -> None:
    """Search should resolve tag filters after whitespace trimming."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Trimmed search tag objective",
            "--decisions",
            "Verify search tag filter trimming",
            "--next-step",
            "run search tag filter",
            "--risks",
            "none",
            "--command",
            "echo noop",
            "--tag",
            "alpha",
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

    rows = json.loads(
        _run_dock(
            ["search", "Trimmed search tag objective", "--tag", "  alpha  ", "--json"],
            cwd=tmp_path,
            env=env,
        ).stdout
    )
    assert len(rows) >= 1
    assert rows[0]["objective"] == "Trimmed search tag objective"


def test_search_rejects_blank_branch_filter(git_repo: Path, tmp_path: Path) -> None:
    """Search should reject blank branch filter values when provided."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Blank branch filter objective",
            "--decisions",
            "Need search context",
            "--next-step",
            "run invalid branch search",
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

    failed = _run_dock(
        ["search", "Blank branch filter objective", "--branch", "   "],
        cwd=tmp_path,
        env=env,
        expect_code=2,
    )
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "--branch must be a non-empty string." in output
    assert "Traceback" not in output


def test_search_branch_filter_accepts_trimmed_value(git_repo: Path, tmp_path: Path) -> None:
    """Search should resolve branch filters after whitespace trimming."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Trimmed branch filter objective",
            "--decisions",
            "Search should match trimmed branch filters",
            "--next-step",
            "run branch search",
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

    rows = json.loads(
        _run_dock(
            ["search", "Trimmed branch filter objective", "--branch", f"  {branch}  ", "--json"],
            cwd=tmp_path,
            env=env,
        ).stdout
    )
    assert len(rows) >= 1
    assert {row["branch"] for row in rows} == {branch}


def test_search_repo_and_branch_filters_accept_trimmed_values(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Search should resolve trimmed repo+branch filters together."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Trimmed repo branch search objective",
            "--decisions",
            "Search should trim both repo and branch filters",
            "--next-step",
            "run combined search",
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

    rows = json.loads(
        _run_dock(
            [
                "search",
                "Trimmed repo branch search objective",
                "--repo",
                f"  {git_repo.name}  ",
                "--branch",
                f"  {branch}  ",
                "--json",
            ],
            cwd=tmp_path,
            env=env,
        ).stdout
    )
    assert len(rows) >= 1
    assert {row["berth_name"] for row in rows} == {git_repo.name}
    assert {row["branch"] for row in rows} == {branch}


def test_search_repo_branch_filter_semantics_non_json(git_repo: Path, tmp_path: Path) -> None:
    """Search should honor combined repo+branch filters in table mode."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    default_branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "prb-default",
            "--decisions",
            "default branch checkpoint for primary repo+branch filtering",
            "--next-step",
            "run primary repo+branch filter",
            "--risks",
            "none",
            "--command",
            "echo default",
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
    subprocess.run(
        ["git", "checkout", "-b", "feature/primary-repo-branch-filter"],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "prb-feature",
            "--decisions",
            "feature branch checkpoint for primary repo+branch filtering",
            "--next-step",
            "run primary repo+branch filter",
            "--risks",
            "none",
            "--command",
            "echo feature",
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
    subprocess.run(
        ["git", "checkout", default_branch],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )

    filtered = _run_dock(
        [
            "search",
            "prb",
            "--repo",
            git_repo.name,
            "--branch",
            "feature/primary-repo-branch-filter",
        ],
        cwd=tmp_path,
        env=env,
    ).stdout
    assert "prb-feature" in filtered
    assert "prb-default" not in filtered
    assert "Traceback" not in filtered


def test_search_alias_validates_limit_argument(tmp_path: Path) -> None:
    """Search alias should enforce the same limit validation as search."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    failed = _run_dock(["f", "query", "--limit", "0"], cwd=tmp_path, env=env, expect_code=2)
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "--limit must be >= 1." in output
    assert "Traceback" not in output


def test_search_alias_rejects_blank_query(tmp_path: Path) -> None:
    """Search alias should reject whitespace-only queries."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    failed = _run_dock(["f", "   "], cwd=tmp_path, env=env, expect_code=2)
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "Query must be a non-empty string." in output
    assert "Traceback" not in output


def test_search_alias_rejects_blank_tag_filter(tmp_path: Path) -> None:
    """Search alias should reject blank tag filter values."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    failed = _run_dock(["f", "query", "--tag", "   "], cwd=tmp_path, env=env, expect_code=2)
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "--tag must be a non-empty string." in output
    assert "Traceback" not in output


def test_search_alias_rejects_blank_repo_filter(tmp_path: Path) -> None:
    """Search alias should reject blank repo filter values."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    failed = _run_dock(["f", "query", "--repo", "   "], cwd=tmp_path, env=env, expect_code=2)
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "--repo must be a non-empty string." in output
    assert "Traceback" not in output


def test_search_alias_rejects_blank_branch_filter(tmp_path: Path) -> None:
    """Search alias should reject blank branch filter values."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    failed = _run_dock(["f", "query", "--branch", "   "], cwd=tmp_path, env=env, expect_code=2)
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "--branch must be a non-empty string." in output
    assert "Traceback" not in output


def test_search_alias_repo_filter_accepts_trimmed_berth_name(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Search alias repo filter should accept trimmed berth name values."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Alias trimmed repo objective",
            "--decisions",
            "Alias repo filter should trim berth names",
            "--next-step",
            "run alias repo search",
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

    rows = json.loads(
        _run_dock(
            ["f", "Alias trimmed repo objective", "--repo", f"  {git_repo.name}  ", "--json"],
            cwd=tmp_path,
            env=env,
        ).stdout
    )
    assert len(rows) >= 1
    assert {row["berth_name"] for row in rows} == {git_repo.name}


def test_search_alias_tag_filter_accepts_trimmed_value(git_repo: Path, tmp_path: Path) -> None:
    """Search alias should resolve tag filters after whitespace trimming."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Alias trimmed tag objective",
            "--decisions",
            "Alias tag filter should trim values",
            "--next-step",
            "run alias search",
            "--risks",
            "none",
            "--command",
            "echo noop",
            "--tag",
            "alpha",
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

    rows = json.loads(_run_dock(["f", "Alias trimmed tag objective", "--tag", "  alpha  ", "--json"], cwd=tmp_path, env=env).stdout)
    assert len(rows) >= 1


def test_search_alias_branch_filter_accepts_trimmed_value(git_repo: Path, tmp_path: Path) -> None:
    """Search alias should resolve branch filters after whitespace trimming."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Alias trimmed branch objective",
            "--decisions",
            "Alias branch filter should trim values",
            "--next-step",
            "run alias branch search",
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

    rows = json.loads(
        _run_dock(
            ["f", "Alias trimmed branch objective", "--branch", f"  {branch}  ", "--json"],
            cwd=tmp_path,
            env=env,
        ).stdout
    )
    assert len(rows) >= 1
    assert {row["branch"] for row in rows} == {branch}


def test_search_alias_repo_and_branch_filters_accept_trimmed_values(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Search alias should resolve trimmed repo+branch filters together."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Alias trimmed repo branch objective",
            "--decisions",
            "Alias filters should trim repo and branch together",
            "--next-step",
            "run alias repo branch search",
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

    rows = json.loads(
        _run_dock(
            [
                "f",
                "Alias trimmed repo branch objective",
                "--repo",
                f"  {git_repo.name}  ",
                "--branch",
                f"  {branch}  ",
                "--json",
            ],
            cwd=tmp_path,
            env=env,
        ).stdout
    )
    assert len(rows) >= 1
    assert {row["berth_name"] for row in rows} == {git_repo.name}
    assert {row["branch"] for row in rows} == {branch}


def test_search_alias_json_respects_limit(git_repo: Path, tmp_path: Path) -> None:
    """Search alias JSON mode should honor --limit."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    base_branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Alias limit objective one",
            "--decisions",
            "alias limit baseline one",
            "--next-step",
            "record first",
            "--risks",
            "none",
            "--command",
            "echo one",
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
    subprocess.run(
        ["git", "checkout", "-b", "feature/alias-limit"],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Alias limit objective two",
            "--decisions",
            "alias limit baseline two",
            "--next-step",
            "record second",
            "--risks",
            "none",
            "--command",
            "echo two",
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
    subprocess.run(
        ["git", "checkout", base_branch],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )

    rows = json.loads(_run_dock(["f", "Alias limit objective", "--limit", "1", "--json"], cwd=tmp_path, env=env).stdout)
    assert len(rows) == 1


def test_search_alias_limit_applies_after_tag_filter(git_repo: Path, tmp_path: Path) -> None:
    """Search alias should apply --limit to tag-filtered result sets."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    base_branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Alias tag-limit objective one",
            "--decisions",
            "alias tag-limit checkpoint one",
            "--next-step",
            "record first",
            "--risks",
            "none",
            "--command",
            "echo one",
            "--tag",
            "alpha",
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
    subprocess.run(
        ["git", "checkout", "-b", "feature/alias-tag-limit"],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Alias tag-limit objective two",
            "--decisions",
            "alias tag-limit checkpoint two",
            "--next-step",
            "record second",
            "--risks",
            "none",
            "--command",
            "echo two",
            "--tag",
            "alpha",
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
    subprocess.run(
        ["git", "checkout", base_branch],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )

    rows = json.loads(
        _run_dock(
            ["f", "Alias tag-limit objective", "--tag", "alpha", "--limit", "1", "--json"],
            cwd=tmp_path,
            env=env,
        ).stdout
    )
    assert len(rows) == 1


@pytest.mark.parametrize("command_name", ["search", "f"])
def test_search_tag_filter_applies_before_limit_json(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Search JSON should apply tag filtering before truncating to --limit."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"tbf-tagged-{command_name}",
            "--decisions",
            "tagged baseline for filter-before-limit semantics",
            "--next-step",
            "run search tag+limit",
            "--risks",
            "none",
            "--command",
            "echo tagged",
            "--tag",
            "alpha",
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
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"tbf-untagged-{command_name}",
            "--decisions",
            "newer untagged record should be filtered before limit",
            "--next-step",
            "run search tag+limit",
            "--risks",
            "none",
            "--command",
            "echo untagged",
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

    rows = json.loads(
        _run_dock(
            [command_name, "tbf-", "--tag", "alpha", "--limit", "1", "--json"],
            cwd=tmp_path,
            env=env,
        ).stdout
    )
    assert len(rows) == 1
    assert rows[0]["objective"] == f"tbf-tagged-{command_name}"


@pytest.mark.parametrize("command_name", ["search", "f"])
def test_search_tag_filter_applies_before_limit_non_json(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Search table output should apply tag filters before --limit truncation."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"tbn-tagged-{command_name}",
            "--decisions",
            "tagged baseline for table filter-before-limit semantics",
            "--next-step",
            "run table search tag+limit",
            "--risks",
            "none",
            "--command",
            "echo tagged",
            "--tag",
            "alpha",
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
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"tbn-untagged-{command_name}",
            "--decisions",
            "newer untagged record should be filtered before limit in table mode",
            "--next-step",
            "run table search tag+limit",
            "--risks",
            "none",
            "--command",
            "echo untagged",
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

    output = _run_dock(
        [command_name, "tbn-", "--tag", "alpha", "--limit", "1"],
        cwd=tmp_path,
        env=env,
    ).stdout
    assert f"tbn-tagged-{command_name}" in output
    assert f"tbn-untagged-{command_name}" not in output
    assert "No checkpoint matches found." not in output
    assert "Traceback" not in output


def test_search_alias_limit_applies_after_tag_filter_non_json(git_repo: Path, tmp_path: Path) -> None:
    """Alias search table output should honor --tag + --limit together."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    base_branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Alias tag-limit table objective one",
            "--decisions",
            "alias tag-limit table checkpoint one",
            "--next-step",
            "record first",
            "--risks",
            "none",
            "--command",
            "echo one",
            "--tag",
            "alpha",
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
    subprocess.run(
        ["git", "checkout", "-b", "feature/alias-tag-limit-table"],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Alias tag-limit table objective two",
            "--decisions",
            "alias tag-limit table checkpoint two",
            "--next-step",
            "record second",
            "--risks",
            "none",
            "--command",
            "echo two",
            "--tag",
            "alpha",
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
    subprocess.run(
        ["git", "checkout", base_branch],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )

    output = _run_dock(
        ["f", "Alias tag-limit table objective", "--tag", "alpha", "--limit", "1"],
        cwd=tmp_path,
        env=env,
    ).stdout
    assert "Dockyard Search Results" in output
    assert "No checkpoint matches found." not in output
    assert "Traceback" not in output


def test_search_limit_applies_after_tag_filter_non_json(git_repo: Path, tmp_path: Path) -> None:
    """Primary search table output should honor --tag + --limit together."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    base_branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "ptl-one",
            "--decisions",
            "primary tag-limit checkpoint one",
            "--next-step",
            "record first",
            "--risks",
            "none",
            "--command",
            "echo one",
            "--tag",
            "alpha",
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
    subprocess.run(
        ["git", "checkout", "-b", "feature/primary-tag-limit-table"],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "ptl-two",
            "--decisions",
            "primary tag-limit checkpoint two",
            "--next-step",
            "record second",
            "--risks",
            "none",
            "--command",
            "echo two",
            "--tag",
            "alpha",
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
    subprocess.run(
        ["git", "checkout", base_branch],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )

    output = _run_dock(
        ["search", "ptl", "--tag", "alpha", "--limit", "1"],
        cwd=tmp_path,
        env=env,
    ).stdout
    shows_one = "ptl-one" in output
    shows_two = "ptl-two" in output
    assert shows_one ^ shows_two
    assert "Traceback" not in output


@pytest.mark.parametrize("command_name", ["search", "f"])
def test_search_table_long_snippet_render_is_truncated(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Search table output should truncate long snippet text for readability."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    long_risk = "long-snippet-token " + ("x" * 220)
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"long-snippet-{command_name}",
            "--decisions",
            "long snippet table rendering baseline",
            "--next-step",
            "run search table",
            "--risks",
            long_risk,
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

    output = _run_dock([command_name, "long-snippet-token"], cwd=tmp_path, env=env).stdout
    assert "Dockyard Search Results" in output
    assert "long-snippet-token" in output
    assert long_risk not in output
    assert "x" * 140 not in output
    assert "Traceback" not in output


def test_harbor_alias_validates_limit_argument(tmp_path: Path) -> None:
    """Harbor alias should enforce the same limit validation as ls."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    failed = _run_dock(["harbor", "--limit", "0"], cwd=tmp_path, env=env, expect_code=2)
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "--limit must be >= 1." in output
    assert "Traceback" not in output


def test_harbor_alias_validates_stale_argument(tmp_path: Path) -> None:
    """Harbor alias should enforce stale lower bound."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    failed = _run_dock(["harbor", "--stale", "-1"], cwd=tmp_path, env=env, expect_code=2)
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "--stale must be >= 0." in output
    assert "Traceback" not in output


def test_harbor_alias_rejects_blank_tag_filter(tmp_path: Path) -> None:
    """Harbor alias should reject blank tag filter values."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    failed = _run_dock(["harbor", "--tag", "   "], cwd=tmp_path, env=env, expect_code=2)
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "--tag must be a non-empty string." in output
    assert "Traceback" not in output


def test_harbor_alias_tag_filter_accepts_trimmed_value(git_repo: Path, tmp_path: Path) -> None:
    """Harbor alias should resolve tag filters after whitespace trimming."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Harbor trimmed tag objective",
            "--decisions",
            "Harbor tag filter should trim values",
            "--next-step",
            "run harbor filter",
            "--risks",
            "none",
            "--command",
            "echo noop",
            "--tag",
            "alpha",
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

    rows = json.loads(_run_dock(["harbor", "--tag", "  alpha  ", "--json"], cwd=tmp_path, env=env).stdout)
    assert len(rows) >= 1


def test_harbor_alias_renders_unknown_status_text(git_repo: Path, tmp_path: Path) -> None:
    """Harbor alias should render unknown slip statuses as raw text."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)
    branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Unknown status harbor baseline",
            "--decisions",
            "Render non-standard status token",
            "--next-step",
            "run harbor",
            "--risks",
            "none",
            "--command",
            "echo harbor",
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

    db_path = dock_home / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE slips SET status = ? WHERE branch = ?",
        ("paused", branch),
    )
    conn.commit()
    conn.close()

    output = _run_dock(["harbor"], cwd=tmp_path, env=env).stdout
    assert "paused" in output
    json_rows = json.loads(_run_dock(["harbor", "--json"], cwd=tmp_path, env=env).stdout)
    assert len(json_rows) == 1
    assert json_rows[0]["status"] == "paused"


@pytest.mark.parametrize(
    ("command_prefix", "label"),
    [
        (["ls"], "ls"),
        (["harbor"], "harbor"),
        ([], "callback"),
    ],
)
def test_dashboard_paths_render_unknown_status_text(
    git_repo: Path,
    tmp_path: Path,
    command_prefix: list[str],
    label: str,
) -> None:
    """Dashboard command paths should preserve unknown status tokens."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)
    branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"Dashboard {label} unknown status baseline",
            "--decisions",
            "Render non-standard status token across dashboard paths",
            "--next-step",
            "run dashboard views",
            "--risks",
            "none",
            "--command",
            "echo dashboard",
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

    db_path = dock_home / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE slips SET status = ? WHERE branch = ?",
        ("paused", branch),
    )
    conn.commit()
    conn.close()

    table_output = _run_dock(command_prefix, cwd=tmp_path, env=env)
    assert "paused" in table_output.stdout
    assert "Traceback" not in f"{table_output.stdout}\n{table_output.stderr}"

    json_rows = json.loads(_run_dock([*command_prefix, "--json"], cwd=tmp_path, env=env).stdout)
    assert len(json_rows) == 1
    assert json_rows[0]["status"] == "paused"


def test_harbor_alias_maps_short_status_token(git_repo: Path, tmp_path: Path) -> None:
    """Harbor alias should map short status token values to known badges."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)
    branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Harbor short status token baseline",
            "--decisions",
            "Map short status tokens in harbor rendering",
            "--next-step",
            "run harbor",
            "--risks",
            "none",
            "--command",
            "echo harbor",
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

    db_path = dock_home / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE slips SET status = ? WHERE branch = ?",
        (" y ", branch),
    )
    conn.commit()
    conn.close()

    output = _run_dock(["harbor"], cwd=tmp_path, env=env).stdout
    assert " Y " in f" {output} "
    json_rows = json.loads(_run_dock(["harbor", "--json"], cwd=tmp_path, env=env).stdout)
    assert len(json_rows) == 1
    assert json_rows[0]["status"] == " y "


@pytest.mark.parametrize(
    ("command_prefix", "label"),
    [
        (["ls"], "ls"),
        (["harbor"], "harbor"),
        ([], "callback"),
    ],
)
def test_dashboard_paths_map_short_status_token(
    git_repo: Path,
    tmp_path: Path,
    command_prefix: list[str],
    label: str,
) -> None:
    """Dashboard command paths should map known short status tokens."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)
    branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"Dashboard {label} short status token baseline",
            "--decisions",
            "Map short status token across dashboard paths",
            "--next-step",
            "run dashboard paths",
            "--risks",
            "none",
            "--command",
            "echo dashboard",
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

    db_path = dock_home / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE slips SET status = ? WHERE branch = ?",
        (" y ", branch),
    )
    conn.commit()
    conn.close()

    output = _run_dock(command_prefix, cwd=tmp_path, env=env).stdout
    assert " Y " in f" {output} "
    json_rows = json.loads(_run_dock([*command_prefix, "--json"], cwd=tmp_path, env=env).stdout)
    assert len(json_rows) == 1
    assert json_rows[0]["status"] == " y "


@pytest.mark.parametrize(
    ("status_value", "expected_table_fragment"),
    [
        ("  paused  ", "paused"),
        ("paused\nreview", "paused review"),
    ],
    ids=["trimmed_unknown_status", "multiline_unknown_status"],
)
@pytest.mark.parametrize(
    ("command_prefix", "label"),
    [
        (["ls"], "ls"),
        (["harbor"], "harbor"),
        ([], "callback"),
    ],
)
def test_dashboard_paths_normalize_unknown_status_text(
    git_repo: Path,
    tmp_path: Path,
    status_value: str,
    expected_table_fragment: str,
    command_prefix: list[str],
    label: str,
) -> None:
    """Dashboard command paths should normalize unknown status text in tables."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)
    branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"Dashboard {label} normalized unknown status baseline",
            "--decisions",
            "Normalize unknown status text across dashboard paths",
            "--next-step",
            "run dashboard paths",
            "--risks",
            "none",
            "--command",
            "echo dashboard",
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

    db_path = dock_home / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE slips SET status = ? WHERE branch = ?",
        (status_value, branch),
    )
    conn.commit()
    conn.close()

    output = _run_dock(command_prefix, cwd=tmp_path, env=env).stdout
    assert expected_table_fragment in output
    assert "Traceback" not in output

    json_rows = json.loads(_run_dock([*command_prefix, "--json"], cwd=tmp_path, env=env).stdout)
    assert len(json_rows) == 1
    assert json_rows[0]["status"] == status_value


def test_harbor_alias_compacts_multiline_branch_text(git_repo: Path, tmp_path: Path) -> None:
    """Harbor alias should compact multiline branch values in table output."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)
    branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Harbor multiline branch baseline",
            "--decisions",
            "Normalize multiline branch text in harbor output",
            "--next-step",
            "run harbor",
            "--risks",
            "none",
            "--command",
            "echo harbor",
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

    db_path = dock_home / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE slips SET branch = ? WHERE branch = ?",
        ("feature/\nharbor", branch),
    )
    conn.commit()
    conn.close()

    output = _run_dock(["harbor"], cwd=tmp_path, env=env).stdout
    assert "feature/ harbor" in output


@pytest.mark.parametrize(
    ("command_prefix", "label"),
    [
        (["ls"], "ls"),
        (["harbor"], "harbor"),
        ([], "callback"),
    ],
)
def test_dashboard_paths_compact_multiline_branch_text(
    git_repo: Path,
    tmp_path: Path,
    command_prefix: list[str],
    label: str,
) -> None:
    """Dashboard command paths should compact multiline branch values in tables."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)
    branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"dmb-{label}",
            "--decisions",
            "Normalize multiline branch text across dashboard output paths",
            "--next-step",
            "run dashboard path",
            "--risks",
            "none",
            "--command",
            "echo dashboard",
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

    db_path = dock_home / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE slips SET branch = ? WHERE branch = ?",
        ("feature/\nharbor", branch),
    )
    conn.commit()
    conn.close()

    output = _run_dock(command_prefix, cwd=tmp_path, env=env).stdout
    assert "feature/ harbor" in output
    rows = json.loads(_run_dock([*command_prefix, "--json"], cwd=tmp_path, env=env).stdout)
    assert len(rows) == 1
    assert rows[0]["branch"] == "feature/\nharbor"


def test_harbor_alias_falls_back_for_blank_branch_text(git_repo: Path, tmp_path: Path) -> None:
    """Harbor alias should show unknown label when slip branch is blank."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)
    branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Harbor blank branch baseline",
            "--decisions",
            "Fallback branch rendering should remain explicit",
            "--next-step",
            "run harbor",
            "--risks",
            "none",
            "--command",
            "echo harbor",
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

    db_path = dock_home / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE slips SET branch = ? WHERE branch = ?",
        ("   ", branch),
    )
    conn.commit()
    conn.close()

    output = _run_dock(["harbor"], cwd=tmp_path, env=env).stdout
    assert "(unknown)" in output


def test_harbor_alias_falls_back_for_blank_timestamp(git_repo: Path, tmp_path: Path) -> None:
    """Harbor alias should show unknown age when slip timestamp is blank."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)
    branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Harbor blank timestamp baseline",
            "--decisions",
            "Fallback timestamp rendering should remain explicit",
            "--next-step",
            "run harbor",
            "--risks",
            "none",
            "--command",
            "echo harbor",
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

    db_path = dock_home / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE slips SET updated_at = ? WHERE branch = ?",
        ("   ", branch),
    )
    conn.commit()
    conn.close()

    output = _run_dock(["harbor"], cwd=tmp_path, env=env).stdout
    assert "unknown" in output


@pytest.mark.parametrize(
    ("command_prefix", "label"),
    [
        (["ls"], "ls"),
        (["harbor"], "harbor"),
        ([], "callback"),
    ],
)
def test_dashboard_paths_fallback_for_blank_branch_text(
    git_repo: Path,
    tmp_path: Path,
    command_prefix: list[str],
    label: str,
) -> None:
    """Dashboard command paths should show unknown label for blank branch text."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)
    branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"dbbb-{label}",
            "--decisions",
            "Fallback branch rendering should remain explicit across dashboard paths",
            "--next-step",
            "run dashboard path",
            "--risks",
            "none",
            "--command",
            "echo dashboard",
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

    db_path = dock_home / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE slips SET branch = ? WHERE branch = ?",
        ("   ", branch),
    )
    conn.commit()
    conn.close()

    output = _run_dock(command_prefix, cwd=tmp_path, env=env).stdout
    assert "(unknown)" in output
    assert "Traceback" not in output
    rows = json.loads(_run_dock([*command_prefix, "--json"], cwd=tmp_path, env=env).stdout)
    assert len(rows) == 1
    assert rows[0]["branch"].strip() == ""


@pytest.mark.parametrize(
    ("command_prefix", "label"),
    [
        (["ls"], "ls"),
        (["harbor"], "harbor"),
        ([], "callback"),
    ],
)
def test_dashboard_paths_fallback_for_blank_updated_timestamp(
    git_repo: Path,
    tmp_path: Path,
    command_prefix: list[str],
    label: str,
) -> None:
    """Dashboard command paths should show unknown age for blank timestamps."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)
    branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"dbbt-{label}",
            "--decisions",
            "Fallback timestamp rendering should remain explicit across dashboard paths",
            "--next-step",
            "run dashboard path",
            "--risks",
            "none",
            "--command",
            "echo dashboard",
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

    db_path = dock_home / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE slips SET updated_at = ? WHERE branch = ?",
        ("   ", branch),
    )
    conn.commit()
    conn.close()

    output = _run_dock(command_prefix, cwd=tmp_path, env=env).stdout
    assert "unknown" in output
    assert "Traceback" not in output
    rows = json.loads(_run_dock([*command_prefix, "--json"], cwd=tmp_path, env=env).stdout)
    assert len(rows) == 1
    assert rows[0]["updated_at"].strip() == ""


def test_ls_stale_zero_is_accepted(git_repo: Path, tmp_path: Path) -> None:
    """Stale threshold of zero days should be valid input."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Stale zero baseline",
            "--decisions",
            "Need one slip to query",
            "--next-step",
            "run ls stale 0",
            "--risks",
            "none",
            "--command",
            "echo stale",
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
    result = _run_dock(["ls", "--stale", "0", "--json"], cwd=tmp_path, env=env)
    rows = json.loads(result.stdout)
    assert len(rows) >= 1


def test_harbor_stale_zero_is_accepted(git_repo: Path, tmp_path: Path) -> None:
    """Harbor alias should accept stale threshold of zero days."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Harbor stale zero baseline",
            "--decisions",
            "Need one slip for harbor stale 0",
            "--next-step",
            "run harbor stale 0",
            "--risks",
            "none",
            "--command",
            "echo stale",
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

    rows = json.loads(_run_dock(["harbor", "--stale", "0", "--json"], cwd=tmp_path, env=env).stdout)
    assert len(rows) >= 1


def test_ls_stale_handles_naive_updated_timestamp(git_repo: Path, tmp_path: Path) -> None:
    """Stale filtering should handle naive updated timestamps without crashing."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)
    branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Naive stale timestamp baseline",
            "--decisions",
            "Ensure stale filter supports naive timestamps",
            "--next-step",
            "run ls stale 1",
            "--risks",
            "none",
            "--command",
            "echo stale",
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

    db_path = dock_home / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE slips SET updated_at = ? WHERE branch = ?",
        ("2000-01-01T00:00:00", branch),
    )
    conn.commit()
    conn.close()

    rows = json.loads(_run_dock(["ls", "--stale", "1", "--json"], cwd=tmp_path, env=env).stdout)
    assert len(rows) == 1
    assert rows[0]["branch"] == branch
    harbor_rows = json.loads(_run_dock(["harbor", "--stale", "1", "--json"], cwd=tmp_path, env=env).stdout)
    assert len(harbor_rows) == 1
    assert harbor_rows[0]["branch"] == branch
    callback_rows = json.loads(_run_dock(["--stale", "1", "--json"], cwd=tmp_path, env=env).stdout)
    assert len(callback_rows) == 1
    assert callback_rows[0]["branch"] == branch


def test_ls_stale_skips_invalid_updated_timestamp(git_repo: Path, tmp_path: Path) -> None:
    """Stale filtering should skip slips with invalid updated_at timestamps."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)
    branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Invalid stale timestamp baseline",
            "--decisions",
            "Ensure invalid stale timestamps are skipped",
            "--next-step",
            "run ls stale 1",
            "--risks",
            "none",
            "--command",
            "echo stale",
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

    db_path = dock_home / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE slips SET updated_at = ? WHERE branch = ?",
        ("not-a-timestamp", branch),
    )
    conn.commit()
    conn.close()

    ls_rows = json.loads(_run_dock(["ls", "--stale", "1", "--json"], cwd=tmp_path, env=env).stdout)
    assert ls_rows == []
    harbor_rows = json.loads(_run_dock(["harbor", "--stale", "1", "--json"], cwd=tmp_path, env=env).stdout)
    assert harbor_rows == []
    callback_rows = json.loads(_run_dock(["--stale", "1", "--json"], cwd=tmp_path, env=env).stdout)
    assert callback_rows == []


def test_ls_stale_skips_non_string_updated_timestamp(git_repo: Path, tmp_path: Path) -> None:
    """Stale filtering should skip slips with non-string updated_at values."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)
    branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Numeric stale timestamp baseline",
            "--decisions",
            "Ensure non-string stale timestamps are skipped",
            "--next-step",
            "run harbor stale 1",
            "--risks",
            "none",
            "--command",
            "echo stale",
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

    db_path = dock_home / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE slips SET updated_at = ? WHERE branch = ?",
        (0, branch),
    )
    conn.commit()
    conn.close()

    ls_rows = json.loads(_run_dock(["ls", "--stale", "1", "--json"], cwd=tmp_path, env=env).stdout)
    assert ls_rows == []
    harbor_rows = json.loads(_run_dock(["harbor", "--stale", "1", "--json"], cwd=tmp_path, env=env).stdout)
    assert harbor_rows == []
    callback_rows = json.loads(_run_dock(["--stale", "1", "--json"], cwd=tmp_path, env=env).stdout)
    assert callback_rows == []


def test_ls_json_limit_and_tag_combination(git_repo: Path, tmp_path: Path) -> None:
    """Combined ls filters should still obey limit and tag constraints."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    base_branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "ls-tag-limit-alpha-one",
            "--decisions",
            "alpha branch context",
            "--next-step",
            "seed alpha tag",
            "--risks",
            "none",
            "--command",
            "echo alpha",
            "--tag",
            "alpha",
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

    subprocess.run(
        ["git", "checkout", "-b", "feature/alpha-two"],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "ls-tag-limit-alpha-two",
            "--decisions",
            "alpha second branch context",
            "--next-step",
            "seed second alpha tag",
            "--risks",
            "none",
            "--command",
            "echo alpha-two",
            "--tag",
            "alpha",
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
    subprocess.run(
        ["git", "checkout", base_branch],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )

    rows = json.loads(
        _run_dock(["ls", "--tag", "alpha", "--limit", "1", "--json"], cwd=tmp_path, env=env).stdout
    )
    assert len(rows) == 1
    assert "alpha" in rows[0]["tags"]
    table_output = _run_dock(["ls", "--tag", "alpha", "--limit", "1"], cwd=tmp_path, env=env).stdout
    shows_base_branch = base_branch in table_output
    shows_feature_branch = "feature/alpha-two" in table_output
    assert shows_base_branch ^ shows_feature_branch
    assert "No checkpoints yet." not in table_output
    assert "Traceback" not in table_output


def test_search_rejects_blank_query(tmp_path: Path) -> None:
    """Search should reject whitespace-only query strings."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    failed = _run_dock(["search", "   "], cwd=tmp_path, env=env, expect_code=2)
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "Query must be a non-empty string." in output
    assert "Traceback" not in output


def test_search_no_matches_is_informative(tmp_path: Path) -> None:
    """Search should display explicit no-match message when empty."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    result = _run_dock(["search", "nothing-will-match"], cwd=tmp_path, env=env)
    assert "No checkpoint matches found." in result.stdout
    assert "Traceback" not in f"{result.stdout}\n{result.stderr}"


def test_search_filtered_no_matches_is_informative(git_repo: Path, tmp_path: Path) -> None:
    """Search should keep no-match guidance when filters eliminate results."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Filtered no-match objective",
            "--decisions",
            "Filtered no-match decisions",
            "--next-step",
            "run filtered search",
            "--risks",
            "none",
            "--command",
            "echo noop",
            "--tag",
            "present-tag",
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

    result = _run_dock(
        ["search", "Filtered no-match objective", "--tag", "missing-tag"],
        cwd=tmp_path,
        env=env,
    )
    assert "No checkpoint matches found." in result.stdout
    assert "Traceback" not in f"{result.stdout}\n{result.stderr}"


def test_search_output_falls_back_for_blank_timestamp(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Search output should show unknown timestamp when created_at is blank."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Search blank timestamp objective",
            "--decisions",
            "Verify fallback timestamp rendering for search",
            "--next-step",
            "run search",
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

    db_path = dock_home / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE checkpoints SET created_at = ?", ("   ",))
    conn.commit()
    conn.close()

    result = _run_dock(["search", "Search blank timestamp objective"], cwd=tmp_path, env=env)
    assert "(unknown)" in result.stdout


def test_search_output_falls_back_for_blank_branch(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Search output should show unknown branch when checkpoint branch is blank."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Search blank branch objective",
            "--decisions",
            "Verify fallback branch rendering for search",
            "--next-step",
            "run search",
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

    db_path = dock_home / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE checkpoints SET branch = ?", ("   ",))
    conn.commit()
    conn.close()

    result = _run_dock(["search", "Search blank branch objective"], cwd=tmp_path, env=env)
    assert "(unknown)" in result.stdout


def test_search_no_matches_json_returns_empty_array(tmp_path: Path) -> None:
    """JSON search output should remain machine-parseable when empty."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    result = _run_dock(["search", "nothing-will-match", "--json"], cwd=tmp_path, env=env)
    assert json.loads(result.stdout) == []
    assert "Traceback" not in f"{result.stdout}\n{result.stderr}"


def test_search_filtered_no_matches_json_returns_empty_array(git_repo: Path, tmp_path: Path) -> None:
    """Filtered JSON search output should remain [] when no rows survive."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Filtered no-match json objective",
            "--decisions",
            "Filtered no-match json decisions",
            "--next-step",
            "run filtered search json",
            "--risks",
            "none",
            "--command",
            "echo noop",
            "--tag",
            "present-tag",
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

    result = _run_dock(
        ["search", "Filtered no-match json objective", "--tag", "missing-tag", "--json"],
        cwd=tmp_path,
        env=env,
    )
    assert json.loads(result.stdout) == []
    assert "Traceback" not in f"{result.stdout}\n{result.stderr}"


def test_search_repo_filter_no_match_is_informative(git_repo: Path, tmp_path: Path) -> None:
    """Search should show no-match guidance when repo filter excludes results."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Repo filter no-match objective",
            "--decisions",
            "Repo filter no-match decisions",
            "--next-step",
            "run repo filtered search",
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

    result = _run_dock(
        ["search", "Repo filter no-match objective", "--repo", "missing-berth"],
        cwd=tmp_path,
        env=env,
    )
    assert "No checkpoint matches found." in result.stdout
    assert "Traceback" not in f"{result.stdout}\n{result.stderr}"


def test_search_repo_filter_no_match_json_returns_empty_array(git_repo: Path, tmp_path: Path) -> None:
    """Search JSON should return [] when repo filter excludes results."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Repo filter no-match json objective",
            "--decisions",
            "Repo filter no-match json decisions",
            "--next-step",
            "run repo filtered search json",
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

    result = _run_dock(
        ["search", "Repo filter no-match json objective", "--repo", "missing-berth", "--json"],
        cwd=tmp_path,
        env=env,
    )
    assert json.loads(result.stdout) == []
    assert "Traceback" not in f"{result.stdout}\n{result.stderr}"


def test_search_repo_branch_filter_no_match_json_returns_empty_array(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Search JSON should return [] for combined repo+branch filter misses."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Repo branch filter no-match objective",
            "--decisions",
            "Repo branch filter no-match decisions",
            "--next-step",
            "run repo branch filtered search",
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

    result = _run_dock(
        [
            "search",
            "Repo branch filter no-match objective",
            "--repo",
            "missing-berth",
            "--branch",
            "missing/branch",
            "--json",
        ],
        cwd=tmp_path,
        env=env,
    )
    assert json.loads(result.stdout) == []
    assert "Traceback" not in f"{result.stdout}\n{result.stderr}"


def test_search_repo_branch_filter_no_match_is_informative(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Search should show no-match guidance for combined repo+branch misses."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Repo branch filter message objective",
            "--decisions",
            "Repo branch filter message decisions",
            "--next-step",
            "run repo branch filtered search",
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

    result = _run_dock(
        [
            "search",
            "Repo branch filter message objective",
            "--repo",
            "missing-berth",
            "--branch",
            "missing/branch",
        ],
        cwd=tmp_path,
        env=env,
    )
    assert "No checkpoint matches found." in result.stdout
    assert "Traceback" not in f"{result.stdout}\n{result.stderr}"


def test_search_repo_filter_accepts_trimmed_berth_name(git_repo: Path, tmp_path: Path) -> None:
    """Search repo filter should accept berth names with surrounding spaces."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Trimmed repo filter objective",
            "--decisions",
            "Search should resolve trimmed berth-name filters",
            "--next-step",
            "run search repo filter",
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

    rows = json.loads(
        _run_dock(
            ["search", "Trimmed repo filter objective", "--repo", f"  {git_repo.name}  ", "--json"],
            cwd=tmp_path,
            env=env,
        ).stdout
    )
    assert len(rows) >= 1
    assert {row["berth_name"] for row in rows} == {git_repo.name}


def test_search_rejects_blank_repo_filter(git_repo: Path, tmp_path: Path) -> None:
    """Search should reject blank repo filter values when provided."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Blank repo filter validation objective",
            "--decisions",
            "Need context for search command",
            "--next-step",
            "run invalid search",
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

    failed = _run_dock(
        ["search", "Blank repo filter validation objective", "--repo", "   "],
        cwd=tmp_path,
        env=env,
        expect_code=2,
    )
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "--repo must be a non-empty string." in output
    assert "Traceback" not in output


def test_search_repo_filter_semantics_non_json_across_multiple_berths(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Search should keep repo-filtered table output scoped to one berth."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "psrf-target",
            "--decisions",
            "target berth checkpoint for repo filter semantics",
            "--next-step",
            "run primary repo filter",
            "--risks",
            "none",
            "--command",
            "echo target",
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

    other_repo = tmp_path / "other-repo"
    other_repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=str(other_repo), check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "dockyard@example.com"],
        cwd=str(other_repo),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Dockyard Test"],
        cwd=str(other_repo),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", "git@github.com:org/other.git"],
        cwd=str(other_repo),
        check=True,
        capture_output=True,
    )
    (other_repo / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=str(other_repo), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=str(other_repo), check=True, capture_output=True)

    _run_dock(
        [
            "save",
            "--root",
            str(other_repo),
            "--no-prompt",
            "--objective",
            "psrf-other",
            "--decisions",
            "other berth checkpoint for repo filter semantics",
            "--next-step",
            "run primary repo filter",
            "--risks",
            "none",
            "--command",
            "echo other",
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
        cwd=other_repo,
        env=env,
    )

    table_output = _run_dock(
        ["search", "psrf", "--repo", git_repo.name],
        cwd=tmp_path,
        env=env,
    ).stdout
    assert "psrf-target" in table_output
    assert "psrf-other" not in table_output
    assert "Traceback" not in table_output

    rows = json.loads(
        _run_dock(
            ["search", "psrf", "--repo", git_repo.name, "--json"],
            cwd=tmp_path,
            env=env,
        ).stdout
    )
    assert len(rows) == 1
    assert rows[0]["objective"] == "psrf-target"
    assert rows[0]["berth_name"] == git_repo.name

    db_path = tmp_path / ".dockyard_data" / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    target_repo_id = conn.execute(
        "SELECT repo_id FROM berths WHERE root_path = ?",
        (str(git_repo),),
    ).fetchone()[0]
    other_repo_id = conn.execute(
        "SELECT repo_id FROM berths WHERE root_path = ?",
        (str(other_repo),),
    ).fetchone()[0]
    conn.execute("UPDATE berths SET name = ? WHERE repo_id = ?", (target_repo_id, other_repo_id))
    conn.commit()
    conn.close()

    repo_id_rows = json.loads(
        _run_dock(
            ["search", "psrf", "--repo", target_repo_id, "--json"],
            cwd=tmp_path,
            env=env,
        ).stdout
    )
    assert len(repo_id_rows) == 1
    assert repo_id_rows[0]["repo_id"] == target_repo_id
    assert repo_id_rows[0]["objective"] == "psrf-target"


def test_search_alias_repo_filter_semantics_non_json_across_multiple_berths(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Alias search should keep repo-filtered output scoped to one berth."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "asrf-target",
            "--decisions",
            "target berth checkpoint for alias repo filter semantics",
            "--next-step",
            "run alias repo filter",
            "--risks",
            "none",
            "--command",
            "echo target",
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

    other_repo = tmp_path / "other-repo-alias"
    other_repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=str(other_repo), check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "dockyard@example.com"],
        cwd=str(other_repo),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Dockyard Test"],
        cwd=str(other_repo),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", "git@github.com:org/other-alias.git"],
        cwd=str(other_repo),
        check=True,
        capture_output=True,
    )
    (other_repo / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=str(other_repo), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=str(other_repo), check=True, capture_output=True)

    _run_dock(
        [
            "save",
            "--root",
            str(other_repo),
            "--no-prompt",
            "--objective",
            "asrf-other",
            "--decisions",
            "other berth checkpoint for alias repo filter semantics",
            "--next-step",
            "run alias repo filter",
            "--risks",
            "none",
            "--command",
            "echo other",
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
        cwd=other_repo,
        env=env,
    )

    table_output = _run_dock(
        ["f", "asrf", "--repo", git_repo.name],
        cwd=tmp_path,
        env=env,
    ).stdout
    assert "asrf-target" in table_output
    assert "asrf-other" not in table_output
    assert "Traceback" not in table_output

    rows = json.loads(
        _run_dock(
            ["f", "asrf", "--repo", git_repo.name, "--json"],
            cwd=tmp_path,
            env=env,
        ).stdout
    )
    assert len(rows) == 1
    assert rows[0]["objective"] == "asrf-target"
    assert rows[0]["berth_name"] == git_repo.name

    db_path = tmp_path / ".dockyard_data" / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    target_repo_id = conn.execute(
        "SELECT repo_id FROM berths WHERE root_path = ?",
        (str(git_repo),),
    ).fetchone()[0]
    other_repo_id = conn.execute(
        "SELECT repo_id FROM berths WHERE root_path = ?",
        (str(other_repo),),
    ).fetchone()[0]
    conn.execute("UPDATE berths SET name = ? WHERE repo_id = ?", (target_repo_id, other_repo_id))
    conn.commit()
    conn.close()

    repo_id_rows = json.loads(
        _run_dock(
            ["f", "asrf", "--repo", target_repo_id, "--json"],
            cwd=tmp_path,
            env=env,
        ).stdout
    )
    assert len(repo_id_rows) == 1
    assert repo_id_rows[0]["repo_id"] == target_repo_id
    assert repo_id_rows[0]["objective"] == "asrf-target"


@pytest.mark.parametrize("command_name", ["search", "f"])
def test_search_tag_repo_filter_semantics_across_multiple_berths(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Search tag+repo filters should stay scoped to the selected berth."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"mtr-target-{command_name}",
            "--decisions",
            "target berth checkpoint for multi-berth tag+repo semantics",
            "--next-step",
            "run tag+repo search",
            "--risks",
            "none",
            "--command",
            "echo target",
            "--tag",
            "alpha",
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

    other_repo = tmp_path / f"multi-tag-repo-{command_name}"
    other_repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=str(other_repo), check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "dockyard@example.com"],
        cwd=str(other_repo),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Dockyard Test"],
        cwd=str(other_repo),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", f"git@github.com:org/{command_name}-multi-tag.git"],
        cwd=str(other_repo),
        check=True,
        capture_output=True,
    )
    (other_repo / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=str(other_repo), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=str(other_repo), check=True, capture_output=True)

    _run_dock(
        [
            "save",
            "--root",
            str(other_repo),
            "--no-prompt",
            "--objective",
            f"mtr-other-{command_name}",
            "--decisions",
            "other berth checkpoint for multi-berth tag+repo semantics",
            "--next-step",
            "run tag+repo search",
            "--risks",
            "none",
            "--command",
            "echo other",
            "--tag",
            "alpha",
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
        cwd=other_repo,
        env=env,
    )

    rows = json.loads(
        _run_dock(
            [command_name, "mtr-", "--tag", "alpha", "--repo", git_repo.name, "--json"],
            cwd=tmp_path,
            env=env,
        ).stdout
    )
    assert len(rows) == 1
    assert rows[0]["objective"] == f"mtr-target-{command_name}"
    assert rows[0]["berth_name"] == git_repo.name

    table_output = _run_dock(
        [command_name, "mtr-", "--tag", "alpha", "--repo", git_repo.name],
        cwd=tmp_path,
        env=env,
    ).stdout
    assert f"mtr-target-{command_name}" in table_output
    assert f"mtr-other-{command_name}" not in table_output
    assert "Traceback" not in table_output


@pytest.mark.parametrize("command_name", ["search", "f"])
def test_search_tag_repo_branch_filter_semantics_across_multi_branch_matches(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Combined tag+repo+branch filters should isolate target-branch rows."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    base_branch = _git_current_branch(git_repo)
    target_branch = "feature/matrix-target"

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"mtrbtoken tm-{command_name}",
            "--decisions",
            "target main checkpoint for combined filter matrix",
            "--next-step",
            "run combined filter matrix",
            "--risks",
            "none",
            "--command",
            "echo target-main",
            "--tag",
            "alpha",
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
    subprocess.run(
        ["git", "checkout", "-b", target_branch],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"mtrbtoken tf-{command_name}",
            "--decisions",
            "target feature checkpoint for combined filter matrix",
            "--next-step",
            "run combined filter matrix",
            "--risks",
            "none",
            "--command",
            "echo target-feature",
            "--tag",
            "alpha",
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
    subprocess.run(
        ["git", "checkout", base_branch],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )

    other_repo = tmp_path / f"multi-tag-repo-branch-{command_name}"
    other_repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=str(other_repo), check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "dockyard@example.com"],
        cwd=str(other_repo),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Dockyard Test"],
        cwd=str(other_repo),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", f"git@github.com:org/{command_name}-multi-tag-branch.git"],
        cwd=str(other_repo),
        check=True,
        capture_output=True,
    )
    (other_repo / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=str(other_repo), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=str(other_repo), check=True, capture_output=True)
    subprocess.run(
        ["git", "checkout", "-b", target_branch],
        cwd=str(other_repo),
        check=True,
        capture_output=True,
    )
    _run_dock(
        [
            "save",
            "--root",
            str(other_repo),
            "--no-prompt",
            "--objective",
            f"mtrbtoken of-{command_name}",
            "--decisions",
            "other repo feature checkpoint for combined filter matrix",
            "--next-step",
            "run combined filter matrix",
            "--risks",
            "none",
            "--command",
            "echo other-feature",
            "--tag",
            "alpha",
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
        cwd=other_repo,
        env=env,
    )

    rows = json.loads(
        _run_dock(
            [
                command_name,
                    "mtrbtoken",
                "--tag",
                "alpha",
                "--repo",
                git_repo.name,
                "--branch",
                target_branch,
                "--json",
            ],
            cwd=tmp_path,
            env=env,
        ).stdout
    )
    assert len(rows) == 1
    assert rows[0]["objective"] == f"mtrbtoken tf-{command_name}"
    assert rows[0]["berth_name"] == git_repo.name
    assert rows[0]["branch"] == target_branch

    table_output = _run_dock(
        [
            command_name,
            "mtrbtoken",
            "--tag",
            "alpha",
            "--repo",
            git_repo.name,
            "--branch",
            target_branch,
        ],
        cwd=tmp_path,
        env=env,
    ).stdout
    assert f"tf-{command_name}" in table_output
    assert f"tm-{command_name}" not in table_output
    assert f"of-{command_name}" not in table_output
    assert "Traceback" not in table_output


@pytest.mark.parametrize("command_name", ["search", "f"])
def test_search_tag_repo_branch_limit_semantics_across_multi_branch_matches(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Combined filters should apply --limit after tag/repo/branch narrowing."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    base_branch = _git_current_branch(git_repo)
    target_branch = "feature/matrix-target-limit"

    subprocess.run(
        ["git", "checkout", "-b", target_branch],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"mtrbltoken one-{command_name}",
            "--decisions",
            "target feature checkpoint one for combined limit matrix",
            "--next-step",
            "run combined filter matrix with limit",
            "--risks",
            "none",
            "--command",
            "echo one",
            "--tag",
            "alpha",
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
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"mtrbltoken two-{command_name}",
            "--decisions",
            "target feature checkpoint two for combined limit matrix",
            "--next-step",
            "run combined filter matrix with limit",
            "--risks",
            "none",
            "--command",
            "echo two",
            "--tag",
            "alpha",
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
    subprocess.run(
        ["git", "checkout", base_branch],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )

    other_repo = tmp_path / f"multi-tag-repo-branch-limit-{command_name}"
    other_repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=str(other_repo), check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "dockyard@example.com"],
        cwd=str(other_repo),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Dockyard Test"],
        cwd=str(other_repo),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", f"git@github.com:org/{command_name}-multi-tag-branch-limit.git"],
        cwd=str(other_repo),
        check=True,
        capture_output=True,
    )
    (other_repo / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=str(other_repo), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=str(other_repo), check=True, capture_output=True)
    subprocess.run(
        ["git", "checkout", "-b", target_branch],
        cwd=str(other_repo),
        check=True,
        capture_output=True,
    )
    _run_dock(
        [
            "save",
            "--root",
            str(other_repo),
            "--no-prompt",
            "--objective",
            f"mtrbltoken other-{command_name}",
            "--decisions",
            "other repo feature checkpoint for combined limit matrix",
            "--next-step",
            "run combined filter matrix with limit",
            "--risks",
            "none",
            "--command",
            "echo other",
            "--tag",
            "alpha",
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
        cwd=other_repo,
        env=env,
    )

    rows = json.loads(
        _run_dock(
            [
                command_name,
                "mtrbltoken",
                "--tag",
                "alpha",
                "--repo",
                git_repo.name,
                "--branch",
                target_branch,
                "--limit",
                "1",
                "--json",
            ],
            cwd=tmp_path,
            env=env,
        ).stdout
    )
    assert len(rows) == 1
    assert rows[0]["berth_name"] == git_repo.name
    assert rows[0]["branch"] == target_branch
    assert rows[0]["objective"] in {f"mtrbltoken one-{command_name}", f"mtrbltoken two-{command_name}"}

    table_output = _run_dock(
        [
            command_name,
            "mtrbltoken",
            "--tag",
            "alpha",
            "--repo",
            git_repo.name,
            "--branch",
            target_branch,
            "--limit",
            "1",
        ],
        cwd=tmp_path,
        env=env,
    ).stdout
    assert f"other-{command_name}" not in table_output
    assert "No checkpoint matches found." not in table_output
    assert "Traceback" not in table_output


def test_search_branch_filter_semantics_non_json(git_repo: Path, tmp_path: Path) -> None:
    """Search should honor branch filters in non-JSON table output."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    default_branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "psbf-default",
            "--decisions",
            "default branch checkpoint for primary branch filtering",
            "--next-step",
            "run primary branch filter",
            "--risks",
            "none",
            "--command",
            "echo default",
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
    subprocess.run(
        ["git", "checkout", "-b", "feature/primary-branch-filter"],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "psbf-feature",
            "--decisions",
            "feature branch checkpoint for primary branch filtering",
            "--next-step",
            "run primary branch filter",
            "--risks",
            "none",
            "--command",
            "echo feature",
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
    subprocess.run(
        ["git", "checkout", default_branch],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )

    rows = json.loads(
        _run_dock(
            ["search", "psbf", "--branch", "feature/primary-branch-filter", "--json"],
            cwd=tmp_path,
            env=env,
        ).stdout
    )
    assert len(rows) == 1
    assert rows[0]["branch"] == "feature/primary-branch-filter"

    output = _run_dock(
        ["search", "psbf", "--branch", "feature/primary-branch-filter"],
        cwd=tmp_path,
        env=env,
    ).stdout
    assert "psbf-feature" in output
    assert "psbf-default" not in output
    assert "Traceback" not in output


def test_search_branch_filter_no_match_json_returns_empty_array(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Search JSON should return [] when branch filter excludes results."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Branch filter no-match objective",
            "--decisions",
            "Branch filter no-match decisions",
            "--next-step",
            "run branch filtered search",
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

    result = _run_dock(
        ["search", "Branch filter no-match objective", "--branch", "missing/branch", "--json"],
        cwd=tmp_path,
        env=env,
    )
    assert json.loads(result.stdout) == []
    assert "Traceback" not in f"{result.stdout}\n{result.stderr}"


def test_search_branch_filter_no_match_is_informative(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Search should show no-match guidance when branch filter excludes rows."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Branch filter no-match message objective",
            "--decisions",
            "Branch filter no-match message decisions",
            "--next-step",
            "run branch filtered search",
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

    result = _run_dock(
        ["search", "Branch filter no-match message objective", "--branch", "missing/branch"],
        cwd=tmp_path,
        env=env,
    )
    assert "No checkpoint matches found." in result.stdout
    assert "Traceback" not in f"{result.stdout}\n{result.stderr}"


def test_search_tag_repo_filter_semantics_non_json(git_repo: Path, tmp_path: Path) -> None:
    """Search should honor combined tag+repo filters in table mode."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "primary-tag-repo-alpha-token",
            "--decisions",
            "alpha-tag checkpoint for primary tag+repo filtering",
            "--next-step",
            "run primary tag+repo filter",
            "--risks",
            "none",
            "--command",
            "echo alpha",
            "--tag",
            "alpha",
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
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "primary-tag-repo-beta-token",
            "--decisions",
            "beta-tag checkpoint for primary tag+repo filtering",
            "--next-step",
            "run primary tag+repo filter",
            "--risks",
            "none",
            "--command",
            "echo beta",
            "--tag",
            "beta",
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

    filtered = _run_dock(
        [
            "search",
            "primary-tag-repo",
            "--tag",
            "beta",
            "--repo",
            git_repo.name,
        ],
        cwd=tmp_path,
        env=env,
    ).stdout
    assert "primary-tag-repo-beta-token" in filtered
    assert "primary-tag-repo-alpha-token" not in filtered
    assert "Traceback" not in filtered


def test_search_tag_branch_filter_semantics_non_json(git_repo: Path, tmp_path: Path) -> None:
    """Search should honor combined tag+branch filters in table mode."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    default_branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "ptb-default",
            "--decisions",
            "default branch checkpoint for primary tag+branch filtering",
            "--next-step",
            "run primary tag+branch filter",
            "--risks",
            "none",
            "--command",
            "echo default",
            "--tag",
            "alpha",
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
    subprocess.run(
        ["git", "checkout", "-b", "feature/primary-tag-branch-filter"],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "ptb-feature",
            "--decisions",
            "feature branch checkpoint for primary tag+branch filtering",
            "--next-step",
            "run primary tag+branch filter",
            "--risks",
            "none",
            "--command",
            "echo feature",
            "--tag",
            "alpha",
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
    subprocess.run(
        ["git", "checkout", default_branch],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )

    filtered = _run_dock(
        [
            "search",
            "ptb",
            "--tag",
            "alpha",
            "--branch",
            "feature/primary-tag-branch-filter",
        ],
        cwd=tmp_path,
        env=env,
    ).stdout
    assert "ptb-feature" in filtered
    assert "ptb-default" not in filtered
    assert "Traceback" not in filtered


def test_search_tag_repo_filter_no_match_json_returns_empty_array(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Search JSON should return [] when combined tag+repo filters exclude rows."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Tag repo filter no-match objective",
            "--decisions",
            "Tag repo filter no-match decisions",
            "--next-step",
            "run tag repo filtered search",
            "--risks",
            "none",
            "--command",
            "echo noop",
            "--tag",
            "alpha",
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

    result = _run_dock(
        ["search", "Tag repo filter no-match objective", "--tag", "alpha", "--repo", "missing-berth", "--json"],
        cwd=tmp_path,
        env=env,
    )
    assert json.loads(result.stdout) == []
    assert "Traceback" not in f"{result.stdout}\n{result.stderr}"


def test_search_tag_repo_filter_no_match_is_informative(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Search should keep no-match guidance for combined tag+repo misses."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Tag repo filter message objective",
            "--decisions",
            "Tag repo filter message decisions",
            "--next-step",
            "run tag repo filtered search",
            "--risks",
            "none",
            "--command",
            "echo noop",
            "--tag",
            "alpha",
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

    result = _run_dock(
        ["search", "Tag repo filter message objective", "--tag", "alpha", "--repo", "missing-berth"],
        cwd=tmp_path,
        env=env,
    )
    assert "No checkpoint matches found." in result.stdout
    assert "Traceback" not in f"{result.stdout}\n{result.stderr}"


def test_search_tag_branch_filter_no_match_json_returns_empty_array(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Search JSON should return [] when combined tag+branch filters miss."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Tag branch filter no-match objective",
            "--decisions",
            "Tag branch filter no-match decisions",
            "--next-step",
            "run tag branch filtered search",
            "--risks",
            "none",
            "--command",
            "echo noop",
            "--tag",
            "alpha",
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

    result = _run_dock(
        ["search", "Tag branch filter no-match objective", "--tag", "alpha", "--branch", "missing/branch", "--json"],
        cwd=tmp_path,
        env=env,
    )
    assert json.loads(result.stdout) == []
    assert "Traceback" not in f"{result.stdout}\n{result.stderr}"


def test_search_tag_branch_filter_no_match_is_informative(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Search should keep no-match guidance for combined tag+branch misses."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Tag branch filter message objective",
            "--decisions",
            "Tag branch filter message decisions",
            "--next-step",
            "run tag branch filtered search",
            "--risks",
            "none",
            "--command",
            "echo noop",
            "--tag",
            "alpha",
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

    result = _run_dock(
        ["search", "Tag branch filter message objective", "--tag", "alpha", "--branch", "missing/branch"],
        cwd=tmp_path,
        env=env,
    )
    assert "No checkpoint matches found." in result.stdout
    assert "Traceback" not in f"{result.stdout}\n{result.stderr}"


def test_search_tag_repo_branch_filter_no_match_json_returns_empty_array(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Search JSON should return [] when tag+repo+branch filters exclude rows."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Tag repo branch filter no-match objective",
            "--decisions",
            "Tag repo branch filter no-match decisions",
            "--next-step",
            "run tag repo branch filtered search",
            "--risks",
            "none",
            "--command",
            "echo noop",
            "--tag",
            "alpha",
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

    result = _run_dock(
        [
            "search",
            "Tag repo branch filter no-match objective",
            "--tag",
            "alpha",
            "--repo",
            "missing-berth",
            "--branch",
            "missing/branch",
            "--json",
        ],
        cwd=tmp_path,
        env=env,
    )
    assert json.loads(result.stdout) == []
    assert "Traceback" not in f"{result.stdout}\n{result.stderr}"


def test_search_tag_repo_branch_filter_no_match_is_informative(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Search should keep no-match guidance for tag+repo+branch misses."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Tag repo branch filter message objective",
            "--decisions",
            "Tag repo branch filter message decisions",
            "--next-step",
            "run tag repo branch filtered search",
            "--risks",
            "none",
            "--command",
            "echo noop",
            "--tag",
            "alpha",
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

    result = _run_dock(
        [
            "search",
            "Tag repo branch filter message objective",
            "--tag",
            "alpha",
            "--repo",
            "missing-berth",
            "--branch",
            "missing/branch",
        ],
        cwd=tmp_path,
        env=env,
    )
    assert "No checkpoint matches found." in result.stdout
    assert "Traceback" not in f"{result.stdout}\n{result.stderr}"


@pytest.mark.parametrize("command_name", ["search", "f"])
def test_search_tag_repo_branch_limit_no_match_json_returns_empty_array(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Combined tag+repo+branch+limit JSON misses should return [] cleanly."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"Tag repo branch limit no-match objective ({command_name})",
            "--decisions",
            "Tag repo branch limit no-match decisions",
            "--next-step",
            "run tag repo branch limit filtered search",
            "--risks",
            "none",
            "--command",
            "echo noop",
            "--tag",
            "alpha",
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

    result = _run_dock(
        [
            command_name,
            f"Tag repo branch limit no-match objective ({command_name})",
            "--tag",
            "alpha",
            "--repo",
            "missing-berth",
            "--branch",
            "missing/branch",
            "--limit",
            "1",
            "--json",
        ],
        cwd=tmp_path,
        env=env,
    )
    assert json.loads(result.stdout) == []
    assert "Traceback" not in f"{result.stdout}\n{result.stderr}"


@pytest.mark.parametrize("command_name", ["search", "f"])
def test_search_tag_repo_branch_limit_no_match_is_informative(
    git_repo: Path,
    tmp_path: Path,
    command_name: str,
) -> None:
    """Combined tag+repo+branch+limit misses should keep no-match guidance."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            f"Tag repo branch limit message objective ({command_name})",
            "--decisions",
            "Tag repo branch limit message decisions",
            "--next-step",
            "run tag repo branch limit filtered search",
            "--risks",
            "none",
            "--command",
            "echo noop",
            "--tag",
            "alpha",
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

    result = _run_dock(
        [
            command_name,
            f"Tag repo branch limit message objective ({command_name})",
            "--tag",
            "alpha",
            "--repo",
            "missing-berth",
            "--branch",
            "missing/branch",
            "--limit",
            "1",
        ],
        cwd=tmp_path,
        env=env,
    )
    assert "No checkpoint matches found." in result.stdout
    assert "Traceback" not in f"{result.stdout}\n{result.stderr}"


def test_search_json_snippet_includes_risk_match(git_repo: Path, tmp_path: Path) -> None:
    """Search snippets should surface matches from risks text."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Risk snippet objective",
            "--decisions",
            "generic decisions text",
            "--next-step",
            "generic next step",
            "--risks",
            "Requires risktoken validation before deploy",
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

    rows = json.loads(_run_dock(["search", "risktoken", "--json"], cwd=tmp_path, env=env).stdout)
    assert len(rows) == 1
    assert "risktoken" in rows[0]["snippet"].lower()


def test_search_json_parser_error_query_honors_repo_branch_filters(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Parser-error fallback path should preserve repo/branch filter semantics."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    base_branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "pf-target security/path",
            "--decisions",
            "Keep fallback query filters stable",
            "--next-step",
            "Validate parser fallback filter semantics",
            "--risks",
            "none",
            "--command",
            "echo main",
            "--tag",
            "parser-fallback",
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

    subprocess.run(
        ["git", "checkout", "-b", "feature/parser-fallback-other"],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "pf-sibling security/path",
            "--decisions",
            "Other branch record should be filtered out",
            "--next-step",
            "Ensure branch filter is honored",
            "--risks",
            "none",
            "--command",
            "echo feature",
            "--tag",
            "parser-fallback",
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

    rows = json.loads(
        _run_dock(
            [
                "search",
                "security/path",
                "--json",
                "--repo",
                git_repo.name,
                "--branch",
                base_branch,
            ],
            cwd=tmp_path,
            env=env,
        ).stdout
    )
    assert len(rows) == 1
    assert rows[0]["objective"] == "pf-target security/path"
    tagged_rows = json.loads(
        _run_dock(
            [
                "search",
                "security/path",
                "--json",
                "--tag",
                "parser-fallback",
                "--repo",
                git_repo.name,
                "--branch",
                base_branch,
            ],
            cwd=tmp_path,
            env=env,
        ).stdout
    )
    assert len(tagged_rows) == 1
    assert tagged_rows[0]["objective"] == "pf-target security/path"
    tagged_limit_rows = json.loads(
        _run_dock(
            [
                "search",
                "security/path",
                "--json",
                "--tag",
                "parser-fallback",
                "--repo",
                git_repo.name,
                "--branch",
                base_branch,
                "--limit",
                "1",
            ],
            cwd=tmp_path,
            env=env,
        ).stdout
    )
    assert len(tagged_limit_rows) == 1
    assert tagged_limit_rows[0]["objective"] == "pf-target security/path"
    table_output = _run_dock(
        [
            "search",
            "security/path",
            "--repo",
            git_repo.name,
            "--branch",
            base_branch,
        ],
        cwd=tmp_path,
        env=env,
    ).stdout
    assert "pf-target" in table_output
    assert "pf-sibling" not in table_output
    assert "Traceback" not in table_output
    tagged_table_output = _run_dock(
        [
            "search",
            "security/path",
            "--tag",
            "parser-fallback",
            "--repo",
            git_repo.name,
            "--branch",
            base_branch,
        ],
        cwd=tmp_path,
        env=env,
    ).stdout
    assert "pf-target" in tagged_table_output
    assert "pf-sibling" not in tagged_table_output
    assert "Traceback" not in tagged_table_output
    tagged_limit_table_output = _run_dock(
        [
            "search",
            "security/path",
            "--tag",
            "parser-fallback",
            "--repo",
            git_repo.name,
            "--branch",
            base_branch,
            "--limit",
            "1",
        ],
        cwd=tmp_path,
        env=env,
    ).stdout
    assert "pf-target" in tagged_limit_table_output
    assert "pf-sibling" not in tagged_limit_table_output
    assert "Traceback" not in tagged_limit_table_output


def test_search_alias_parser_error_query_honors_repo_branch_filters(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Search alias parser fallback should keep repo/branch filters intact."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    base_branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "apf-target security/path",
            "--decisions",
            "Keep alias fallback query filters stable",
            "--next-step",
            "Validate alias parser fallback filter semantics",
            "--risks",
            "none",
            "--command",
            "echo main",
            "--tag",
            "parser-fallback-alias",
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

    subprocess.run(
        ["git", "checkout", "-b", "feature/parser-fallback-alias-other"],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "apf-sibling security/path",
            "--decisions",
            "Other branch alias record should be filtered out",
            "--next-step",
            "Ensure alias branch filter is honored",
            "--risks",
            "none",
            "--command",
            "echo feature",
            "--tag",
            "parser-fallback-alias",
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

    rows = json.loads(
        _run_dock(
            [
                "f",
                "security/path",
                "--json",
                "--repo",
                git_repo.name,
                "--branch",
                base_branch,
            ],
            cwd=tmp_path,
            env=env,
        ).stdout
    )
    assert len(rows) == 1
    assert rows[0]["objective"] == "apf-target security/path"
    tagged_rows = json.loads(
        _run_dock(
            [
                "f",
                "security/path",
                "--json",
                "--tag",
                "parser-fallback-alias",
                "--repo",
                git_repo.name,
                "--branch",
                base_branch,
            ],
            cwd=tmp_path,
            env=env,
        ).stdout
    )
    assert len(tagged_rows) == 1
    assert tagged_rows[0]["objective"] == "apf-target security/path"
    tagged_limit_rows = json.loads(
        _run_dock(
            [
                "f",
                "security/path",
                "--json",
                "--tag",
                "parser-fallback-alias",
                "--repo",
                git_repo.name,
                "--branch",
                base_branch,
                "--limit",
                "1",
            ],
            cwd=tmp_path,
            env=env,
        ).stdout
    )
    assert len(tagged_limit_rows) == 1
    assert tagged_limit_rows[0]["objective"] == "apf-target security/path"
    table_output = _run_dock(
        [
            "f",
            "security/path",
            "--repo",
            git_repo.name,
            "--branch",
            base_branch,
        ],
        cwd=tmp_path,
        env=env,
    ).stdout
    assert "apf-target" in table_output
    assert "apf-sibling" not in table_output
    assert "Traceback" not in table_output
    tagged_table_output = _run_dock(
        [
            "f",
            "security/path",
            "--tag",
            "parser-fallback-alias",
            "--repo",
            git_repo.name,
            "--branch",
            base_branch,
        ],
        cwd=tmp_path,
        env=env,
    ).stdout
    assert "apf-target" in tagged_table_output
    assert "apf-sibling" not in tagged_table_output
    assert "Traceback" not in tagged_table_output
    tagged_limit_table_output = _run_dock(
        [
            "f",
            "security/path",
            "--tag",
            "parser-fallback-alias",
            "--repo",
            git_repo.name,
            "--branch",
            base_branch,
            "--limit",
            "1",
        ],
        cwd=tmp_path,
        env=env,
    ).stdout
    assert "apf-target" in tagged_limit_table_output
    assert "apf-sibling" not in tagged_limit_table_output
    assert "Traceback" not in tagged_limit_table_output


def test_search_json_snippet_includes_next_step_match(git_repo: Path, tmp_path: Path) -> None:
    """Search snippets should surface matches from next-step text."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Next-step snippet objective",
            "--decisions",
            "generic decisions text",
            "--next-step",
            "Run nexttoken verification before handoff",
            "--risks",
            "generic risks",
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

    rows = json.loads(_run_dock(["search", "nexttoken", "--json"], cwd=tmp_path, env=env).stdout)
    assert len(rows) == 1
    assert "nexttoken" in rows[0]["snippet"].lower()


def test_search_json_snippet_includes_decisions_match(git_repo: Path, tmp_path: Path) -> None:
    """Search snippets should surface matches from decisions text."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Decisions snippet objective",
            "--decisions",
            "Need decisiontoken guardrails before merge",
            "--next-step",
            "generic next step",
            "--risks",
            "generic risks",
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

    rows = json.loads(_run_dock(["search", "decisiontoken", "--json"], cwd=tmp_path, env=env).stdout)
    assert len(rows) == 1
    assert "decisiontoken" in rows[0]["snippet"].lower()


def test_search_json_snippet_includes_objective_match(git_repo: Path, tmp_path: Path) -> None:
    """Search snippets should surface matches from objective text."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Objectivetoken milestone",
            "--decisions",
            "generic decisions",
            "--next-step",
            "generic next step",
            "--risks",
            "generic risks",
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

    rows = json.loads(_run_dock(["search", "objectivetoken", "--json"], cwd=tmp_path, env=env).stdout)
    assert len(rows) == 1
    assert "objectivetoken" in rows[0]["snippet"].lower()


def test_search_json_snippet_is_bounded(git_repo: Path, tmp_path: Path) -> None:
    """Search snippets should stay within bounded length for readability."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    long_risk = "boundtoken " + ("x" * 400)
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Bounded snippet objective",
            "--decisions",
            "generic decisions",
            "--next-step",
            "generic next step",
            "--risks",
            long_risk,
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

    rows = json.loads(_run_dock(["search", "boundtoken", "--json"], cwd=tmp_path, env=env).stdout)
    assert len(rows) == 1
    assert len(rows[0]["snippet"]) <= 140


def test_search_json_multiline_snippet_remains_parseable(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Search JSON should remain parseable when snippet includes newlines."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    multiline_risk = "line1\nmultilinetoken line2\nline3"
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Multiline snippet objective",
            "--decisions",
            "generic decisions",
            "--next-step",
            "generic next step",
            "--risks",
            multiline_risk,
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

    rows = json.loads(_run_dock(["search", "multilinetoken", "--json"], cwd=tmp_path, env=env).stdout)
    assert len(rows) == 1
    assert "multilinetoken" in rows[0]["snippet"]
    assert "\n" not in rows[0]["snippet"]
    assert rows[0]["snippet"] == "line1 multilinetoken line2 line3"


def test_search_json_preserves_unicode_snippets(git_repo: Path, tmp_path: Path) -> None:
    """Search JSON output should preserve unicode text in snippets."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    unicode_risk = "Needs façade review before merge"
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Unicode snippet objective",
            "--decisions",
            "generic decisions",
            "--next-step",
            "generic next step",
            "--risks",
            unicode_risk,
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

    rows = json.loads(_run_dock(["search", "façade", "--json"], cwd=tmp_path, env=env).stdout)
    assert len(rows) == 1
    assert "façade" in rows[0]["snippet"]


def test_search_json_respects_limit(git_repo: Path, tmp_path: Path) -> None:
    """Search JSON mode should honor --limit constraint."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    base_branch = _git_current_branch(git_repo)

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "JSON limit objective one",
            "--decisions",
            "Search JSON limit baseline one",
            "--next-step",
            "Collect first result",
            "--risks",
            "none",
            "--command",
            "echo one",
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
    subprocess.run(
        ["git", "checkout", "-b", "feature/json-limit"],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )
    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "JSON limit objective two",
            "--decisions",
            "Search JSON limit baseline two",
            "--next-step",
            "Collect second result",
            "--risks",
            "none",
            "--command",
            "echo two",
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
    subprocess.run(
        ["git", "checkout", base_branch],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )

    rows = json.loads(_run_dock(["search", "JSON limit objective", "--limit", "1", "--json"], cwd=tmp_path, env=env).stdout)
    assert len(rows) == 1


def test_links_are_branch_scoped_and_persist(git_repo: Path, tmp_path: Path) -> None:
    """Links should remain scoped by branch across context switches."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    main_branch = _git_current_branch(git_repo)
    _run_dock(["link", "https://example.com/main-link"], cwd=git_repo, env=env)
    main_links = _run_dock(["links"], cwd=git_repo, env=env).stdout
    assert "https://example.com/main-link" in main_links

    subprocess.run(
        ["git", "checkout", "-b", "feature/links-scope"],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )
    _run_dock(["link", "https://example.com/feature-link"], cwd=git_repo, env=env)
    feature_links = _run_dock(["links"], cwd=git_repo, env=env).stdout
    assert "https://example.com/feature-link" in feature_links
    assert "https://example.com/main-link" not in feature_links

    subprocess.run(
        ["git", "checkout", main_branch],
        cwd=str(git_repo),
        check=True,
        capture_output=True,
    )
    main_links_again = _run_dock(["links"], cwd=git_repo, env=env).stdout
    assert "https://example.com/main-link" in main_links_again
    assert "https://example.com/feature-link" not in main_links_again


def test_link_commands_support_root_override_outside_repo(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Link and links commands should work from outside repo with --root."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        ["link", "https://example.com/root-override", "--root", str(git_repo)],
        cwd=tmp_path,
        env=env,
    )
    listed = _run_dock(["links", "--root", str(git_repo)], cwd=tmp_path, env=env).stdout
    assert "https://example.com/root-override" in listed


def test_link_and_links_accept_trimmed_root_override(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Link and links should resolve root override values after trimming."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    trimmed_root = f"  {git_repo}  "

    _run_dock(
        ["link", "https://example.com/trimmed-root", "--root", trimmed_root],
        cwd=tmp_path,
        env=env,
    )
    listed = _run_dock(["links", "--root", trimmed_root], cwd=tmp_path, env=env).stdout
    assert "https://example.com/trimmed-root" in listed


def test_link_and_links_reject_blank_root_override(tmp_path: Path) -> None:
    """Link and links should reject blank root override values."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    link_failed = _run_dock(
        ["link", "https://example.com/no-root", "--root", "   "],
        cwd=tmp_path,
        env=env,
        expect_code=2,
    )
    link_output = f"{link_failed.stdout}\n{link_failed.stderr}"
    assert "--root must be a non-empty string." in link_output
    assert "Traceback" not in link_output

    links_failed = _run_dock(
        ["links", "--root", "   "],
        cwd=tmp_path,
        env=env,
        expect_code=2,
    )
    links_output = f"{links_failed.stdout}\n{links_failed.stderr}"
    assert "--root must be a non-empty string." in links_output
    assert "Traceback" not in links_output


def test_link_rejects_blank_url(git_repo: Path, tmp_path: Path) -> None:
    """Link command should reject blank URL values with actionable error."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    failed = _run_dock(
        ["link", "   "],
        cwd=git_repo,
        env=env,
        expect_code=2,
    )
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "URL must be a non-empty string." in output
    assert "Traceback" not in output


def test_link_output_compacts_multiline_url_text(git_repo: Path, tmp_path: Path) -> None:
    """Link success output should compact multiline URL text."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    multiline_url = "https://example.com/line-one\nline-two"
    linked = _run_dock(["link", multiline_url], cwd=git_repo, env=env).stdout
    assert "https://example.com/line-one line-two" in linked
    assert "https://example.com/line-one\nline-two" not in linked


def test_link_trims_surrounding_whitespace_from_url_input(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Link command should trim outer whitespace from URL input."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    linked = _run_dock(["link", "  https://example.com/trimmed  "], cwd=git_repo, env=env).stdout
    assert "https://example.com/trimmed" in linked
    assert "  https://example.com/trimmed  " not in linked

    listed = _run_dock(["links"], cwd=git_repo, env=env).stdout
    assert "https://example.com/trimmed" in listed
    assert "  https://example.com/trimmed  " not in listed


def test_links_output_compacts_multiline_url_text(git_repo: Path, tmp_path: Path) -> None:
    """Links list should compact multiline URL text into one-line previews."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    multiline_url = "https://example.com/line-one\nline-two"
    _run_dock(["link", multiline_url], cwd=git_repo, env=env)

    listed = _run_dock(["links"], cwd=git_repo, env=env).stdout
    assert "https://example.com/line-one line-two" in listed
    assert "https://example.com/line-one\nline-two" not in listed


def test_links_output_falls_back_for_blank_fields(git_repo: Path, tmp_path: Path) -> None:
    """Links output should show explicit fallbacks for blank row fields."""
    env = dict(os.environ)
    dock_home = tmp_path / ".dockyard_data"
    env["DOCKYARD_HOME"] = str(dock_home)

    _run_dock(["link", "https://example.com/base-link"], cwd=git_repo, env=env)
    db_path = dock_home / "db" / "index.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE links SET created_at = ?, url = ?",
        ("   ", "   "),
    )
    conn.commit()
    conn.close()

    listed = _run_dock(["links"], cwd=git_repo, env=env).stdout
    assert "(unknown) | (unknown)" in listed


def test_link_outputs_preserve_literal_markup_like_urls(git_repo: Path, tmp_path: Path) -> None:
    """Link command output should preserve literal bracketed URL text."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    literal_url = "https://example.com/[red]literal[/red]"
    linked = _run_dock(["link", literal_url], cwd=git_repo, env=env).stdout
    assert literal_url in linked

    listed = _run_dock(["links"], cwd=git_repo, env=env).stdout
    assert literal_url in listed


def test_link_outside_repo_without_root_is_actionable(tmp_path: Path) -> None:
    """Link command outside repo should fail unless root override is provided."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    failed = _run_dock(
        ["link", "https://example.com/no-root"],
        cwd=tmp_path,
        env=env,
        expect_code=2,
    )
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "not inside a git repository" in output
    assert "Traceback" not in output


def test_links_outside_repo_without_root_is_actionable(tmp_path: Path) -> None:
    """Links command outside repo should fail unless root override is provided."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    failed = _run_dock(
        ["links"],
        cwd=tmp_path,
        env=env,
        expect_code=2,
    )
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "not inside a git repository" in output
    assert "Traceback" not in output


def test_links_in_repo_with_no_items_is_informative(git_repo: Path, tmp_path: Path) -> None:
    """Links command should print informative message when none are attached."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    output = _run_dock(["links"], cwd=git_repo, env=env).stdout
    assert "No links for current slip." in output


def test_save_with_non_git_root_is_actionable(tmp_path: Path) -> None:
    """Save should fail clearly when --root points to a non-git directory."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    non_git_root = tmp_path / "not_a_repo"
    non_git_root.mkdir()

    failed = _run_dock(
        [
            "save",
            "--root",
            str(non_git_root),
            "--no-prompt",
            "--objective",
            "Non-git root validation objective",
            "--decisions",
            "Ensure actionable root validation error",
            "--next-step",
            "do not write checkpoint",
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
        cwd=tmp_path,
        env=env,
        expect_code=2,
    )
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "git repository" in output
    assert "Traceback" not in output


@pytest.mark.parametrize(
    ("command", "args"),
    [
        ("link", ["https://example.com/non-git-root"]),
        ("links", []),
    ],
    ids=["link", "links"],
)
def test_link_commands_reject_non_git_root_override(
    tmp_path: Path,
    command: str,
    args: list[str],
) -> None:
    """Link/links commands should fail clearly for non-git root overrides."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")
    non_git_root = tmp_path / "not_a_repo_for_links"
    non_git_root.mkdir()

    failed = _run_dock(
        [
            command,
            *args,
            "--root",
            str(non_git_root),
        ],
        cwd=tmp_path,
        env=env,
        expect_code=2,
    )
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "git repository" in output
    assert "Traceback" not in output
