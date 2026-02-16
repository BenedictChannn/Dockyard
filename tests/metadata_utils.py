"""Shared metadata helpers for scenario-driven test parametrization."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Protocol, TypeVar

CaseT = TypeVar("CaseT")
ContextT = TypeVar("ContextT")
ScopeCaseT = TypeVar("ScopeCaseT", bound="SupportsRunScopeCase")


class SupportsCaseId(Protocol):
    """Protocol for metadata records that include pytest case IDs."""

    case_id: str


class SupportsRunScopeCase(Protocol):
    """Protocol for scope-aware metadata with command + flags."""

    command_name: Any
    include_berth: bool
    include_branch: bool


def case_ids(cases: Sequence[SupportsCaseId]) -> tuple[str, ...]:
    """Return pytest ID labels from case metadata entries.

    Args:
        cases: Metadata entries exposing a ``case_id`` attribute.

    Returns:
        Tuple of case IDs preserving input ordering.
    """
    return tuple(case.case_id for case in cases)


def pair_with_context(
    cases: Sequence[CaseT],
    *,
    context_builder: Callable[[CaseT], ContextT],
) -> tuple[tuple[CaseT, ContextT], ...]:
    """Pair each case with its derived context metadata.

    Args:
        cases: Source case metadata entries.
        context_builder: Callable that renders context metadata for each case.

    Returns:
        Tuples containing the original case and its derived context.
    """
    return tuple((case, context_builder(case)) for case in cases)


def pair_scope_cases_with_context(
    cases: Sequence[ScopeCaseT],
    *,
    context_builder: Callable[[Any, bool, bool], ContextT],
) -> tuple[tuple[ScopeCaseT, ContextT], ...]:
    """Pair each scope case with context derived from command/scope flags.

    Args:
        cases: Scope-aware case metadata entries.
        context_builder: Callable receiving ``(command_name, include_berth,
            include_branch)`` and returning context metadata.

    Returns:
        Tuples containing the original scope case and derived context metadata.
    """
    return pair_with_context(
        cases,
        context_builder=lambda case: context_builder(
            case.command_name,
            case.include_berth,
            case.include_branch,
        ),
    )
