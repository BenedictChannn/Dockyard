# Dockyard Commands (MVP)

All commands are available through:

```bash
python3 -m dockyard <command>
```

## `save` (`s`)

Create a new checkpoint for current repo/branch.

### Key options

- `--root <path>`: explicit repo root
- `--editor`: open `$EDITOR` for decisions text
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

## `search` (`f`)

Search checkpoint objectives/decisions/next steps.

### Usage

```bash
python3 -m dockyard search "<query>"
```

### Options

- `--tag <tag>`
- `--repo <repo_id>`
- `--branch <branch>`
- `--limit <n>`

## `review`

Review queue management.

### List open (default)

```bash
python3 -m dockyard review
```

### Add

```bash
python3 -m dockyard review add --reason "manual validation" --severity med
```

### Mark done

```bash
python3 -m dockyard review done <review_id>
```

### Open details

```bash
python3 -m dockyard review open <review_id>
```

## `link` / `links`

Attach and list URLs for current slip.

```bash
python3 -m dockyard link https://example.com/pr/123
python3 -m dockyard links
```
