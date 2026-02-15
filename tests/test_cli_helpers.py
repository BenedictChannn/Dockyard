"""Unit tests for CLI helper normalization logic."""

from __future__ import annotations

from dockyard.cli import _normalize_editor_text


def test_normalize_editor_text_drops_scaffold_line() -> None:
    """Scaffold comment line should be removed from editor payload."""
    raw = "# Decisions / Findings\nShip search improvements"
    assert _normalize_editor_text(raw) == "Ship search improvements"


def test_normalize_editor_text_handles_indented_scaffold_line() -> None:
    """Whitespace-indented scaffold comment should also be removed."""
    raw = "   # Decisions / Findings\nShip search improvements"
    assert _normalize_editor_text(raw) == "Ship search improvements"


def test_normalize_editor_text_preserves_internal_blank_lines() -> None:
    """Intentional paragraph spacing should remain in normalized text."""
    raw = "# Decisions / Findings\n\nFirst paragraph\n\nSecond paragraph\n"
    assert _normalize_editor_text(raw) == "First paragraph\n\nSecond paragraph"


def test_normalize_editor_text_trims_outer_blank_lines() -> None:
    """Leading and trailing blank lines should be dropped."""
    raw = "# Decisions / Findings\n\n\nCore line\n\n"
    assert _normalize_editor_text(raw) == "Core line"
