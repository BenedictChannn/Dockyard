"""Tests for checkpoint markdown render/parse round-trip behavior."""

from __future__ import annotations

from dockyard.models import Checkpoint, VerificationState
from dockyard.storage.markdown_store import parse_checkpoint_markdown, render_checkpoint_markdown


def test_markdown_round_trip_sections() -> None:
    """Rendered checkpoint markdown should be parseable for key sections."""
    checkpoint = Checkpoint(
        id="cp_round",
        repo_id="repo_a",
        branch="feature/roundtrip",
        created_at="2026-02-15T00:00:00+00:00",
        objective="Improve markdown parser reliability",
        decisions="Use lightweight parser for own template output.",
        next_steps=["Add round-trip test", "Wire parser utility"],
        risks_review="Low risk, parser constrained to known format",
        resume_commands=["pytest -q", "python3 -m dockyard ls"],
        git_dirty=True,
        head_sha="abc123",
        head_subject="subject",
        recent_commits=["abc subject"],
        diff_files_changed=2,
        diff_insertions=20,
        diff_deletions=5,
        touched_files=["dockyard/storage/markdown_store.py"],
        diff_stat_text="1 file changed, 20 insertions(+), 5 deletions(-)",
        verification=VerificationState(
            tests_run=True,
            tests_command="pytest -q",
            tests_timestamp="2026-02-15T00:00:00+00:00",
            build_ok=False,
            lint_ok=False,
            smoke_ok=False,
        ),
        tags=["mvp"],
    )
    markdown = render_checkpoint_markdown(checkpoint)
    parsed = parse_checkpoint_markdown(markdown)

    assert parsed["objective"] == checkpoint.objective
    assert parsed["decisions"] == checkpoint.decisions
    assert parsed["next_steps"] == checkpoint.next_steps
    assert parsed["risks_review"] == checkpoint.risks_review
    assert parsed["resume_commands"] == checkpoint.resume_commands


def test_markdown_parser_handles_empty_resume_commands() -> None:
    """Parser should return empty command list when section has no items."""
    checkpoint = Checkpoint(
        id="cp_empty_cmds",
        repo_id="repo_a",
        branch="main",
        created_at="2026-02-15T00:00:00+00:00",
        objective="Objective",
        decisions="Decisions",
        next_steps=["Single step"],
        risks_review="Risk notes",
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
        verification=VerificationState(),
        tags=[],
    )
    parsed = parse_checkpoint_markdown(render_checkpoint_markdown(checkpoint))
    assert parsed["resume_commands"] == []


def test_markdown_parser_ignores_blank_resume_command_bullets() -> None:
    """Parser should drop resume command bullets that normalize to empty strings."""
    markdown = """# Checkpoint
## Objective
Objective text
## Decisions/Findings
Decision text
## Next Steps
1. Keep moving
## Risks/Review Needed
None
## Resume Commands
- ``
- `   `
- `pytest -q`
- `  python3 -m dockyard ls  `
## Auto-captured Git Evidence
`git status --porcelain`: clean
`head`: abc (subject)
`recent commits`: (none)
`diff stat`: (no diff)
`touched files`: (none)
## Verification Status
- tests_run: false
- tests_command: none
- tests_timestamp: none
- build_ok: false
- lint_ok: false
- smoke_ok: false
"""
    parsed = parse_checkpoint_markdown(markdown)

    assert parsed["resume_commands"] == [
        "pytest -q",
        "python3 -m dockyard ls",
    ]


def test_markdown_parser_accepts_unquoted_resume_command_bullets() -> None:
    """Parser should accept plain bullet commands without backtick quoting."""
    markdown = """# Checkpoint
## Objective
Objective text
## Decisions/Findings
Decision text
## Next Steps
1. Keep moving
## Risks/Review Needed
None
## Resume Commands
- pytest -q
- python3 -m dockyard ls
* echo star-bullet
+ echo plus-bullet
-echo tight-bullet
*`echo tight-quoted-bullet`
1. echo numbered-bullet
2)echo numbered-tight
(3)echo numbered-paren
- `echo quoted`
## Auto-captured Git Evidence
`git status --porcelain`: clean
`head`: abc (subject)
`recent commits`: (none)
`diff stat`: (no diff)
`touched files`: (none)
## Verification Status
- tests_run: false
- tests_command: none
- tests_timestamp: none
- build_ok: false
- lint_ok: false
- smoke_ok: false
"""
    parsed = parse_checkpoint_markdown(markdown)

    assert parsed["resume_commands"] == [
        "pytest -q",
        "python3 -m dockyard ls",
        "echo star-bullet",
        "echo plus-bullet",
        "echo tight-bullet",
        "echo tight-quoted-bullet",
        "echo numbered-bullet",
        "echo numbered-tight",
        "echo numbered-paren",
        "echo quoted",
    ]


def test_markdown_parser_ignores_malformed_backtick_command_bullets() -> None:
    """Parser should ignore malformed backtick command bullets."""
    markdown = """# Checkpoint
## Objective
Objective text
## Decisions/Findings
Decision text
## Next Steps
1. Keep moving
## Risks/Review Needed
None
## Resume Commands
- `unterminated
- ``
- `   `
- echo valid-plain
- `echo valid-quoted`
## Auto-captured Git Evidence
`git status --porcelain`: clean
`head`: abc (subject)
`recent commits`: (none)
`diff stat`: (no diff)
`touched files`: (none)
## Verification Status
- tests_run: false
- tests_command: none
- tests_timestamp: none
- build_ok: false
- lint_ok: false
- smoke_ok: false
"""
    parsed = parse_checkpoint_markdown(markdown)

    assert parsed["resume_commands"] == [
        "echo valid-plain",
        "echo valid-quoted",
    ]


def test_markdown_parser_ignores_blank_next_step_items() -> None:
    """Parser should drop next-step items that normalize to empty strings."""
    markdown = """# Checkpoint
## Objective
Objective text
## Decisions/Findings
Decision text
## Next Steps
1.
2.   
3. Add integration coverage
4.   Tighten parser behavior
## Risks/Review Needed
None
## Resume Commands
- `pytest -q`
## Auto-captured Git Evidence
`git status --porcelain`: clean
`head`: abc (subject)
`recent commits`: (none)
`diff stat`: (no diff)
`touched files`: (none)
## Verification Status
- tests_run: false
- tests_command: none
- tests_timestamp: none
- build_ok: false
- lint_ok: false
- smoke_ok: false
"""
    parsed = parse_checkpoint_markdown(markdown)

    assert parsed["next_steps"] == [
        "Add integration coverage",
        "Tighten parser behavior",
    ]


def test_markdown_parser_accepts_parenthesized_numbered_next_steps() -> None:
    """Parser should support numbered next-step markers using `1)` format."""
    markdown = """# Checkpoint
## Objective
Objective text
## Decisions/Findings
Decision text
## Next Steps
1) First parenthesized step
2) Second parenthesized step
## Risks/Review Needed
None
## Resume Commands
- `pytest -q`
## Auto-captured Git Evidence
`git status --porcelain`: clean
`head`: abc (subject)
`recent commits`: (none)
`diff stat`: (no diff)
`touched files`: (none)
## Verification Status
- tests_run: false
- tests_command: none
- tests_timestamp: none
- build_ok: false
- lint_ok: false
- smoke_ok: false
"""
    parsed = parse_checkpoint_markdown(markdown)

    assert parsed["next_steps"] == [
        "First parenthesized step",
        "Second parenthesized step",
    ]


def test_markdown_parser_accepts_numbered_next_steps_without_space() -> None:
    """Parser should support numbered next-step markers without delimiter spacing."""
    markdown = """# Checkpoint
## Objective
Objective text
## Decisions/Findings
Decision text
## Next Steps
1)First compact step
2.Second compact step
(3)Third compact step
## Risks/Review Needed
None
## Resume Commands
- `pytest -q`
## Auto-captured Git Evidence
`git status --porcelain`: clean
`head`: abc (subject)
`recent commits`: (none)
`diff stat`: (no diff)
`touched files`: (none)
## Verification Status
- tests_run: false
- tests_command: none
- tests_timestamp: none
- build_ok: false
- lint_ok: false
- smoke_ok: false
"""
    parsed = parse_checkpoint_markdown(markdown)

    assert parsed["next_steps"] == [
        "First compact step",
        "Second compact step",
        "Third compact step",
    ]


def test_markdown_parser_accepts_bulleted_next_steps() -> None:
    """Parser should accept bulleted next-step markers from manual edits."""
    markdown = """# Checkpoint
## Objective
Objective text
## Decisions/Findings
Decision text
## Next Steps
- First bullet step
* Second bullet step
+ Third bullet step
-Fourth tight bullet step
*Fifth tight bullet step
## Risks/Review Needed
None
## Resume Commands
- `pytest -q`
## Auto-captured Git Evidence
`git status --porcelain`: clean
`head`: abc (subject)
`recent commits`: (none)
`diff stat`: (no diff)
`touched files`: (none)
## Verification Status
- tests_run: false
- tests_command: none
- tests_timestamp: none
- build_ok: false
- lint_ok: false
- smoke_ok: false
"""
    parsed = parse_checkpoint_markdown(markdown)

    assert parsed["next_steps"] == [
        "First bullet step",
        "Second bullet step",
        "Third bullet step",
        "Fourth tight bullet step",
        "Fifth tight bullet step",
    ]


def test_markdown_parser_preserves_unknown_headings_inside_sections() -> None:
    """Parser should keep unknown `##` headings within active section content."""
    markdown = """# Checkpoint
## Objective
Objective line one
## Internal objective note
Objective line two
## Decisions/Findings
Decision line one
## Internal decision note
Decision line two
## Next Steps
1. Keep moving
## Risks/Review Needed
None
## Resume Commands
- `pytest -q`
## Auto-captured Git Evidence
`git status --porcelain`: clean
`head`: abc (subject)
`recent commits`: (none)
`diff stat`: (no diff)
`touched files`: (none)
## Verification Status
- tests_run: false
- tests_command: none
- tests_timestamp: none
- build_ok: false
- lint_ok: false
- smoke_ok: false
"""
    parsed = parse_checkpoint_markdown(markdown)

    assert parsed["objective"] == "\n".join(
        [
            "Objective line one",
            "## Internal objective note",
            "Objective line two",
        ],
    )
    assert parsed["decisions"] == "\n".join(
        [
            "Decision line one",
            "## Internal decision note",
            "Decision line two",
        ],
    )


def test_markdown_parser_preserves_unknown_headings_inside_risks_section() -> None:
    """Parser should preserve unknown `##` lines within risks freeform text."""
    markdown = """# Checkpoint
## Objective
Objective text
## Decisions/Findings
Decision text
## Next Steps
1. Keep moving
## Risks/Review Needed
Primary risk line
## Internal risk note
Follow-up mitigation detail
## Resume Commands
- `pytest -q`
## Auto-captured Git Evidence
`git status --porcelain`: clean
`head`: abc (subject)
`recent commits`: (none)
`diff stat`: (no diff)
`touched files`: (none)
## Verification Status
- tests_run: false
- tests_command: none
- tests_timestamp: none
- build_ok: false
- lint_ok: false
- smoke_ok: false
"""
    parsed = parse_checkpoint_markdown(markdown)

    assert parsed["risks_review"] == "\n".join(
        [
            "Primary risk line",
            "## Internal risk note",
            "Follow-up mitigation detail",
        ],
    )
    assert parsed["resume_commands"] == ["pytest -q"]


def test_markdown_parser_normalizes_section_heading_spacing_variants() -> None:
    """Parser should accept section headings with varied spacing and slash styles."""
    markdown = """# Checkpoint
## Objective
Objective text
## Decisions / Findings
Decision text
## Next   Steps
1. Keep moving
## Risks / Review Needed
Risk text
## Resume   Commands
- `pytest -q`
## Auto-captured Git Evidence
`git status --porcelain`: clean
`head`: abc (subject)
`recent commits`: (none)
`diff stat`: (no diff)
`touched files`: (none)
## Verification Status
- tests_run: false
- tests_command: none
- tests_timestamp: none
- build_ok: false
- lint_ok: false
- smoke_ok: false
"""
    parsed = parse_checkpoint_markdown(markdown)

    assert parsed["objective"] == "Objective text"
    assert parsed["decisions"] == "Decision text"
    assert parsed["next_steps"] == ["Keep moving"]
    assert parsed["risks_review"] == "Risk text"
    assert parsed["resume_commands"] == ["pytest -q"]


def test_markdown_parser_accepts_case_insensitive_section_headings() -> None:
    """Parser should resolve known section headings regardless of case."""
    markdown = """# Checkpoint
## objective
Objective text
## DECISIONS / FINDINGS
Decision text
## nExT sTePs
1. Keep moving
## risks/review needed
Risk text
## RESUME COMMANDS
- `pytest -q`
## Auto-captured Git Evidence
`git status --porcelain`: clean
`head`: abc (subject)
`recent commits`: (none)
`diff stat`: (no diff)
`touched files`: (none)
## Verification Status
- tests_run: false
- tests_command: none
- tests_timestamp: none
- build_ok: false
- lint_ok: false
- smoke_ok: false
"""
    parsed = parse_checkpoint_markdown(markdown)

    assert parsed["objective"] == "Objective text"
    assert parsed["decisions"] == "Decision text"
    assert parsed["next_steps"] == ["Keep moving"]
    assert parsed["risks_review"] == "Risk text"
    assert parsed["resume_commands"] == ["pytest -q"]


def test_markdown_parser_accepts_trailing_colons_in_section_headings() -> None:
    """Parser should accept known section headings with trailing colon suffixes."""
    markdown = """# Checkpoint
## Objective:
Objective text
## Decisions/Findings:
Decision text
## Next Steps:
1. Keep moving
## Risks / Review Needed:
Risk text
## Resume Commands:
- `pytest -q`
## Auto-captured Git Evidence
`git status --porcelain`: clean
`head`: abc (subject)
`recent commits`: (none)
`diff stat`: (no diff)
`touched files`: (none)
## Verification Status
- tests_run: false
- tests_command: none
- tests_timestamp: none
- build_ok: false
- lint_ok: false
- smoke_ok: false
"""
    parsed = parse_checkpoint_markdown(markdown)

    assert parsed["objective"] == "Objective text"
    assert parsed["decisions"] == "Decision text"
    assert parsed["next_steps"] == ["Keep moving"]
    assert parsed["risks_review"] == "Risk text"
    assert parsed["resume_commands"] == ["pytest -q"]


def test_markdown_parser_accepts_closing_hashes_in_section_headings() -> None:
    """Parser should accept known section headings with trailing ATX hashes."""
    markdown = """# Checkpoint
## Objective ##
Objective text
## Decisions/Findings ##
Decision text
## Next Steps ##
1. Keep moving
## Risks / Review Needed ##
Risk text
## Resume Commands ##
- `pytest -q`
## Auto-captured Git Evidence
`git status --porcelain`: clean
`head`: abc (subject)
`recent commits`: (none)
`diff stat`: (no diff)
`touched files`: (none)
## Verification Status
- tests_run: false
- tests_command: none
- tests_timestamp: none
- build_ok: false
- lint_ok: false
- smoke_ok: false
"""
    parsed = parse_checkpoint_markdown(markdown)

    assert parsed["objective"] == "Objective text"
    assert parsed["decisions"] == "Decision text"
    assert parsed["next_steps"] == ["Keep moving"]
    assert parsed["risks_review"] == "Risk text"
    assert parsed["resume_commands"] == ["pytest -q"]


def test_markdown_parser_accepts_section_headings_without_space_after_hashes() -> None:
    """Parser should accept compact section headings like `##Objective##`."""
    markdown = """# Checkpoint
##Objective##
Objective text
##Decisions / Findings##
Decision text
##Next Steps##
1. Keep moving
##Risks/Review Needed##
Risk text
##Resume Commands##
- `pytest -q`
## Auto-captured Git Evidence
`git status --porcelain`: clean
`head`: abc (subject)
`recent commits`: (none)
`diff stat`: (no diff)
`touched files`: (none)
## Verification Status
- tests_run: false
- tests_command: none
- tests_timestamp: none
- build_ok: false
- lint_ok: false
- smoke_ok: false
"""
    parsed = parse_checkpoint_markdown(markdown)

    assert parsed["objective"] == "Objective text"
    assert parsed["decisions"] == "Decision text"
    assert parsed["next_steps"] == ["Keep moving"]
    assert parsed["risks_review"] == "Risk text"
    assert parsed["resume_commands"] == ["pytest -q"]


def test_markdown_parser_accepts_singular_section_heading_aliases() -> None:
    """Parser should accept singular heading aliases for known section labels."""
    markdown = """# Checkpoint
## Objective
Objective text
## Decision/Finding
Decision text
## Next Step
1. Keep moving
## Risk/Review Needed
Risk text
## Resume Command
- `pytest -q`
## Auto-captured Git Evidence
`git status --porcelain`: clean
`head`: abc (subject)
`recent commits`: (none)
`diff stat`: (no diff)
`touched files`: (none)
## Verification Status
- tests_run: false
- tests_command: none
- tests_timestamp: none
- build_ok: false
- lint_ok: false
- smoke_ok: false
"""
    parsed = parse_checkpoint_markdown(markdown)

    assert parsed["objective"] == "Objective text"
    assert parsed["decisions"] == "Decision text"
    assert parsed["next_steps"] == ["Keep moving"]
    assert parsed["risks_review"] == "Risk text"
    assert parsed["resume_commands"] == ["pytest -q"]


def test_markdown_parser_stops_list_section_capture_on_unknown_heading() -> None:
    """Unknown headings should terminate list sections to avoid entry leakage."""
    markdown = """# Checkpoint
## Objective
Objective text
## Decisions/Findings
Decision text
## Next Steps
1. Keep moving
## Internal next-step note
2. Should not be parsed
## Risks/Review Needed
Risk text
## Resume Commands
- `echo first`
## Internal command note
- `echo should-not-parse`
## Auto-captured Git Evidence
`git status --porcelain`: clean
`head`: abc (subject)
`recent commits`: (none)
`diff stat`: (no diff)
`touched files`: (none)
## Verification Status
- tests_run: false
- tests_command: none
- tests_timestamp: none
- build_ok: false
- lint_ok: false
- smoke_ok: false
"""
    parsed = parse_checkpoint_markdown(markdown)

    assert parsed["next_steps"] == ["Keep moving"]
    assert parsed["resume_commands"] == ["echo first"]


def test_markdown_parser_strips_checkbox_prefixes_from_next_steps() -> None:
    """Parser should strip markdown checklist prefixes from next-step entries."""
    markdown = """# Checkpoint
## Objective
Objective text
## Decisions/Findings
Decision text
## Next Steps
- [ ] First checklist step
* [x] Second checklist step
1. [X] Third checklist step
2. [x]literal-no-separator
3. [] Keep literal unmatched bracket token
## Risks/Review Needed
Risk text
## Resume Commands
- `pytest -q`
## Auto-captured Git Evidence
`git status --porcelain`: clean
`head`: abc (subject)
`recent commits`: (none)
`diff stat`: (no diff)
`touched files`: (none)
## Verification Status
- tests_run: false
- tests_command: none
- tests_timestamp: none
- build_ok: false
- lint_ok: false
- smoke_ok: false
"""
    parsed = parse_checkpoint_markdown(markdown)

    assert parsed["next_steps"] == [
        "First checklist step",
        "Second checklist step",
        "Third checklist step",
        "[x]literal-no-separator",
        "[] Keep literal unmatched bracket token",
    ]


def test_markdown_parser_strips_checklist_prefixes_from_resume_commands() -> None:
    """Parser should strip checklist prefixes from resume command entries."""
    markdown = """# Checkpoint
## Objective
Objective text
## Decisions/Findings
Decision text
## Next Steps
1. Keep moving
## Risks/Review Needed
Risk text
## Resume Commands
- [ ] pytest -q
* [x] python3 -m dockyard ls
1. [X] echo numbered
2) [x]echo-literal-no-separator
- `[x] echo quoted`
- `[x]echo quoted-literal-no-separator`
## Auto-captured Git Evidence
`git status --porcelain`: clean
`head`: abc (subject)
`recent commits`: (none)
`diff stat`: (no diff)
`touched files`: (none)
## Verification Status
- tests_run: false
- tests_command: none
- tests_timestamp: none
- build_ok: false
- lint_ok: false
- smoke_ok: false
"""
    parsed = parse_checkpoint_markdown(markdown)

    assert parsed["resume_commands"] == [
        "pytest -q",
        "python3 -m dockyard ls",
        "echo numbered",
        "[x]echo-literal-no-separator",
        "echo quoted",
        "[x]echo quoted-literal-no-separator",
    ]
