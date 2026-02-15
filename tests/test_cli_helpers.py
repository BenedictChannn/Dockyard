"""Unit tests for CLI helper normalization logic."""

from __future__ import annotations

import json

import pytest

import dockyard.cli as cli_module
from dockyard.cli import _comma_or_pipe_values, _emit_json, _normalize_editor_text


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


def test_comma_or_pipe_values_supports_commas() -> None:
    """Comma-separated input should parse into stripped values."""
    assert _comma_or_pipe_values("alpha, beta , ,gamma") == ["alpha", "beta", "gamma"]


def test_comma_or_pipe_values_prioritizes_pipe_separator() -> None:
    """Pipe-separated input should parse as pipe-delimited when present."""
    assert _comma_or_pipe_values("alpha| beta |gamma") == ["alpha", "beta", "gamma"]


def test_comma_or_pipe_values_empty_input_returns_empty_list() -> None:
    """Empty helper input should normalize to an empty list."""
    assert _comma_or_pipe_values("   ") == []


def test_emit_json_uses_unicode_friendly_plain_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """JSON emitter should output parseable text without unicode escaping."""
    captured: list[str] = []

    def _fake_echo(message: str) -> None:
        captured.append(message)

    monkeypatch.setattr(cli_module.typer, "echo", _fake_echo)
    _emit_json({"text": "façade"})

    assert len(captured) == 1
    assert "\x1b[" not in captured[0]
    assert "\\u00e7" not in captured[0]
    assert json.loads(captured[0])["text"] == "façade"
