# Dockyard PRD (MVP)

## One-liner

Dockyard is a local-first, git-aware CLI that lets developers **dock** work
(capture decisions + state) and **undock** later (resume instantly) across many
repos and branches.

## Product promise

Resume any repo/branch in ≤30 seconds with the right context, next steps, and
commands.

## Problem

AI-heavy development increases context thrash:

- decisions and rationale are forgotten
- branch juggling creates resume friction
- review debt accumulates
- setup/verification steps are repeatedly rediscovered

## MVP goals

1. Dock in ≤60s with high-signal checkpoint capture.
2. Undock in ≤30s with objective/next step/verification visibility.
3. Preserve decisions/findings for search and retrieval.
4. Auto-surface risky or large changes in a review ledger.
5. Show active/stale/risky/pending-review workstreams in one CLI dashboard.

## Non-goals

- full PM suite
- required GitHub sync
- cloud collaboration
- full diff storage by default

## MVP command scope

- `dock save` (`dock s`)
- `dock resume` (`dock r`, `dock undock`)
- `dock ls` (`dock`, `dock harbor`)
- `dock search` (`dock f`)
- `dock review`, `dock review add`, `dock review done`, `dock review open`
- `dock link`, `dock links`

## Data model

- **Berth**: repo identity
- **Slip**: branch-scoped workstream
- **Checkpoint**: user notes + git evidence + verification
- **Review item**: open/done review debt record

## Heuristics summary

### Review suggestion triggers

- risky paths touched (`auth/`, `infra/`, `.github/`, `terraform/`,
  `migrations/`, `payments/`, `security/`)
- files changed ≥ 15
- insertions + deletions ≥ 400
- tests missing and diff is non-trivial
- branch starts with `release/` or `hotfix/`

### Slip status

- **Green**: tests + build good and no high severity open review
- **Yellow**: partial verification or low/med review debt
- **Red**: risky/large/unreviewed combinations or high-severity review open

## Storage architecture

Two-layer local storage:

1. Markdown per checkpoint (human-readable and diffable)
2. SQLite index for fast dashboard/search/review queries

Default location:

- Linux/macOS: `~/.local/share/dockyard/`
- Windows: `%APPDATA%/dockyard/`

## Success metrics

- median `save` ≤ 60s
- median `resume` to first meaningful command ≤ 30s
- high risky-diff review coverage
- strong reduction in rediscovery events

## Safety boundary

Dockyard is a context/index tool, not a repo mutator. It reads git state and
writes to Dockyard storage. `resume --run` is explicit opt-in command execution.
