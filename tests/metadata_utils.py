"""Shared metadata helpers for scenario-driven test parametrization."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol, TypeVar

CaseT = TypeVar("CaseT")
ContextT = TypeVar("ContextT")


class SupportsCaseId(Protocol):
    """Protocol for metadata records that include pytest case IDs."""

    case_id: str


def case_ids(cases: Sequence[SupportsCaseId]) -> tuple[str, ...]:
    """Return pytest ID labels from case metadata entries."""
    return tuple(case.case_id for case in cases)


def pair_with_context(
    cases: Sequence[CaseT],
    *,
    context_builder: Callable[[CaseT], ContextT],
) -> tuple[tuple[CaseT, ContextT], ...]:
    """Pair each case with its derived context metadata."""
    return tuple((case, context_builder(case)) for case in cases)
