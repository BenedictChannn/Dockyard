"""Unit tests for CLI helper normalization logic."""

from __future__ import annotations

import json

import pytest

import dockyard.cli as cli_module
from dockyard.cli import (
    _coerce_text_items,
    _comma_or_pipe_values,
    _emit_json,
    _normalize_editor_text,
    _normalize_optional_text,
    _safe_preview,
    _safe_text,
)


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


def test_normalize_editor_text_preserves_non_scaffold_hash_lines() -> None:
    """Non-scaffold hash-prefixed lines should remain in normalized text."""
    raw = "# Decisions / Findings\n# Keep heading\nDecision body"
    assert _normalize_editor_text(raw) == "# Keep heading\nDecision body"


def test_normalize_editor_text_trims_outer_blank_lines() -> None:
    """Leading and trailing blank lines should be dropped."""
    raw = "# Decisions / Findings\n\n\nCore line\n\n"
    assert _normalize_editor_text(raw) == "Core line"


def test_normalize_editor_text_returns_empty_for_scaffold_only() -> None:
    """Scaffold-only editor content should normalize to empty text."""
    raw = " # Decisions / Findings \n\n"
    assert _normalize_editor_text(raw) == ""


def test_normalize_editor_text_drops_multiple_scaffold_lines() -> None:
    """Repeated scaffold lines should all be removed."""
    raw = "# Decisions / Findings\n# Decisions / Findings\nDecision body"
    assert _normalize_editor_text(raw) == "Decision body"


def test_normalize_editor_text_handles_windows_newlines() -> None:
    """Normalization should work with CRLF editor payloads."""
    raw = "# Decisions / Findings\r\n\r\nDecision body\r\n"
    assert _normalize_editor_text(raw) == "Decision body"


def test_normalize_editor_text_empty_input_returns_empty() -> None:
    """Empty editor payload should normalize to empty string."""
    assert _normalize_editor_text("") == ""


def test_comma_or_pipe_values_supports_commas() -> None:
    """Comma-separated input should parse into stripped values."""
    assert _comma_or_pipe_values("alpha, beta , ,gamma") == ["alpha", "beta", "gamma"]


def test_comma_or_pipe_values_prioritizes_pipe_separator() -> None:
    """Pipe-separated input should parse as pipe-delimited when present."""
    assert _comma_or_pipe_values("alpha| beta |gamma") == ["alpha", "beta", "gamma"]


def test_comma_or_pipe_values_empty_input_returns_empty_list() -> None:
    """Empty helper input should normalize to an empty list."""
    assert _comma_or_pipe_values("   ") == []


def test_comma_or_pipe_values_with_mixed_separators_prefers_pipe() -> None:
    """Presence of pipe should disable comma splitting semantics."""
    assert _comma_or_pipe_values("alpha,beta|gamma") == ["alpha,beta", "gamma"]


def test_comma_or_pipe_values_drops_empty_pipe_segments() -> None:
    """Pipe parsing should ignore empty segments after trimming."""
    assert _comma_or_pipe_values("alpha|| beta | ") == ["alpha", "beta"]


def test_comma_or_pipe_values_preserves_internal_spaces() -> None:
    """Parsing should not alter interior whitespace inside a value token."""
    assert _comma_or_pipe_values("alpha value|beta value") == ["alpha value", "beta value"]


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
    assert captured[0].startswith("{\n  ")


def test_emit_json_handles_list_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """JSON emitter should support list payloads for empty-state outputs."""
    captured: list[str] = []

    def _fake_echo(message: str) -> None:
        captured.append(message)

    monkeypatch.setattr(cli_module.typer, "echo", _fake_echo)
    _emit_json([])

    assert captured == ["[]"]
    assert "\x1b[" not in captured[0]


def test_emit_json_list_payload_preserves_unicode(monkeypatch: pytest.MonkeyPatch) -> None:
    """List payload emission should keep unicode characters unescaped."""
    captured: list[str] = []

    def _fake_echo(message: str) -> None:
        captured.append(message)

    monkeypatch.setattr(cli_module.typer, "echo", _fake_echo)
    _emit_json(["façade"])

    assert len(captured) == 1
    assert "\\u00e7" not in captured[0]
    assert json.loads(captured[0]) == ["façade"]


def test_emit_json_list_payload_is_pretty_indented(monkeypatch: pytest.MonkeyPatch) -> None:
    """List payload emission should keep readable pretty indentation."""
    captured: list[str] = []

    def _fake_echo(message: str) -> None:
        captured.append(message)

    monkeypatch.setattr(cli_module.typer, "echo", _fake_echo)
    _emit_json(["alpha", "beta"])

    assert len(captured) == 1
    assert captured[0].startswith("[\n  ")


def test_safe_text_escapes_markup_tokens() -> None:
    """Safe text helper should escape Rich markup delimiters."""
    escaped = _safe_text("[red]literal[/red]")
    assert escaped == "\\[red]literal\\[/red]"


def test_safe_text_handles_non_string_values() -> None:
    """Safe text helper should coerce and escape non-string values safely."""
    escaped = _safe_text(123)
    assert escaped == "123"


def test_safe_preview_compacts_multiline_text() -> None:
    """Safe preview helper should compact multiline text into one line."""
    preview = _safe_preview("line1\nline2\tline3")
    assert preview == "line1 line2 line3"


def test_safe_preview_applies_length_bound() -> None:
    """Safe preview helper should enforce max-length truncation."""
    preview = _safe_preview("x" * 20, max_length=10)
    assert preview == "x" * 10


def test_safe_preview_escapes_markup_tokens() -> None:
    """Safe preview helper should escape literal markup delimiters."""
    preview = _safe_preview("[red]literal[/red]")
    assert preview == "\\[red]literal\\[/red]"


def test_safe_preview_uses_fallback_for_blank_values() -> None:
    """Safe preview helper should return fallback when compact text is blank."""
    preview = _safe_preview("   ", fallback="(unknown)")
    assert preview == "(unknown)"


def test_coerce_text_items_handles_scalar_and_filters_blank_values() -> None:
    """Coercion helper should normalize scalar values and drop blanks."""
    assert _coerce_text_items("single") == ["single"]
    assert _coerce_text_items("   ") == []


def test_coerce_text_items_handles_mixed_iterables() -> None:
    """Coercion helper should coerce iterable items and skip blank entries."""
    values = ["alpha", 42, "   ", None]
    assert _coerce_text_items(values) == ["alpha", "42"]


def test_normalize_optional_text_trims_non_blank_values() -> None:
    """Optional text normalizer should trim surrounding whitespace."""
    assert _normalize_optional_text("  keep me  ") == "keep me"


def test_normalize_optional_text_returns_none_for_blank_input() -> None:
    """Optional text normalizer should collapse blank values to None."""
    assert _normalize_optional_text("   ") is None
    assert _normalize_optional_text(None) is None
