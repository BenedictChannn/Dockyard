"""Unit tests for shared metadata helper utilities."""

from __future__ import annotations

from dataclasses import dataclass

from tests.metadata_utils import case_ids, pair_with_context


@dataclass(frozen=True)
class _CaseMeta:
    """Simple case metadata fixture for utility tests."""

    case_id: str
    label: str


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
