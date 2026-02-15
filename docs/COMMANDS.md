# Dockyard Commands (MVP)

All commands are available through:

```bash
python3 -m dockyard <command>
```

JSON flags (`--json`) emit raw machine-parseable JSON suitable for piping to
tools like `jq`.

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
- If `--decisions` is provided explicitly, Dockyard uses it and does not invoke
  `$EDITOR`.

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
```

When no results match, Dockyard prints: `No checkpoint matches found.`
With `--json`, no-match output is `[]`.

### Options

- `--tag <tag>`
- `--repo <repo_id|berth_name>`
- `--branch <branch>`
- `--limit <n>`
- `--json`

Validation:
- query must be non-empty
- `--limit` must be `>= 1`

## `review`

Review queue management.

### List open (default)

```bash
python3 -m dockyard review
# include resolved:
python3 -m dockyard review --all
```

### Add

```bash
python3 -m dockyard review add --reason "manual validation" --severity med
# outside repo, provide both:
python3 -m dockyard review add --reason "manual" --severity low --repo my_repo --branch my_branch
# --repo accepts repo_id or berth name
```

### Mark done

```bash
python3 -m dockyard review done <review_id>
```

### Open details

```bash
python3 -m dockyard review open <review_id>
```

`review open` displays review metadata plus associated checkpoint details (if
available), including creation timestamp, checkpoint id, and any attached file
paths.

## `link` / `links`

Attach and list URLs for current slip.

```bash
python3 -m dockyard link https://example.com/pr/123
python3 -m dockyard links
```
