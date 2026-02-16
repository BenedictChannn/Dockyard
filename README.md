# Dockyard

Dockyard is a **local-first, git-aware CLI** for capturing coding context quickly
(`dock save`) and resuming work instantly (`dock resume`) across many repos and branches.

It acts like a coding-workstream notepad with a queryable index:

- stores markdown checkpoints (human-readable)
- indexes checkpoints/reviews in SQLite (fast dashboard and search)
- tracks review debt and verification state
- avoids mutating project repos by default

## Install

```bash
python3 -m pip install -e ".[dev]"
```

Run via module:

```bash
python3 -m dockyard --help
```

Or via console script (`dock`) if your user script directory is on `PATH`.

## Core workflow

### 1) Save a checkpoint before context switching

```bash
python3 -m dockyard save
# alias:
python3 -m dockyard dock
```

Fast non-interactive mode:

```bash
python3 -m dockyard save \
  --no-prompt \
  --objective "Implement search indexing" \
  --decisions "Use SQLite FTS5 with LIKE fallback" \
  --next-step "Write search tests" \
  --next-step "Document filters" \
  --risks "Review migration logic" \
  --command "pytest -q" \
  --tests-run --tests-command "pytest -q" \
  --build-ok --build-command "python -m build"
```

`save` trims `--tag` / `--link` values, ignores blank entries, and de-duplicates
exact repeats.
`--root` override values are trimmed; blank values are rejected.
`--template` path values are trimmed; blank values are rejected.
`--template` must point to a readable file.
Verification command/note text flags are trimmed; blank values are treated as
missing.

Template-powered non-interactive mode:

```bash
python3 -m dockyard save --template ./checkpoint_template.json --no-prompt
```

Optional editor capture for decisions:

```bash
python3 -m dockyard save --editor
# if --decisions is provided, it takes precedence and $EDITOR is not invoked
# the scaffold heading is ignored, but intentional blank lines are preserved
```

Example template:

```json
{
  "objective": "Ship harbor sorting polish",
  "decisions": "Keep sorting in SQL-backed index layer",
  "next_steps": ["Add integration test", "Re-run perf smoke"],
  "risks_review": "Review ordering assumptions",
  "resume_commands": ["pytest -q"],
  "tags": ["mvp"],
  "links": ["https://example.com/pr/123"],
  "verification": {
    "tests_run": true,
    "tests_command": "pytest -q",
    "build_ok": true,
    "build_command": "python -m build",
    "lint_ok": false,
    "smoke_ok": false
  }
}
```

### 2) Resume quickly

```bash
python3 -m dockyard resume
```

Useful flags:

- `--branch <name>` resume specific branch
- `--handoff` print agent-ready block
- `--run` run recorded commands in sequence (stop on first failure)
- `--json` structured output
- Resume summary lines compact multiline objective/next-step text into single
  line previews for faster scanning.
- Handoff bullets and `--run` command labels are compacted to single-line
  previews for readability.
- Handoff shows `(none recorded)` placeholders when no next steps or commands
  are recorded.
- Handoff renders blank objective/risks values as `(none)`, and `--run`
  ignores blank command entries after normalization.
- `--run` is always explicit opt-in, including BERTH/`--branch` variants
  (for example: `resume my-berth --branch main --run`).
- BERTH argument values are trimmed; blank BERTH values are rejected.
- `--branch` values are trimmed; blank values are rejected.

### 3) Harbor dashboard across projects

```bash
python3 -m dockyard ls
```

Filters:

```bash
python3 -m dockyard ls --stale 3 --tag mvp --limit 20
```

`--tag` values are trimmed; blank values are rejected.

### 4) Search objectives, decisions, next steps, and risks

```bash
python3 -m dockyard search "migration"
python3 -m dockyard search "search indexing" --repo <repo_id> --branch main --tag mvp
python3 -m dockyard search "auth" --json
python3 -m dockyard search "auth" --tag backend --branch feature/workstream --json
python3 -m dockyard search "auth" --tag backend --repo <repo_id|berth_name> --branch feature/workstream --json
python3 -m dockyard f "auth" --branch feature/workstream --json
python3 -m dockyard f "auth" --repo <repo_id|berth_name> --branch feature/workstream --json
python3 -m dockyard f "auth" --tag backend --json
python3 -m dockyard f "auth" --tag backend --branch feature/workstream --json
python3 -m dockyard f "auth" --tag backend --limit 5 --json
python3 -m dockyard f "auth" --tag backend --repo <repo_id|berth_name> --json
python3 -m dockyard f "auth" --tag backend --repo <repo_id|berth_name> --branch feature/workstream --json
# --repo also accepts berth name
# query must be non-empty, --limit must be >= 1
# --tag must be non-empty when provided
# --repo must be non-empty when provided
# --branch must be non-empty when provided
# in --json mode, no matches are returned as []
# snippets are compacted to single-line text for scanability
# unicode characters are emitted as-is in --json output
# filtered searches keep the same no-match behavior/message semantics
```

### 5) Review queue

```bash
python3 -m dockyard review            # list open
python3 -m dockyard review --all      # include resolved
python3 -m dockyard review add --reason "manual check" --severity med
# outside repo context:
python3 -m dockyard review add --reason "manual check" --severity med --repo <repo_id|berth_name> --branch <branch>
python3 -m dockyard review open <id>
python3 -m dockyard review done <id>
```

Review list/open outputs compact multiline fields into single-line text and use
explicit fallback markers (`(unknown)` / `(none)`) for blank metadata values
(including checkpoint id, notes, and file fields in `review open`).
`review add` ignores blank `--file` entries and de-duplicates exact repeats.
Optional `--notes` / `--checkpoint-id` values are trimmed, and blank values are
treated as missing.
`--repo` / `--branch` override values are trimmed before lookup.
`--repo` / `--branch` must be non-empty when provided.
`--severity` must be non-empty and one of `low|med|high`.
`review open` / `review done` IDs are trimmed; blank IDs are rejected.

### 6) Link URLs to a branch context

```bash
python3 -m dockyard link https://example.com/pr/123
python3 -m dockyard links
```

`link` validates URL input as a non-empty string.
Outer whitespace on URL input is trimmed before persistence/display.
`--root` override values are trimmed; blank values are rejected.
`links` output also compacts multiline values and uses `(unknown)` fallback for
blank timestamp/URL fields.

## Storage

By default Dockyard writes to:

- Linux/macOS: `~/.local/share/dockyard/`
- Windows: `%APPDATA%/dockyard/`

Layout:

- `checkpoints/<repo_id>/<branch>/<checkpoint_id>.md`
- `db/index.sqlite`
- `config.toml`

Override base path with:

```bash
export DOCKYARD_HOME=/path/to/custom/store
```

Optional `config.toml` can override review heuristic thresholds/patterns (see
`docs/HEURISTICS.md`).

## Safety boundary

Dockyard is intended to be non-invasive:

- reads repository state and git metadata
- writes its own markdown + sqlite store
- does **not** mutate your repo in normal operations

Only the explicit run modes (`resume --run`, `r --run`, `undock --run`)
execute user-authored commands, which can mutate repos if those commands do so.

## Development

Run tests:

```bash
python3 -m pytest
```

Project docs:

- `docs/PRD.md`
- `docs/DATA_MODEL.md`
- `docs/COMMANDS.md`
- `docs/HEURISTICS.md`

Dogfood script:

```bash
bash scripts/dogfood_demo.sh
```

Performance smoke script:

```bash
python3 scripts/perf_smoke.py
# optional target enforcement
python3 scripts/perf_smoke.py --enforce-targets
```