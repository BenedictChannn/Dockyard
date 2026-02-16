"""Unit tests for shared metadata helper utilities."""

from __future__ import annotations

from dataclasses import dataclass

from tests.metadata_utils import case_ids, pair_scope_cases_with_context, pair_with_context


@dataclass(frozen=True)
class _CaseMeta:
    """Simple case metadata fixture for utility tests."""

    case_id: str
    label: str


@dataclass(frozen=True)
class _ScopeCaseMeta:
    """Simple scope-case metadata fixture for utility tests."""

    case_id: str
    command_name: str
    include_berth: bool
    include_branch: bool


def test_case_ids_returns_case_id_order() -> None:
    """case_ids should preserve input ordering."""
    cases = (
        _CaseMeta(case_id="case_a", label="alpha"),
        _CaseMeta(case_id="case_b", label="beta"),
        _CaseMeta(case_id="case_c", label="gamma"),
    )

    assert case_ids(cases) == ("case_a", "case_b", "case_c")


def test_pair_with_context_renders_context_for_each_case() -> None:
    """pair_with_context should pair every case with built context."""
    cases = (
        _CaseMeta(case_id="case_a", label="alpha"),
        _CaseMeta(case_id="case_b", label="beta"),
    )

    paired = pair_with_context(
        cases,
        context_builder=lambda case: f"context::{case.label}",
    )

    assert paired == (
        (cases[0], "context::alpha"),
        (cases[1], "context::beta"),
    )


def test_case_ids_returns_empty_tuple_for_empty_input() -> None:
    """case_ids should return an empty tuple for empty case collections."""
    assert case_ids(()) == ()


def test_pair_with_context_preserves_order_for_empty_and_non_empty() -> None:
    """pair_with_context should preserve case ordering in output pairs."""
    empty_pairs = pair_with_context((), context_builder=lambda _: "unused")
    assert empty_pairs == ()

    cases = (
        _CaseMeta(case_id="case_z", label="zeta"),
        _CaseMeta(case_id="case_a", label="alpha"),
    )
    paired = pair_with_context(cases, context_builder=lambda case: case.label.upper())
    assert paired == (
        (cases[0], "ZETA"),
        (cases[1], "ALPHA"),
    )


def test_pair_with_context_does_not_call_builder_for_empty_input() -> None:
    """Empty input should skip context builder invocation."""
    call_count = 0

    def _builder(_case: _CaseMeta) -> str:
        nonlocal call_count
        call_count += 1
        return "unused"

    assert pair_with_context((), context_builder=_builder) == ()
    assert call_count == 0


def test_pair_scope_cases_with_context_uses_scope_fields() -> None:
    """pair_scope_cases_with_context should pass command and scope flags."""
    cases = (
        _ScopeCaseMeta(case_id="a", command_name="resume", include_berth=False, include_branch=True),
        _ScopeCaseMeta(case_id="b", command_name="undock", include_berth=True, include_branch=False),
    )

    paired = pair_scope_cases_with_context(
        cases,
        context_builder=lambda command_name, include_berth, include_branch: (
            f"{command_name}:{include_berth}:{include_branch}"
        ),
    )

    assert paired == (
        (cases[0], "resume:False:True"),
        (cases[1], "undock:True:False"),
    )


def test_pair_scope_cases_with_context_returns_empty_tuple_for_empty_input() -> None:
    """pair_scope_cases_with_context should return empty tuple for empty input."""
    assert pair_scope_cases_with_context((), context_builder=lambda *_: "unused") == ()


def test_pair_scope_cases_with_context_does_not_call_builder_for_empty_input() -> None:
    """Empty scope-case input should not invoke context builder."""
    call_count = 0

    def _builder(*_args: object) -> str:
        nonlocal call_count
        call_count += 1
        return "unused"

    assert pair_scope_cases_with_context((), context_builder=_builder) == ()
    assert call_count == 0
