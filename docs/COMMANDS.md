# Dockyard Commands (MVP)

All commands are available through:

```bash
python3 -m dockyard <command>
```

JSON flags (`--json`) emit raw machine-parseable JSON suitable for piping to
tools like `jq` (including unicode text without escaping).

## `save` (`s`, `dock`)

Create a new checkpoint for current repo/branch.

### Key options

- `--root <path>`: explicit repo root
- `--editor`: open `$EDITOR` for decisions text
- `--template <path>`: load default fields from `.json` or `.toml` template
- `--tag <tag>`: repeatable
- `--link <url>`: repeatable
- `--no-prompt`: non-interactive mode
- `--objective`, `--decisions`, `--next-step`, `--risks`, `--command`
- verification flags:
  - `--tests-run/--no-tests-run`, `--tests-command`
  - `--build-ok/--build-fail`, `--build-command`
  - `--lint-ok/--lint-fail`, `--lint-command`
  - `--smoke-ok/--smoke-fail`, `--smoke-notes`
- `--auto-review/--no-auto-review`

### Example

```bash
python3 -m dockyard save --no-prompt \
  --objective "Fix flaky migration test" \
  --decisions "Keep sqlite + markdown dual store" \
  --next-step "Add migration idempotence test" \
  --risks "Needs schema review" \
  --command "pytest -q"
python3 -m dockyard s --no-prompt --objective "..." --decisions "..." --next-step "..." --risks "..."
python3 -m dockyard dock --no-prompt --objective "..." --decisions "..." --next-step "..." --risks "..."
```

Template mode:

```bash
python3 -m dockyard save \
  --template ./checkpoint_template.json \
  --no-prompt
```

Editor note:
- If you use `--editor` and leave the scaffold line unchanged
  (`# Decisions / Findings`), Dockyard treats decisions as missing and keeps
  required-field validation intact.
- The scaffold-line check is whitespace-tolerant, so indented scaffold-only
  text is also treated as missing decisions.
- Repeated scaffold lines are stripped as comments before persistence.
- Dockyard trims only leading/trailing empty lines from editor text; intentional
  internal blank lines are preserved.
- If `--decisions` is provided explicitly, Dockyard uses it and does not invoke
  `$EDITOR`.
- `--tag` / `--link` values are trimmed, blank entries are ignored, and exact
  duplicates are de-duplicated.
- `--root` must be non-empty when provided.
- `--template` path values are trimmed and must be non-empty when provided.
- `--template` path must resolve to a readable file.
- template payloads must parse as object/table structures (`.json` or `.toml`);
  non-object payloads are rejected.
- template list fields (`next_steps`, `resume_commands`, `tags`, `links`) must
  be arrays of strings.
- template `verification` (when present) must be an object/table; status flags
  (`tests_run`, `build_ok`, `lint_ok`, `smoke_ok`) accept bool or bool-like
  strings (`yes/no`, `true/false`, `1/0`).
- verification command/note text fields are trimmed for both CLI flag inputs
  and template-provided values; blank values are treated as missing.

## `resume` (`r`, `undock`)

Show latest checkpoint for current repo (or selected berth).

### Usage

```bash
python3 -m dockyard resume [BERTH]
```

### Options

- `--branch <name>`
- `--run` execute resume commands sequentially (stop on failure)
- `--handoff` print agent-ready context block
- `--json` structured output

Notes:
- Resume summary compacts multiline objective and next-step values into
  single-line previews.
- Resume top-lines summary contract (Project/Branch, Last Checkpoint,
  Objective, Next Steps, Open Reviews, Verification) is consistent for
  `resume`, `r`, and `undock`, including explicit BERTH lookups and
  BERTH + `--branch` invocations outside repos, as well as in-repo
  `--branch` flows with trimmed branch values.
- Trimmed BERTH/`--branch` inputs are normalized in output, so
  `Project/Branch:` headers remain canonical (`<berth> / <branch>`).
- If a checkpoint has no next steps, resume summary shows `(none recorded)`.
- `--handoff` output compacts multiline objective/next-step/risk/command
  fields into one-line bullet previews.
- BERTH + `--branch` scoped resume lookups support `--handoff` and `--json`
  from outside repo directories (for example:
  `python3 -m dockyard resume my-berth --branch main --handoff`).
- BERTH values are validated as non-empty strings for `resume`, `r`, and
  `undock`; unknown berth values fail with actionable errors while preserving
  literal text.
- When handoff next steps or commands are empty, Dockyard prints
  `(none recorded)` placeholders.
- Blank objective/risks values in handoff render as `(none)` for explicitness.
- `--run` command labels in output are compacted to one-line previews.
- `--run` trims surrounding whitespace from command entries and ignores blanks
  after payload normalization.
- `--run` is explicit opt-in: `resume --run`, `r --run`, and
  `undock --run` may mutate repo files depending on recorded commands.
- Opt-in mutation semantics also apply when BERTH and/or `--branch` are used
  with `--run` (e.g., `resume <berth> --branch <name> --run`).
- If no resume commands are recorded, `--run` is a no-op success for
  `resume`, `r`, and `undock` (no command execution rows are emitted).
- The same no-op behavior applies when persisted command payloads contain only
  blank/whitespace entries after normalization.
- If the persisted berth root path for `--run` no longer exists, Dockyard
  fails with an actionable error instead of a traceback (including BERTH +
  `--branch` scoped invocations).
- If BERTH/`--branch` context has no checkpoint, Dockyard reports
  `No checkpoint found for the requested context.` without traceback noise
  across default, `--json`, and `--handoff` output modes.
- BERTH argument must be non-empty when provided.
- `--branch` must be non-empty when provided.

## `ls` (`harbor`)

Harbor dashboard listing slips across berths.

When invoked with no subcommand (`python3 -m dockyard`), Dockyard defaults to
the same harbor listing path and accepts the same `ls` flags at the root level
(for example: `python3 -m dockyard --json --tag mvp --limit 20`).
Root-level callback validation mirrors `ls` behavior (`--stale >= 0`,
`--limit >= 1`, non-empty `--tag`).
Combined filters are also supported via the callback path
(`python3 -m dockyard --json --tag mvp --stale 3 --limit 20`).

Example alias usage:
`python3 -m dockyard harbor --tag mvp --limit 20`

### Options

- `--stale <days>`
- `--tag <tag>`
- `--limit <n>`
- `--json`

Validation:
- `--stale` must be `>= 0`
- `--limit` must be `>= 1`
- `--tag` must be non-empty when provided

`ls --json`, `harbor --json`, and root callback `--json` all return `[]` when
no slips are indexed.
The same JSON no-match contract applies to filtered dashboard paths as well
(`--tag`, `--stale`, `--limit`, and combined filter variants).

## `search` (`f`)

Search checkpoint objectives, decisions, next steps, and risks.

### Usage

```bash
python3 -m dockyard search "<query>"
python3 -m dockyard search "<query>" --json
python3 -m dockyard search "<query>" --tag backend --repo my_repo
python3 -m dockyard search "<query>" --tag backend --repo my_repo --branch feature/workstream
python3 -m dockyard search "<query>" --repo my_repo --tag backend --json
python3 -m dockyard search "<query>" --tag backend --branch feature/workstream --json
python3 -m dockyard search "<query>" --tag backend --repo my_repo --branch feature/workstream --json
python3 -m dockyard search "<query>" --tag backend --repo my_repo --branch feature/workstream --limit 5 --json
python3 -m dockyard f "<query>" --branch feature/workstream
python3 -m dockyard f "<query>" --repo my_repo --branch feature/workstream
python3 -m dockyard f "<query>" --tag backend
python3 -m dockyard f "<query>" --tag backend --branch feature/workstream
python3 -m dockyard f "<query>" --tag backend --repo my_repo
python3 -m dockyard f "<query>" --tag backend --limit 5
python3 -m dockyard f "<query>" --branch feature/workstream --json
python3 -m dockyard f "<query>" --repo my_repo --branch feature/workstream --json
python3 -m dockyard f "<query>" --tag backend --json
python3 -m dockyard f "<query>" --tag backend --branch feature/workstream --json
python3 -m dockyard f "<query>" --tag backend --limit 5 --json
python3 -m dockyard f "<query>" --tag backend --repo my_repo --json
python3 -m dockyard f "<query>" --tag backend --repo my_repo --branch feature/workstream --json
python3 -m dockyard f "<query>" --tag backend --repo my_repo --branch feature/workstream --limit 5 --json
```

When no results match, Dockyard prints: `No checkpoint matches found.`
With `--json`, no-match output is `[]`.
`--limit` is applied after `--tag` / `--repo` / `--branch` filters.
Snippets are normalized to compact single-line text for scanability.
When multiple fields match, snippets prioritize objective text first.
JSON snippet text is bounded to 140 characters for stable payload size.
Non-JSON `search`/`f` table output truncates long snippets for readability.
`search --json` and `f --json` rows share a stable schema:
`id`, `repo_id`, `berth_name`, `branch`, `created_at`, `snippet`, `objective`.
This no-match behavior is consistent even when `--tag`, `--repo`, or
`--branch` filters are provided.
The same contract applies to combined filter paths like
`--repo + --branch` and `--tag + --repo + --branch` for both `search` and `f`.
No-match semantics are unchanged when `--limit` is also supplied alongside
those filters.
Queries that contain FTS parser-sensitive syntax (for example `security/path`)
automatically fall back to parser-safe matching while preserving the same
filter semantics (including when `--limit` is combined with filters).

### Options

- `--tag <tag>`
- `--repo <repo_id|berth_name>`
- `--branch <branch>`
- `--limit <n>`
- `--json`

Validation:
- query must be non-empty
- `--limit` must be `>= 1`
- `--tag` must be non-empty when provided
- `--repo` must be non-empty when provided
- `--branch` must be non-empty when provided
- if `--repo` matches both a `repo_id` and a berth `name`, Dockyard uses the
  exact `repo_id` match first

## `review`

Review queue management.

### List open (default)

```bash
python3 -m dockyard review
python3 -m dockyard review list
# include resolved:
python3 -m dockyard review --all
python3 -m dockyard review list --all
```

Both `review` and `review list` print `No review items.` when the ledger is empty.
`review list` uses the same severity-first ordering as the default `review` command.
`review --all` and `review list --all` return the same ordered set of open and
resolved items.
List rows compact multiline values into single-line previews and show explicit
fallbacks (`(unknown)` / `(none)`) for blank metadata fields.

### Add

```bash
python3 -m dockyard review add --reason "manual validation" --severity med
# outside repo, provide both:
python3 -m dockyard review add --reason "manual" --severity low --repo my_repo --branch my_branch
# --repo accepts repo_id or berth name
```

`review add` ignores blank `--file` entries and de-duplicates exact repeats.
Optional `--notes` and `--checkpoint-id` values are trimmed; blank values are
treated as missing.
Override values passed to `--repo/--branch` are also trimmed before lookup.
`--repo` and `--branch` must be non-empty when provided.
`--severity` must be non-empty and one of `low|med|high`.

### Mark done

```bash
python3 -m dockyard review done <review_id>
```

`review_id` values are trimmed; blank values are rejected.

### Open details

```bash
python3 -m dockyard review open <review_id>
```

`review_id` values are trimmed; blank values are rejected.

`review open` displays review metadata plus associated checkpoint details (if
available), including creation timestamp, checkpoint id, and any attached file
paths.
This includes review items created from checkpoints captured via `save`, `s`,
or `dock`.
When the linked checkpoint id is missing from the index, `review open` shows a
`status: missing from index` notice for review items created through any save
alias flow.
Blank metadata fields are rendered with explicit fallback text where
applicable (`(unknown)` / `(none)`), and multiline values are compacted to
single-line text (including `checkpoint_id`, `notes`, and `files` fields).

## `link` / `links`

Attach and list URLs for current slip.

```bash
python3 -m dockyard link https://example.com/pr/123
python3 -m dockyard links
```

Validation:
- `link` URL must be a non-empty string
- surrounding whitespace is trimmed from URL input before persistence/display
- `--root` must be non-empty when provided

`links` output compacts multiline URL/timestamp values to single-line previews
and uses `(unknown)` fallback text for blank fields.
