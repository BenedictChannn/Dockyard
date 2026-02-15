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

Template-powered non-interactive mode:

```bash
python3 -m dockyard save --template ./checkpoint_template.json --no-prompt
```

Optional editor capture for decisions:

```bash
python3 -m dockyard save --editor
# if --decisions is provided, it takes precedence and $EDITOR is not invoked
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

### 3) Harbor dashboard across projects

```bash
python3 -m dockyard ls
```

Filters:

```bash
python3 -m dockyard ls --stale 3 --tag mvp --limit 20
```

### 4) Search decisions/findings

```bash
python3 -m dockyard search "migration"
python3 -m dockyard search "search indexing" --repo <repo_id> --branch main --tag mvp
python3 -m dockyard search "auth" --json
# --repo also accepts berth name
# query must be non-empty, --limit must be >= 1
# in --json mode, no matches are returned as []
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

### 6) Link URLs to a branch context

```bash
python3 -m dockyard link https://example.com/pr/123
python3 -m dockyard links
```

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

Only `resume --run` executes user-authored commands, which can mutate repos if
those commands do so.

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