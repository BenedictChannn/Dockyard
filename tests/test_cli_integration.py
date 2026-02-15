"""Integration tests for CLI command flows."""

from __future__ import annotations

import json
import os
import re
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
