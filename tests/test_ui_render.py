"""Unit tests for Rich rendering helpers."""

from __future__ import annotations

from rich.console import Console

from dockyard.models import Checkpoint, VerificationState
from dockyard.ui.render import (
    format_age,
    print_harbor,
    print_resume,
    print_search,
    verification_summary,
)


def _checkpoint() -> Checkpoint:
    """Create minimal checkpoint fixture for rendering tests."""
    return Checkpoint(
        id="cp_ui_1",
        repo_id="repo_ui",
        branch="main",
        created_at="2026-01-01T00:00:00+00:00",
        objective="Objective",
        decisions="Decisions",
        next_steps=["step"],
        risks_review="risks",
        resume_commands=[],
        git_dirty=False,
        head_sha="abc",
        head_subject="subject",
        recent_commits=[],
        diff_files_changed=0,
        diff_insertions=0,
        diff_deletions=0,
        touched_files=[],
        diff_stat_text="",
        verification=VerificationState(tests_run=True, build_ok=False, lint_ok=True),
        tags=[],
    )


def test_format_age_returns_unknown_for_invalid_timestamp() -> None:
    """Invalid timestamps should render as unknown age."""
    assert format_age("not-a-timestamp") == "unknown"


def test_format_age_returns_unknown_for_non_string_timestamp() -> None:
    """Non-string timestamps should render as unknown age."""
    assert format_age(None) == "unknown"  # type: ignore[arg-type]


def test_format_age_clamps_future_timestamps_to_zero_seconds() -> None:
    """Future timestamps should render as 0s instead of negative age."""
    assert format_age("2999-01-01T00:00:00+00:00") == "0s"


def test_format_age_accepts_naive_iso_timestamps() -> None:
    """Naive ISO timestamps should be interpreted safely as UTC."""
    age = format_age("2020-01-01T00:00:00")
    assert age != "unknown"
    assert age[-1] in {"s", "m", "h", "d"}


def test_format_age_supports_day_scale_output() -> None:
    """Past timestamps should support compact day-scale output."""
    assert format_age("2000-01-01T00:00:00+00:00").endswith("d")


def test_verification_summary_uses_yes_no_markers() -> None:
    """Verification summary should map booleans to yes/no values."""
    assert verification_summary(_checkpoint()) == "tests:yes build:no lint:yes"


def test_verification_summary_all_false_flags() -> None:
    """Verification summary should remain explicit when all checks are false."""
    checkpoint = _checkpoint()
    checkpoint.verification = VerificationState(tests_run=False, build_ok=False, lint_ok=False)
    assert verification_summary(checkpoint) == "tests:no build:no lint:no"


def test_print_resume_shows_placeholder_when_next_steps_empty() -> None:
    """Resume rendering should show placeholder when next steps are empty."""
    checkpoint = _checkpoint()
    checkpoint.next_steps = []
    console = Console(record=True, width=120)
    print_resume(console, checkpoint, open_reviews=0, project_name="repo-ui")
    output = console.export_text()
    assert "Next Steps:" in output
    assert "(none recorded)" in output


def test_print_resume_normalizes_multiline_summary_fields() -> None:
    """Resume summary should compact objective and next steps to one line."""
    checkpoint = _checkpoint()
    checkpoint.objective = "Objective line 1\nObjective line 2"
    checkpoint.next_steps = ["Step line 1\nStep line 2"]
    console = Console(record=True, width=120)
    print_resume(console, checkpoint, open_reviews=0, project_name="repo-ui")
    output = console.export_text()
    assert "Objective: Objective line 1 Objective line 2" in output
    assert "1. Step line 1 Step line 2" in output


def test_print_resume_bounds_long_summary_fields() -> None:
    """Resume summary should bound objective and next-step preview lengths."""
    checkpoint = _checkpoint()
    checkpoint.objective = "x" * 260
    checkpoint.next_steps = ["y" * 260]
    console = Console(record=True, width=120)
    print_resume(console, checkpoint, open_reviews=0, project_name="repo-ui")
    output = console.export_text()
    assert "x" * 201 not in output
    assert "y" * 201 not in output


def test_print_search_empty_state_message() -> None:
    """Empty search result rendering should show informative message."""
    console = Console(record=True, width=120)
    print_search(console, [])
    output = console.export_text()
    assert "No checkpoint matches found." in output


def test_print_search_falls_back_to_repo_id_without_berth_name() -> None:
    """Search rendering should fallback to repo_id when berth name missing."""
    console = Console(record=True, width=120)
    print_search(
        console,
        [
            {
                "repo_id": "repo_fallback",
                "branch": "main",
                "created_at": "2026-01-01T00:00:00+00:00",
                "snippet": "snippet",
            }
        ],
    )
    output = console.export_text()
    assert "repo_fallback" in output


def test_print_search_truncates_long_snippets() -> None:
    """Rendered search table should not print full unbounded snippets."""
    long_snippet = "x" * 200
    console = Console(record=True, width=120)
    print_search(
        console,
        [
            {
                "repo_id": "repo_fallback",
                "branch": "main",
                "created_at": "2026-01-01T00:00:00+00:00",
                "snippet": long_snippet,
            }
        ],
    )
    output = console.export_text()
    assert long_snippet not in output
    assert "x" * 121 not in output


def test_print_search_handles_non_string_snippet() -> None:
    """Search renderer should tolerate non-string snippet payloads."""
    console = Console(record=True, width=120)
    print_search(
        console,
        [
            {
                "repo_id": "repo_non_string",
                "branch": "main",
                "created_at": "2026-01-01T00:00:00+00:00",
                "snippet": None,
            }
        ],
    )
    output = console.export_text()
    assert "repo_non_string" in output


def test_print_search_handles_non_string_created_at() -> None:
    """Search renderer should tolerate non-string timestamp payloads."""
    console = Console(record=True, width=120)
    print_search(
        console,
        [
            {
                "repo_id": "repo_created_at",
                "branch": "main",
                "created_at": None,
                "snippet": "snippet",
            }
        ],
    )
    output = console.export_text()
    assert "repo_created_at" in output


def test_print_search_normalizes_multiline_snippet_text() -> None:
    """Search renderer should compact multiline snippet text to one line."""
    console = Console(record=True, width=120)
    print_search(
        console,
        [
            {
                "repo_id": "repo_multiline",
                "branch": "main",
                "created_at": "2026-01-01T00:00:00+00:00",
                "snippet": "line1\nline2   line3",
            }
        ],
    )
    output = console.export_text()
    assert "line1 line2 line3" in output


def test_print_search_uses_unknown_berth_when_identifiers_missing() -> None:
    """Search renderer should fallback to unknown berth when IDs missing."""
    console = Console(record=True, width=120)
    print_search(
        console,
        [
            {
                "branch": "main",
                "created_at": "2026-01-01T00:00:00+00:00",
                "snippet": "snippet",
            }
        ],
    )
    output = console.export_text()
    assert "(unknown)" in output


def test_print_search_uses_unknown_berth_when_identifier_values_none() -> None:
    """Search renderer should fallback to unknown berth for null IDs."""
    console = Console(record=True, width=120)
    print_search(
        console,
        [
            {
                "berth_name": None,
                "repo_id": None,
                "branch": "main",
                "created_at": "2026-01-01T00:00:00+00:00",
                "snippet": "snippet",
            }
        ],
    )
    output = console.export_text()
    assert "(unknown)" in output


def test_print_search_uses_repo_id_when_berth_name_is_blank() -> None:
    """Search renderer should fallback when berth_name is whitespace-only."""
    console = Console(record=True, width=120)
    print_search(
        console,
        [
            {
                "berth_name": "   ",
                "repo_id": "repo_from_id",
                "branch": "main",
                "created_at": "2026-01-01T00:00:00+00:00",
                "snippet": "snippet",
            }
        ],
    )
    output = console.export_text()
    assert "repo_from_id" in output


def test_print_harbor_renders_title_for_empty_rows() -> None:
    """Harbor renderer should still render a titled table when empty."""
    console = Console(record=True, width=120)
    print_harbor(console, [])
    output = console.export_text()
    assert "Dockyard Harbor" in output


def test_print_harbor_falls_back_to_raw_status_for_unknown_value() -> None:
    """Unknown status values should be rendered verbatim."""
    console = Console(record=True, width=120)
    print_harbor(
        console,
        [
            {
                "berth_name": "repo-x",
                "branch": "main",
                "status": "blue",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "next_steps": [],
                "objective": "obj",
                "open_review_count": 0,
            }
        ],
    )
    output = console.export_text()
    assert "blue" in output


def test_print_harbor_falls_back_to_repo_id_without_berth_name() -> None:
    """Harbor renderer should fallback to repo_id when berth name missing."""
    console = Console(record=True, width=120)
    print_harbor(
        console,
        [
            {
                "repo_id": "repo_harbor_fallback",
                "branch": "main",
                "status": "green",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "next_steps": [],
                "objective": "obj",
                "open_review_count": 0,
            }
        ],
    )
    output = console.export_text()
    assert "repo_harbor_fallback" in output


def test_print_harbor_uses_unknown_berth_when_identifiers_missing() -> None:
    """Harbor renderer should fallback to unknown berth when IDs missing."""
    console = Console(record=True, width=120)
    print_harbor(
        console,
        [
            {
                "branch": "main",
                "status": "green",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "next_steps": [],
                "objective": "obj",
                "open_review_count": 0,
            }
        ],
    )
    output = console.export_text()
    assert "(unknown)" in output


def test_print_harbor_uses_unknown_berth_when_identifier_values_none() -> None:
    """Harbor renderer should fallback to unknown berth for null IDs."""
    console = Console(record=True, width=120)
    print_harbor(
        console,
        [
            {
                "berth_name": None,
                "repo_id": None,
                "branch": "main",
                "status": "green",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "next_steps": [],
                "objective": "obj",
                "open_review_count": 0,
            }
        ],
    )
    output = console.export_text()
    assert "(unknown)" in output


def test_print_harbor_uses_repo_id_when_berth_name_is_blank() -> None:
    """Harbor renderer should fallback when berth_name is whitespace-only."""
    console = Console(record=True, width=120)
    print_harbor(
        console,
        [
            {
                "berth_name": "   ",
                "repo_id": "repo_from_id",
                "branch": "main",
                "status": "green",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "next_steps": [],
                "objective": "obj",
                "open_review_count": 0,
            }
        ],
    )
    output = console.export_text()
    assert "repo_from_id" in output


def test_print_harbor_handles_non_string_updated_at() -> None:
    """Harbor rendering should tolerate non-string updated_at values."""
    console = Console(record=True, width=120)
    print_harbor(
        console,
        [
            {
                "berth_name": "repo-y",
                "branch": "main",
                "status": "yellow",
                "updated_at": None,
                "next_steps": [],
                "objective": "obj",
                "open_review_count": 0,
            }
        ],
    )
    output = console.export_text()
    assert "unknown" in output


def test_print_harbor_handles_non_string_objective() -> None:
    """Harbor renderer should tolerate non-string objective payloads."""
    console = Console(record=True, width=120)
    print_harbor(
        console,
        [
            {
                "berth_name": "repo-z",
                "branch": "main",
                "status": "yellow",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "next_steps": [],
                "objective": 123,
                "open_review_count": 0,
            }
        ],
    )
    output = console.export_text()
    assert "123" in output


def test_print_harbor_handles_non_string_next_step_item() -> None:
    """Harbor renderer should tolerate non-string next-step entries."""
    console = Console(record=True, width=120)
    print_harbor(
        console,
        [
            {
                "berth_name": "repo-next-step",
                "branch": "main",
                "status": "yellow",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "next_steps": [42],
                "objective": "obj",
                "open_review_count": 0,
            }
        ],
    )
    output = console.export_text()
    assert "42" in output


def test_print_harbor_handles_string_next_steps_field() -> None:
    """Harbor renderer should tolerate next_steps payloads as raw strings."""
    console = Console(record=True, width=120)
    print_harbor(
        console,
        [
            {
                "berth_name": "repo-next-step-string",
                "branch": "main",
                "status": "yellow",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "next_steps": "single next step text",
                "objective": "obj",
                "open_review_count": 0,
            }
        ],
    )
    output = console.export_text()
    assert "single next step" in output
    assert "text" in output


def test_print_harbor_next_step_preview_is_single_line() -> None:
    """Harbor renderer should compact multiline next-step previews."""
    console = Console(record=True, width=120)
    print_harbor(
        console,
        [
            {
                "berth_name": "repo-next-step-multiline",
                "branch": "main",
                "status": "yellow",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "next_steps": ["line1\nline2   line3"],
                "objective": "obj",
                "open_review_count": 0,
            }
        ],
    )
    output = console.export_text()
    assert "line1 line2 line3" in output


def test_print_harbor_next_step_preview_is_bounded() -> None:
    """Harbor renderer should bound next-step preview length."""
    long_step = "x" * 120
    console = Console(record=True, width=120)
    print_harbor(
        console,
        [
            {
                "berth_name": "repo-next-step-long",
                "branch": "main",
                "status": "yellow",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "next_steps": [long_step],
                "objective": "obj",
                "open_review_count": 0,
            }
        ],
    )
    output = console.export_text()
    assert "x" * 70 not in output
