"""Shared metadata helpers for scenario-driven test parametrization."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class SupportsCaseId(Protocol):
    """Protocol for metadata records that include pytest case IDs."""

    case_id: str


def case_ids(cases: Sequence[SupportsCaseId]) -> tuple[str, ...]:
    """Return pytest ID labels from case metadata entries."""
    return tuple(case.case_id for case in cases)
