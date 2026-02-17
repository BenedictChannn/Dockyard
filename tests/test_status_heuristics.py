"""Tests for status and review heuristic rules."""

from __future__ import annotations

from dockyard.config import ReviewHeuristicsConfig
from dockyard.models import Checkpoint, VerificationState
from dockyard.services.reviews import review_triggers
from dockyard.services.status import compute_slip_status


def _checkpoint(**overrides) -> Checkpoint:
    """Build a minimal checkpoint model for heuristic testing."""
    checkpoint = Checkpoint(
        id="cp_x",
        repo_id="repo",
        branch="feature/test",
        created_at="2026-01-01T00:00:00+00:00",
        objective="obj",
        decisions="decisions",
        next_steps=["next"],
        risks_review="risk",
        resume_commands=[],
        git_dirty=True,
        head_sha="abc",
        head_subject="subj",
        recent_commits=["abc subj"],
        diff_files_changed=1,
        diff_insertions=10,
        diff_deletions=5,
        touched_files=["src/app.py"],
        diff_stat_text="1 file changed",
        verification=VerificationState(
            tests_run=False,
            build_ok=False,
            lint_ok=False,
            smoke_ok=False,
        ),
        tags=[],
    )
    for key, value in overrides.items():
        setattr(checkpoint, key, value)
    return checkpoint


def test_status_green_requires_tests_build_and_no_high_reviews() -> None:
    """Green status requires strong verification and no serious review debt."""
    cp = _checkpoint(
        verification=VerificationState(tests_run=True, build_ok=True, lint_ok=False, smoke_ok=False)
    )
    assert compute_slip_status(cp, open_review_count=0, has_high_open_review=False) == "green"


def test_status_red_for_high_severity_open_review() -> None:
    """High-severity open review should force red state."""
    cp = _checkpoint(verification=VerificationState(tests_run=True, build_ok=True))
    assert compute_slip_status(cp, open_review_count=1, has_high_open_review=True) == "red"


def test_status_red_for_large_diff_without_review() -> None:
    """Large diffs with no review debt coverage should be red."""
    cp = _checkpoint(
        diff_files_changed=16,
        diff_insertions=250,
        diff_deletions=200,
        verification=VerificationState(tests_run=True, build_ok=True),
    )
    assert compute_slip_status(cp, open_review_count=0, has_high_open_review=False) == "red"


def test_status_red_for_risky_paths_without_tests_even_with_open_reviews() -> None:
    """Risky paths without tests should stay red regardless of review count."""
    cp = _checkpoint(
        touched_files=["security/token.py"],
        verification=VerificationState(tests_run=False, build_ok=True),
    )
    assert compute_slip_status(cp, open_review_count=2, has_high_open_review=False) == "red"


def test_status_yellow_for_large_diff_when_open_review_exists() -> None:
    """Large diffs with open non-high reviews should remain yellow."""
    cp = _checkpoint(
        diff_files_changed=20,
        diff_insertions=300,
        diff_deletions=200,
        verification=VerificationState(tests_run=True, build_ok=True),
    )
    assert compute_slip_status(cp, open_review_count=1, has_high_open_review=False) == "yellow"


def test_status_red_at_large_diff_file_threshold_boundary_without_review() -> None:
    """File-count large-diff threshold should trigger red at 15 files."""
    cp = _checkpoint(
        diff_files_changed=15,
        diff_insertions=10,
        diff_deletions=5,
        verification=VerificationState(tests_run=True, build_ok=True),
    )
    assert compute_slip_status(cp, open_review_count=0, has_high_open_review=False) == "red"


def test_status_red_at_large_diff_churn_threshold_boundary_without_review() -> None:
    """Churn large-diff threshold should trigger red at 400 changes."""
    cp = _checkpoint(
        diff_files_changed=5,
        diff_insertions=250,
        diff_deletions=150,
        verification=VerificationState(tests_run=True, build_ok=True),
    )
    assert compute_slip_status(cp, open_review_count=0, has_high_open_review=False) == "red"


def test_status_green_just_below_large_diff_thresholds_with_verification() -> None:
    """Sub-threshold diffs with verification and no reviews should be green."""
    cp = _checkpoint(
        diff_files_changed=14,
        diff_insertions=200,
        diff_deletions=199,
        touched_files=["src/app.py"],
        verification=VerificationState(tests_run=True, build_ok=True),
    )
    assert compute_slip_status(cp, open_review_count=0, has_high_open_review=False) == "green"


def test_status_yellow_when_low_review_open_with_good_verification() -> None:
    """Open low/med review items should keep status yellow."""
    cp = _checkpoint(
        verification=VerificationState(tests_run=True, build_ok=True),
    )
    assert compute_slip_status(cp, open_review_count=1, has_high_open_review=False) == "yellow"


def test_review_triggers_detect_risky_paths_and_large_diff() -> None:
    """Review triggers should activate for risky paths and large churn."""
    cp = _checkpoint(
        touched_files=["security/token.py", "infra/deploy.tf"],
        diff_files_changed=20,
        diff_insertions=300,
        diff_deletions=200,
    )
    triggers = review_triggers(cp)
    assert "risky_paths_touched" in triggers
    assert "many_files_changed" in triggers
    assert "large_diff_churn" in triggers


def test_review_triggers_include_missing_tests_for_non_trivial_diff() -> None:
    """Non-trivial diffs without tests should create missing-tests trigger."""
    cp = _checkpoint(
        diff_files_changed=4,
        diff_insertions=10,
        diff_deletions=2,
        verification=VerificationState(tests_run=False, build_ok=False, lint_ok=False, smoke_ok=False),
    )
    triggers = review_triggers(cp)
    assert "missing_tests_non_trivial_diff" in triggers


def test_review_triggers_include_release_hotfix_branch_default() -> None:
    """Release/hotfix branch naming should trigger review suggestion."""
    cp = _checkpoint(branch="release/2026.02", verification=VerificationState())
    triggers = review_triggers(cp)
    assert "release_or_hotfix_branch" in triggers


def test_review_triggers_honor_custom_config_thresholds() -> None:
    """Review trigger logic should use provided configuration overrides."""
    cp = _checkpoint(
        branch="urgent/security-fix",
        touched_files=["critical/module.py"],
        diff_files_changed=2,
        diff_insertions=30,
        diff_deletions=10,
    )
    config = ReviewHeuristicsConfig(
        risky_path_patterns=[r"(^|/)critical/"],
        files_changed_threshold=2,
        churn_threshold=35,
        non_trivial_files_threshold=1,
        non_trivial_churn_threshold=10,
        branch_prefixes=["urgent/"],
    )
    triggers = review_triggers(cp, heuristics=config)
    assert "risky_paths_touched" in triggers
    assert "many_files_changed" in triggers
    assert "large_diff_churn" in triggers
    assert "release_or_hotfix_branch" in triggers
