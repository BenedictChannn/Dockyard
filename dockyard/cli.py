"""Typer CLI entrypoint for Dockyard."""

from __future__ import annotations

import json
import tomllib
import uuid
from pathlib import Path
from typing import Any

import click
import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel

from dockyard.config import load_runtime_config, resolve_paths
from dockyard.errors import DockyardError, NotGitRepositoryError
from dockyard.git_info import inspect_repository
from dockyard.models import (
    LinkItem,
    ReviewItem,
    SaveInput,
    VerificationState,
    checkpoint_to_jsonable,
    utc_now_iso,
)
from dockyard.runner import run_commands
from dockyard.services.checkpoints import create_checkpoint
from dockyard.services.search import search as search_service
from dockyard.storage.sqlite_store import SQLiteStore
from dockyard.ui.render import print_harbor, print_resume, print_search

app = typer.Typer(
    help="Dockyard: local-first context and resume CLI.",
    invoke_without_command=True,
    add_completion=False,
)
review_app = typer.Typer(help="Review queue commands.", invoke_without_command=True)
app.add_typer(review_app, name="review")
console = Console()
VALID_REVIEW_SEVERITIES = {"low", "med", "high"}


def _store() -> tuple[SQLiteStore, Path]:
    """Return initialized SQLite store and base directory."""
    paths = resolve_paths()
    store = SQLiteStore(paths.db_path)
    store.initialize()
    return store, Path(paths.base_dir)


def _comma_or_pipe_values(raw: str) -> list[str]:
    """Parse comma- or pipe-separated input into stripped values.

    If the text contains a pipe (`|`), pipe separation is used for the full
    string so commas can be preserved inside values.
    """
    if "|" in raw:
        parts = raw.split("|")
    else:
        parts = raw.split(",")
    return [part.strip() for part in parts if part.strip()]


def _emit_json(payload: Any) -> None:
    """Emit machine-readable JSON without Rich wrapping effects."""
    typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))


def _safe_text(value: Any) -> str:
    """Escape Rich markup tokens in user-visible text values."""
    return escape(str(value))


def _normalize_editor_text(raw: str) -> str:
    """Normalize editor text by dropping scaffold comments and outer blanks.

    Args:
        raw: Raw text returned by click editor integration.

    Returns:
        Cleaned text content suitable for persistence, with intentional
        internal blank lines preserved.
    """
    normalized_lines: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped == "# Decisions / Findings":
            continue
        normalized_lines.append(line.rstrip())

    while normalized_lines and not normalized_lines[0].strip():
        normalized_lines.pop(0)
    while normalized_lines and not normalized_lines[-1].strip():
        normalized_lines.pop()

    return "\n".join(normalized_lines)


def _verification_from_inputs(
    no_prompt: bool,
    tests_run: bool | None,
    tests_command: str | None,
    build_ok: bool | None,
    build_command: str | None,
    lint_ok: bool | None,
    lint_command: str | None,
    smoke_ok: bool | None,
    smoke_notes: str | None,
) -> VerificationState:
    """Collect verification state from flags and optional prompts."""
    now = utc_now_iso()

    if not no_prompt and tests_run is None:
        tests_run = typer.confirm("Were tests run?", default=False)
        if tests_run and not tests_command:
            tests_command = typer.prompt("Tests command", default="")
    if not no_prompt and build_ok is None:
        build_ok = typer.confirm("Was build successful?", default=False)
        if build_ok and not build_command:
            build_command = typer.prompt("Build command", default="")
    if not no_prompt and lint_ok is None:
        lint_ok = typer.confirm("Was lint successful?", default=False)
        if lint_ok and not lint_command:
            lint_command = typer.prompt("Lint command", default="")
    if not no_prompt and smoke_ok is None:
        smoke_ok = typer.confirm("Runtime smoke check done?", default=False)
        if smoke_ok and not smoke_notes:
            smoke_notes = typer.prompt("Smoke notes", default="")

    tests_run = bool(tests_run)
    build_ok = bool(build_ok)
    lint_ok = bool(lint_ok)
    smoke_ok = bool(smoke_ok)
    return VerificationState(
        tests_run=tests_run,
        tests_command=tests_command if tests_run else None,
        tests_timestamp=now if tests_run else None,
        build_ok=build_ok,
        build_command=build_command if build_ok else None,
        build_timestamp=now if build_ok else None,
        lint_ok=lint_ok,
        lint_command=lint_command if lint_ok else None,
        lint_timestamp=now if lint_ok else None,
        smoke_ok=smoke_ok,
        smoke_notes=smoke_notes if smoke_ok else None,
        smoke_timestamp=now if smoke_ok else None,
    )


def _load_template_data(template_path: str | None) -> dict:
    """Load save template data from JSON or TOML file.

    Args:
        template_path: Optional template file path.

    Returns:
        Parsed dictionary from template file, or empty dictionary if omitted.

    Raises:
        DockyardError: If file is unreadable or extension unsupported.
    """
    if not template_path:
        return {}
    path = Path(template_path).expanduser().resolve()
    if not path.exists():
        raise DockyardError(f"Template not found: {path}")

    raw = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    try:
        parsed: dict[str, Any]
        if suffix == ".json":
            parsed = json.loads(raw)
            return _validate_template_data(parsed, path=path)
        if suffix in {".toml", ".tml"}:
            parsed = tomllib.loads(raw)
            return _validate_template_data(parsed, path=path)
    except (json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
        raise DockyardError(f"Failed to parse template: {path}") from exc
    raise DockyardError("Template must be .json or .toml")


def _template_or_default(template: dict, key: str, fallback):
    """Return template value by key, otherwise fallback value."""
    return template.get(key, fallback)


def _validate_template_data(parsed: Any, path: Path) -> dict[str, Any]:
    """Validate save template schema and return normalized dictionary.

    Args:
        parsed: Parsed template payload.
        path: Template file path (for actionable errors).

    Returns:
        Validated template mapping.

    Raises:
        DockyardError: If template shape/types are invalid.
    """
    if not isinstance(parsed, dict):
        raise DockyardError(f"Template must contain an object/table: {path}")

    _ensure_optional_str(parsed, "objective", path)
    _ensure_optional_str(parsed, "decisions", path)
    _ensure_optional_str(parsed, "risks_review", path)
    _ensure_optional_list_of_str(parsed, "next_steps", path)
    _ensure_optional_list_of_str(parsed, "resume_commands", path)
    _ensure_optional_list_of_str(parsed, "tags", path)
    _ensure_optional_list_of_str(parsed, "links", path)

    verification = parsed.get("verification")
    if verification is not None:
        if not isinstance(verification, dict):
            raise DockyardError(f"Template field 'verification' must be a table/object: {path}")
        _ensure_optional_bool_like(verification, "tests_run", path)
        _ensure_optional_bool_like(verification, "build_ok", path)
        _ensure_optional_bool_like(verification, "lint_ok", path)
        _ensure_optional_bool_like(verification, "smoke_ok", path)
        _ensure_optional_str(verification, "tests_command", path)
        _ensure_optional_str(verification, "build_command", path)
        _ensure_optional_str(verification, "lint_command", path)
        _ensure_optional_str(verification, "smoke_notes", path)
    return parsed


def _ensure_optional_str(mapping: dict[str, Any], key: str, path: Path) -> None:
    """Validate optional string field from a mapping."""
    value = mapping.get(key)
    if value is not None and not isinstance(value, str):
        raise DockyardError(f"Template field '{key}' must be a string: {path}")


def _ensure_optional_list_of_str(mapping: dict[str, Any], key: str, path: Path) -> None:
    """Validate optional list-of-string field from a mapping."""
    value = mapping.get(key)
    if value is None:
        return
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise DockyardError(f"Template field '{key}' must be an array of strings: {path}")


def _ensure_optional_bool_like(mapping: dict[str, Any], key: str, path: Path) -> None:
    """Validate optional bool-like field accepted by bool coercion."""
    value = mapping.get(key)
    if value is None:
        return
    if _coerce_optional_bool(value) is None:
        raise DockyardError(
            f"Template field '{key}' must be bool or bool-like string: {path}"
        )


def _coerce_optional_bool(value) -> bool | None:
    """Coerce optional bool-like value from templates.

    Args:
        value: Raw template value.

    Returns:
        Parsed boolean value or None when unsupported.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y"}:
            return True
        if lowered in {"0", "false", "no", "n"}:
            return False
    return None


def _validate_review_severity(raw: str) -> str:
    """Validate review severity option value.

    Args:
        raw: Raw severity string provided by user.

    Returns:
        Normalized lower-case severity value.

    Raises:
        DockyardError: If severity is not one of low/med/high.
    """
    normalized = raw.strip().lower()
    if normalized not in VALID_REVIEW_SEVERITIES:
        allowed = ", ".join(sorted(VALID_REVIEW_SEVERITIES))
        raise DockyardError(f"Invalid severity '{raw}'. Use one of: {allowed}.")
    return normalized


def _require_minimum_int(value: int | None, minimum: int, field_name: str) -> int | None:
    """Validate optional integer threshold/limit arguments.

    Args:
        value: Optional integer value.
        minimum: Inclusive minimum allowed value.
        field_name: Human-readable field identifier for error messages.

    Returns:
        Original value when valid, else None.

    Raises:
        typer.BadParameter: If value is below minimum.
    """
    if value is None:
        return None
    if value < minimum:
        raise typer.BadParameter(f"{field_name} must be >= {minimum}.")
    return value


def _resolve_repo_context(
    root: str | None = None,
    require_git: bool = True,
):
    """Resolve git snapshot for current context."""
    try:
        return inspect_repository(root_override=root)
    except NotGitRepositoryError:
        if require_git:
            raise
        return None


@app.callback()
def root_callback(ctx: typer.Context) -> None:
    """Default to `dock ls` when no explicit subcommand is provided."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(ls_command, stale=None, tag=None, limit=None, as_json=False)


@app.command("save")
def save_command(
    root: str | None = typer.Option(None, "--root", help="Repository root override."),
    editor: bool = typer.Option(False, "--editor", help="Open $EDITOR for decisions."),
    template: str | None = typer.Option(
        None,
        "--template",
        help="Path to JSON/TOML save template.",
    ),
    tag: list[str] = typer.Option(None, "--tag", help="Tag for this slip/checkpoint."),
    link: list[str] = typer.Option(None, "--link", help="Attach URL(s) to current slip."),
    no_prompt: bool = typer.Option(False, "--no-prompt", help="Do not ask interactive prompts."),
    objective: str | None = typer.Option(None, "--objective", help="Objective summary."),
    decisions: str | None = typer.Option(None, "--decisions", help="Decisions and findings."),
    next_step: list[str] = typer.Option(None, "--next-step", help="Next step, repeat up to 3x."),
    risks: str | None = typer.Option(None, "--risks", help="Risks and review notes."),
    command: list[str] = typer.Option(None, "--command", help="Resume command, repeat up to 5x."),
    tests_run: bool | None = typer.Option(None, "--tests-run/--no-tests-run", help="Tests status."),
    tests_command: str | None = typer.Option(None, "--tests-command", help="Tests command."),
    build_ok: bool | None = typer.Option(None, "--build-ok/--build-fail", help="Build status."),
    build_command: str | None = typer.Option(None, "--build-command", help="Build command."),
    lint_ok: bool | None = typer.Option(None, "--lint-ok/--lint-fail", help="Lint status."),
    lint_command: str | None = typer.Option(None, "--lint-command", help="Lint command."),
    smoke_ok: bool | None = typer.Option(None, "--smoke-ok/--smoke-fail", help="Smoke status."),
    smoke_notes: str | None = typer.Option(None, "--smoke-notes", help="Smoke check notes."),
    auto_review: bool = typer.Option(True, "--auto-review/--no-auto-review", help="Auto-create review when triggers fire."),
) -> None:
    """Create a new checkpoint for the current repo and branch."""
    store, _ = _store()
    paths = resolve_paths()
    runtime_config = load_runtime_config(paths)
    snapshot = _resolve_repo_context(root=root, require_git=True)
    assert snapshot is not None
    template_data = _load_template_data(template)

    objective = objective or _template_or_default(template_data, "objective", None)
    decisions = decisions or _template_or_default(template_data, "decisions", None)
    risks = risks or _template_or_default(template_data, "risks_review", None)

    if not next_step:
        templated_steps = _template_or_default(template_data, "next_steps", [])
        if isinstance(templated_steps, list):
            next_step = [str(item) for item in templated_steps if str(item).strip()]
    if not command:
        templated_commands = _template_or_default(template_data, "resume_commands", [])
        if isinstance(templated_commands, list):
            command = [str(item) for item in templated_commands if str(item).strip()]
    if not tag:
        templated_tags = _template_or_default(template_data, "tags", [])
        if isinstance(templated_tags, list):
            tag = [str(item) for item in templated_tags if str(item).strip()]
    if not link:
        templated_links = _template_or_default(template_data, "links", [])
        if isinstance(templated_links, list):
            link = [str(item) for item in templated_links if str(item).strip()]

    template_verification = _template_or_default(template_data, "verification", {})
    if isinstance(template_verification, dict):
        tests_run = (
            tests_run
            if tests_run is not None
            else _coerce_optional_bool(template_verification.get("tests_run"))
        )
        tests_command = tests_command or template_verification.get("tests_command")
        build_ok = (
            build_ok
            if build_ok is not None
            else _coerce_optional_bool(template_verification.get("build_ok"))
        )
        build_command = build_command or template_verification.get("build_command")
        lint_ok = (
            lint_ok
            if lint_ok is not None
            else _coerce_optional_bool(template_verification.get("lint_ok"))
        )
        lint_command = lint_command or template_verification.get("lint_command")
        smoke_ok = (
            smoke_ok
            if smoke_ok is not None
            else _coerce_optional_bool(template_verification.get("smoke_ok"))
        )
        smoke_notes = smoke_notes or template_verification.get("smoke_notes")

    if editor and not decisions:
        edited = click.edit("# Decisions / Findings\n")
        if edited:
            decisions = _normalize_editor_text(edited)

    if not no_prompt:
        if not objective:
            objective = typer.prompt("Objective")
        if not decisions:
            decisions = typer.prompt("Decisions / Findings", default="")
        if not next_step:
            next_step = _comma_or_pipe_values(
                typer.prompt("Next steps (1-3, comma or | separated)")
            )
        if not risks:
            risks = typer.prompt("Risks / Review Needed", default="")
        if not command:
            command = _comma_or_pipe_values(
                typer.prompt("Resume commands (0-5, comma or | separated)", default="")
            )
    else:
        if not objective or not decisions or not next_step:
            raise typer.BadParameter(
                "--no-prompt requires --objective, --decisions, and at least one --next-step."
            )

    cleaned_objective = (objective or "").strip()
    cleaned_decisions = (decisions or "").strip()
    cleaned_risks = (risks or "").strip()
    cleaned_next_steps = [step.strip() for step in (next_step or []) if step.strip()]
    cleaned_resume_commands = [item.strip() for item in (command or []) if item.strip()]

    if not cleaned_objective:
        raise typer.BadParameter("Objective is required.")
    if not cleaned_decisions:
        raise typer.BadParameter("Decisions / Findings is required.")
    if not cleaned_next_steps:
        raise typer.BadParameter("At least one next step is required.")
    if not cleaned_risks:
        raise typer.BadParameter("Risks / Review Needed is required.")

    verification = _verification_from_inputs(
        no_prompt=no_prompt,
        tests_run=tests_run,
        tests_command=tests_command,
        build_ok=build_ok,
        build_command=build_command,
        lint_ok=lint_ok,
        lint_command=lint_command,
        smoke_ok=smoke_ok,
        smoke_notes=smoke_notes,
    )
    save_input = SaveInput(
        objective=cleaned_objective,
        decisions=cleaned_decisions,
        next_steps=cleaned_next_steps[:3],
        risks_review=cleaned_risks,
        resume_commands=cleaned_resume_commands[:5],
        tags=tag or [],
        links=link or [],
    )
    checkpoint, triggers, review_id = create_checkpoint(
        store=store,
        paths=paths,
        git=snapshot,
        user_input=save_input,
        verification=verification,
        create_review_on_trigger=auto_review,
        review_heuristics=runtime_config.review_heuristics,
    )
    console.print(
        f"[green]Saved checkpoint[/green] {_safe_text(checkpoint.id)} for {_safe_text(checkpoint.branch)}"
    )
    if triggers:
        console.print(f"[yellow]Review triggers:[/yellow] {_safe_text(', '.join(triggers))}")
    if review_id:
        console.print(f"[yellow]Created review item:[/yellow] {_safe_text(review_id)}")


@app.command("resume")
def resume_command(
    berth: str | None = typer.Argument(None, help="Optional berth name or repo_id."),
    branch: str | None = typer.Option(None, "--branch", help="Branch name to resume."),
    run: bool = typer.Option(False, "--run", help="Execute resume commands sequentially."),
    handoff: bool = typer.Option(False, "--handoff", help="Print agent-ready handoff block."),
    as_json: bool = typer.Option(False, "--json", help="Output structured JSON."),
) -> None:
    """Resume latest checkpoint for current repo or selected berth."""
    store, _ = _store()

    repo_id: str | None = None
    berth_record = None
    if berth:
        berth_record = store.resolve_berth(berth)
        if not berth_record:
            raise DockyardError(f"Unknown berth: {berth}")
        repo_id = berth_record.repo_id
    else:
        try:
            snapshot = inspect_repository()
            repo_id = snapshot.repo_id
            berth_record = store.resolve_berth(repo_id)
        except NotGitRepositoryError:
            raise DockyardError("Not in a git repo. Provide a berth argument.")

    checkpoint = store.get_latest_checkpoint(repo_id=repo_id, branch=branch)
    if not checkpoint:
        raise DockyardError("No checkpoint found for the requested context.")
    open_reviews = store.count_open_reviews(checkpoint.repo_id, checkpoint.branch)

    project_name = berth_record.name if berth_record else checkpoint.repo_id

    if as_json:
        _emit_json(
            checkpoint_to_jsonable(
                checkpoint,
                open_reviews=open_reviews,
                project_name=project_name,
            )
        )
    else:
        print_resume(
            console,
            checkpoint,
            open_reviews=open_reviews,
            project_name=project_name,
        )

    if handoff:
        handoff_block = "\n".join(
            [
                "### Dockyard Handoff",
                f"- Repo ID: {_safe_text(checkpoint.repo_id)}",
                f"- Branch: {_safe_text(checkpoint.branch)}",
                f"- Objective: {_safe_text(checkpoint.objective)}",
                "- Next Steps:",
                *[f"  - {_safe_text(step)}" for step in checkpoint.next_steps],
                f"- Risks: {_safe_text(checkpoint.risks_review)}",
                f"- Verification: tests={checkpoint.verification.tests_run}, build={checkpoint.verification.build_ok}, lint={checkpoint.verification.lint_ok}",
                "- Commands:",
                *[f"  - {_safe_text(cmd)}" for cmd in checkpoint.resume_commands],
            ]
        )
        console.print(Panel.fit(handoff_block, title="Agent Handoff", border_style="cyan"))

    if run:
        if not berth_record:
            berth_record = store.resolve_berth(checkpoint.repo_id)
        if not berth_record:
            raise DockyardError("Cannot resolve repository root for --run execution.")
        success, results = run_commands(checkpoint.resume_commands, cwd=berth_record.root_path)
        for cmd, code in results:
            console.print(f"$ {_safe_text(cmd)} -> exit {code}")
        if not success:
            raise SystemExit(1)


@app.command("ls")
def ls_command(
    stale: int | None = typer.Option(None, "--stale", help="Only show slips stale for N days."),
    tag: str | None = typer.Option(None, "--tag", help="Filter by tag."),
    limit: int | None = typer.Option(None, "--limit", help="Max rows."),
    as_json: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """List harbor dashboard across berths and slips."""
    store, _ = _store()
    stale = _require_minimum_int(stale, minimum=0, field_name="--stale")
    limit = _require_minimum_int(limit, minimum=1, field_name="--limit")
    rows = store.list_harbor(stale_days=stale, tag=tag, limit=limit)
    if as_json:
        _emit_json(rows)
    else:
        print_harbor(console, rows)


@app.command("search")
def search_command(
    query: str = typer.Argument(..., help="Search query string."),
    tag: str | None = typer.Option(None, "--tag", help="Filter by tag."),
    repo: str | None = typer.Option(
        None,
        "--repo",
        help="Filter by repo_id or berth name.",
    ),
    branch: str | None = typer.Option(None, "--branch", help="Filter by branch."),
    limit: int = typer.Option(20, "--limit", help="Max results."),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Search checkpoint objectives, decisions, next steps, and risks."""
    store, _ = _store()
    cleaned_query = query.strip()
    if not cleaned_query:
        raise typer.BadParameter("Query must be a non-empty string.")
    limit = _require_minimum_int(limit, minimum=1, field_name="--limit") or 20
    repo_filter = repo
    if repo:
        berth = store.resolve_berth(repo)
        if berth:
            repo_filter = berth.repo_id
    rows = search_service(
        store,
        query=cleaned_query,
        tag=tag,
        repo=repo_filter,
        branch=branch,
        limit=limit,
    )
    if as_json:
        _emit_json(rows)
    else:
        print_search(console, rows)


@review_app.callback()
def review_callback(
    ctx: typer.Context,
    all_items: bool = typer.Option(
        False,
        "--all",
        help="Include resolved review items in default listing.",
    ),
) -> None:
    """Default `dock review` behavior: list review items."""
    if ctx.invoked_subcommand is None:
        review_list(all_items=all_items)


@review_app.command("list", hidden=True)
def review_list(
    all_items: bool = typer.Option(False, "--all", help="Include done items."),
) -> None:
    """List review items."""
    store, _ = _store()
    items = store.list_reviews(open_only=not all_items)
    if not items:
        console.print("No review items.")
        return
    lines = [
        (
            f"{_safe_text(item.id)} | {_safe_text(item.severity)} | {_safe_text(item.status)}"
            f" | {_safe_text(item.repo_id)}/{_safe_text(item.branch)} | {_safe_text(item.reason)}"
        )
        for item in items
    ]
    console.print("\n".join(lines))


@review_app.command("add")
def review_add(
    reason: str = typer.Option(..., "--reason", help="Reason or category for review."),
    severity: str = typer.Option("med", "--severity", help="Severity: low|med|high."),
    notes: str | None = typer.Option(None, "--notes", help="Optional notes."),
    file: list[str] = typer.Option(None, "--file", help="Associated file path(s)."),
    checkpoint_id: str | None = typer.Option(None, "--checkpoint-id", help="Associated checkpoint ID."),
    repo: str | None = typer.Option(None, "--repo", help="Repo ID override."),
    branch: str | None = typer.Option(None, "--branch", help="Branch override."),
) -> None:
    """Create a manual review item."""
    store, _ = _store()
    normalized_severity = _validate_review_severity(severity)
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise typer.BadParameter("--reason must be a non-empty string.")
    if (repo and not branch) or (branch and not repo):
        raise DockyardError("Provide both --repo and --branch when overriding context.")
    if repo and branch:
        # Allow using berth name for ergonomics in cross-repo contexts.
        berth = store.resolve_berth(repo)
        if berth:
            repo = berth.repo_id
    else:
        snapshot = inspect_repository()
        repo = repo or snapshot.repo_id
        branch = branch or snapshot.branch
    item = ReviewItem(
        id=f"rev_{uuid.uuid4().hex[:10]}",
        repo_id=repo,
        branch=branch,
        checkpoint_id=checkpoint_id,
        created_at=utc_now_iso(),
        reason=normalized_reason,
        severity=normalized_severity,
        status="open",
        notes=notes,
        files=file or [],
    )
    store.add_review_item(item)
    store.recompute_slip_status(repo_id=repo, branch=branch)
    console.print(f"[green]Created review[/green] {_safe_text(item.id)}")


@review_app.command("done")
def review_done(review_id: str = typer.Argument(..., help="Review item ID.")) -> None:
    """Mark review item as done."""
    store, _ = _store()
    review = store.get_review(review_id)
    if not review:
        raise DockyardError(f"Review item not found: {review_id}")
    if not store.mark_review_done(review_id):
        raise DockyardError(f"Review item not found: {review_id}")
    store.recompute_slip_status(repo_id=review.repo_id, branch=review.branch)
    console.print(f"[green]Resolved review[/green] {_safe_text(review_id)}")


@review_app.command("open")
def review_open(review_id: str = typer.Argument(..., help="Review item ID.")) -> None:
    """Show review details and associated checkpoint context."""
    store, _ = _store()
    item = store.get_review(review_id)
    if not item:
        raise DockyardError(f"Review item not found: {review_id}")
    console.print(
        Panel.fit(
            "\n".join(
                [
                    f"id: {_safe_text(item.id)}",
                    f"repo: {_safe_text(item.repo_id)}",
                    f"branch: {_safe_text(item.branch)}",
                    f"created_at: {_safe_text(item.created_at)}",
                    f"checkpoint_id: {_safe_text(item.checkpoint_id or '')}",
                    f"severity: {_safe_text(item.severity)}",
                    f"status: {_safe_text(item.status)}",
                    f"reason: {_safe_text(item.reason)}",
                    f"notes: {_safe_text(item.notes or '')}",
                    f"files: {_safe_text(', '.join(item.files) if item.files else '')}",
                ]
            ),
            title="Review Item",
            border_style="yellow",
        )
    )
    if item.checkpoint_id:
        checkpoint = store.get_checkpoint(item.checkpoint_id)
        if checkpoint:
            console.print(
                Panel.fit(
                    (
                        f"checkpoint: {_safe_text(checkpoint.id)}\n"
                        f"objective: {_safe_text(checkpoint.objective)}"
                    ),
                    title="Associated Checkpoint",
                    border_style="cyan",
                )
            )
        else:
            console.print(
                Panel.fit(
                    (
                        f"checkpoint_id: {_safe_text(item.checkpoint_id)}\n"
                        "status: missing from index"
                    ),
                    title="Associated Checkpoint",
                    border_style="red",
                )
            )


@app.command("link")
def link_command(
    url: str = typer.Argument(..., help="URL to attach to current slip."),
    root: str | None = typer.Option(None, "--root", help="Repository root override."),
) -> None:
    """Attach a URL to the current branch context."""
    store, _ = _store()
    snapshot = inspect_repository(root_override=root)
    item = LinkItem(
        id=f"lnk_{uuid.uuid4().hex[:10]}",
        repo_id=snapshot.repo_id,
        branch=snapshot.branch,
        url=url,
        created_at=utc_now_iso(),
    )
    store.add_link(item)
    console.print(f"[green]Linked[/green] {_safe_text(url)}")


@app.command("links")
def links_command(
    root: str | None = typer.Option(None, "--root", help="Repository root override."),
) -> None:
    """List URLs attached to current slip."""
    store, _ = _store()
    snapshot = inspect_repository(root_override=root)
    items = store.list_links(snapshot.repo_id, snapshot.branch)
    if not items:
        console.print("No links for current slip.")
        return
    for item in items:
        console.print(f"{_safe_text(item.created_at)} | {_safe_text(item.url)}")


def main() -> None:
    """CLI process entrypoint."""
    try:
        app(standalone_mode=False)
    except DockyardError as err:
        console.print(f"[red]Error:[/red] {_safe_text(err)}")
        raise SystemExit(2) from err
    except NotGitRepositoryError as err:
        console.print(f"[red]Error:[/red] {_safe_text(err)}")
        raise SystemExit(2) from err
    except click.ClickException as err:
        err.show()
        raise SystemExit(err.exit_code) from err
    except click.exceptions.Exit as err:
        raise SystemExit(err.exit_code) from err


# Register aliases with identical signatures.
app.command("s", hidden=True)(save_command)
app.command("dock", hidden=True)(save_command)
app.command("r", hidden=True)(resume_command)
app.command("undock", hidden=True)(resume_command)
app.command("harbor", hidden=True)(ls_command)
app.command("f", hidden=True)(search_command)


if __name__ == "__main__":
    main()
