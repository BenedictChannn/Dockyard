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
- If a checkpoint has no next steps, resume summary shows `(none recorded)`.
- `--handoff` output compacts multiline objective/next-step/risk/command
  fields into one-line bullet previews.
- When handoff next steps or commands are empty, Dockyard prints
  `(none recorded)` placeholders.
- Blank objective/risks values in handoff render as `(none)` for explicitness.
- `--run` command labels in output are compacted to one-line previews.
- `--run` ignores blank command entries after payload normalization.
- BERTH argument must be non-empty when provided.

## `ls` (`harbor`)

Harbor dashboard listing slips across berths.

### Options

- `--stale <days>`
- `--tag <tag>`
- `--limit <n>`
- `--json`

Validation:
- `--stale` must be `>= 0`
- `--limit` must be `>= 1`

`ls --json` returns `[]` when no slips are indexed.

## `search` (`f`)

Search checkpoint objectives, decisions, next steps, and risks.

### Usage

```bash
python3 -m dockyard search "<query>"
python3 -m dockyard search "<query>" --json
python3 -m dockyard search "<query>" --repo my_repo --tag backend --json
python3 -m dockyard search "<query>" --tag backend --branch feature/workstream --json
python3 -m dockyard search "<query>" --tag backend --repo my_repo --branch feature/workstream --json
python3 -m dockyard f "<query>" --branch feature/workstream --json
python3 -m dockyard f "<query>" --repo my_repo --branch feature/workstream --json
python3 -m dockyard f "<query>" --tag backend --json
python3 -m dockyard f "<query>" --tag backend --branch feature/workstream --json
python3 -m dockyard f "<query>" --tag backend --limit 5 --json
python3 -m dockyard f "<query>" --tag backend --repo my_repo --json
python3 -m dockyard f "<query>" --tag backend --repo my_repo --branch feature/workstream --json
```

When no results match, Dockyard prints: `No checkpoint matches found.`
With `--json`, no-match output is `[]`.
Snippets are normalized to compact single-line text for scanability.
This no-match behavior is consistent even when `--tag`, `--repo`, or
`--branch` filters are provided.

### Options

- `--tag <tag>`
- `--repo <repo_id|berth_name>`
- `--branch <branch>`
- `--limit <n>`
- `--json`

Validation:
- query must be non-empty
- `--limit` must be `>= 1`
- `--repo` must be non-empty when provided

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
List rows compact multiline values into single-line previews and show explicit
fallbacks (`(unknown)` / `(none)`) for blank metadata fields.

### Add

```bash
python3 -m dockyard review add --reason "manual validation" --severity med
# outside repo, provide both:
python3 -m dockyard review add --reason "manual" --severity low --repo my_repo --branch my_branch
# --repo accepts repo_id or berth name
```

`review add` ignores blank `--file` entries.
Optional `--notes` and `--checkpoint-id` values are trimmed; blank values are
treated as missing.
Override values passed to `--repo/--branch` are also trimmed before lookup.

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

`links` output compacts multiline URL/timestamp values to single-line previews
and uses `(unknown)` fallback text for blank fields.
