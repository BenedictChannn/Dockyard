"""Integration tests for CLI command flows."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
from pathlib import Path


def _run_dock(
    args: list[str],
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
        ["python3", "-m", "dockyard", *args],
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


def test_resume_run_stops_on_failure(git_repo: Path, tmp_path: Path) -> None:
    """Resume --run must stop at first failing command."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Check run ordering",
            "--decisions",
            "Run list should stop on first failing command",
            "--next-step",
            "Observe command exit sequence",
            "--risks",
            "None",
            "--command",
            "echo first",
            "--command",
            "false",
            "--command",
            "echo should-not-run",
            "--tests-run",
            "--tests-command",
            "pytest -q",
            "--build-ok",
            "--build-command",
            "echo build",
            "--lint-fail",
            "--smoke-fail",
            "--no-auto-review",
        ],
        cwd=git_repo,
        env=env,
    )

    run_result = _run_dock(["resume", "--run"], cwd=git_repo, env=env, expect_code=1)
    assert "$ echo first -> exit 0" in run_result.stdout
    assert "$ false -> exit 1" in run_result.stdout
    assert "$ echo should-not-run -> exit" not in run_result.stdout


def test_resume_run_executes_all_commands_on_success(git_repo: Path, tmp_path: Path) -> None:
    """Resume --run should execute all commands when none fail."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Run success path",
            "--decisions",
            "Verify all commands execute when successful",
            "--next-step",
            "Run resume --run",
            "--risks",
            "None",
            "--command",
            "echo first-ok",
            "--command",
            "echo second-ok",
            "--tests-run",
            "--tests-command",
            "pytest -q",
            "--build-ok",
            "--build-command",
            "echo build",
            "--lint-fail",
            "--smoke-fail",
            "--no-auto-review",
        ],
        cwd=git_repo,
        env=env,
    )

    result = _run_dock(["resume", "--run"], cwd=git_repo, env=env)
    assert "$ echo first-ok -> exit 0" in result.stdout
    assert "$ echo second-ok -> exit 0" in result.stdout


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


def test_error_output_has_no_traceback(tmp_path: Path) -> None:
    """Dockyard user-facing errors should be actionable without traceback spam."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    result = _run_dock(["resume"], cwd=tmp_path, env=env, expect_code=2)
    output = f"{result.stdout}\n{result.stderr}"
    assert "Error:" in output
    assert "Traceback" not in output


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
    lines = [line for line in result.stdout.splitlines() if line.strip()]
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

    # Ensure ordering remains scannable and consistent for quick resume.
    assert positions == sorted(positions)


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

    resume_alias = _run_dock(["r"], cwd=git_repo, env=env)
    assert "Objective: Alias coverage objective" in resume_alias.stdout


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


def test_review_open_shows_associated_checkpoint(git_repo: Path, tmp_path: Path) -> None:
    """Auto-created review should link back to associated checkpoint details."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    security_dir = git_repo / "security"
    security_dir.mkdir(exist_ok=True)
    (security_dir / "guard.py").write_text("print('guard')\n", encoding="utf-8")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Trigger risky review linkage",
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
    assert "Associated Checkpoint" in open_result.stdout
    assert "Trigger risky review linkage" in open_result.stdout


def test_review_open_shows_missing_checkpoint_notice(git_repo: Path, tmp_path: Path) -> None:
    """Review open should indicate when checkpoint link is missing."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Missing checkpoint notice baseline",
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
    assert "status: missing from index" in opened.stdout


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

    listed = _run_dock(["review"], cwd=tmp_path, env=env).stdout
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

    # Upper-case values should normalize successfully.
    good = _run_dock(
        ["review", "add", "--reason", "valid", "--severity", "HIGH"],
        cwd=git_repo,
        env=env,
    )
    assert "Created review" in good.stdout


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
