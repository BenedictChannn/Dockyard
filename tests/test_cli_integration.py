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


def test_resume_run_with_no_commands_is_noop_success(
    git_repo: Path,
    tmp_path: Path,
) -> None:
    """Resume --run should succeed when no commands were recorded."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "No command resume run",
            "--decisions",
            "Ensure run path handles empty command list",
            "--next-step",
            "resume with run",
            "--risks",
            "none",
            "--tests-run",
            "--tests-command",
            "pytest -q",
            "--build-ok",
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
    # Should not print any command execution rows when none exist.
    assert "-> exit" not in result.stdout


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
    assert json.loads(_run_dock(["f", "definitely-no-match", "--json"], cwd=tmp_path, env=env).stdout) == []

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
    assert "checkpoint_id: cp_" in open_result.stdout
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
    assert "checkpoint_id: cp_missing_123" in opened.stdout
    assert "status: missing from index" in opened.stdout


def test_review_open_displays_file_list(git_repo: Path, tmp_path: Path) -> None:
    """Review open output should include associated file paths."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Review file display baseline",
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


def test_review_open_displays_notes(git_repo: Path, tmp_path: Path) -> None:
    """Review open output should include optional notes text."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    _run_dock(
        [
            "save",
            "--root",
            str(git_repo),
            "--no-prompt",
            "--objective",
            "Review notes baseline",
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
    assert "checkpoint_id:" in opened.stdout
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


def test_review_done_unknown_id_is_actionable(tmp_path: Path) -> None:
    """Unknown review id resolution should fail without traceback noise."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    failed = _run_dock(["review", "done", "rev_missing"], cwd=tmp_path, env=env, expect_code=2)
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "Review item not found: rev_missing" in output
    assert "Traceback" not in output


def test_review_all_with_no_items_is_informative(tmp_path: Path) -> None:
    """Review --all should report no items when ledger is empty."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    result = _run_dock(["review", "--all"], cwd=tmp_path, env=env)
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
    search_repo_json = json.loads(
        _run_dock(
            ["search", "Filter target objective", "--repo", git_repo.name, "--json"],
            cwd=tmp_path,
            env=env,
        ).stdout
    )
    assert len(search_repo_json) >= 1
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


def test_harbor_alias_validates_limit_argument(tmp_path: Path) -> None:
    """Harbor alias should enforce the same limit validation as ls."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    failed = _run_dock(["harbor", "--limit", "0"], cwd=tmp_path, env=env, expect_code=2)
    output = f"{failed.stdout}\n{failed.stderr}"
    assert "--limit must be >= 1." in output
    assert "Traceback" not in output


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
            "Tagged alpha checkpoint",
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
            "Tagged alpha checkpoint two",
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


def test_search_no_matches_json_returns_empty_array(tmp_path: Path) -> None:
    """JSON search output should remain machine-parseable when empty."""
    env = dict(os.environ)
    env["DOCKYARD_HOME"] = str(tmp_path / ".dockyard_data")

    result = _run_dock(["search", "nothing-will-match", "--json"], cwd=tmp_path, env=env)
    assert json.loads(result.stdout) == []


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
