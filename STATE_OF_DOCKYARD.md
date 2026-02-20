# State of Dockyard

_Last updated: 2026-02-19_

## 1) What Dockyard is

Dockyard is a local-first, git-aware CLI that helps teams checkpoint and
resume engineering context across repositories and branches.

It is built to reduce context-reload overhead by preserving:

- objective
- decisions/findings
- next steps
- risks/review notes
- optional resume commands and verification state

## 2) Current product surface

Core commands:

- `save` (`s`, `dock`) — capture a checkpoint
- `resume` (`r`, `undock`) — restore latest context
- `ls` (`harbor`) — dashboard across berths
- `search` (`f`) — find prior context by query
- `review` — track open/done review items
- `link` / `links` — attach and list branch-scoped URLs
- `quickstart` — first-run guidance with copy-paste commands

## 3) Why use Dockyard

Dockyard is optimized for the part of engineering work where teams lose time:
recovering context after handoffs and interruptions.

Value proposition:

1. Faster restart after context switches
2. More reliable async handoffs
3. Searchable decision/risk trail over time
4. Safe-by-default local workflow

## 4) Safety boundary

Dockyard is designed to be non-invasive for normal usage:

- reads git/repository metadata
- writes to Dockyard-owned markdown/sqlite storage
- does **not** mutate project repos in standard read/save workflows

Only explicit run modes (`resume --run`, `r --run`, `undock --run`) execute
recorded commands that may mutate repositories.

## 5) Reliability snapshot

Dockyard includes broad integration and non-interference coverage to keep
behavior stable across aliases and edge cases.

Latest local verification snapshot (2026-02-19):

- `tests/test_cli_integration.py`: **775 passed**
- `tests/test_non_interference.py`: **622 passed**
- `tests/test_search.py`: **21 passed**
- `tests/test_perf_smoke.py` + `tests/test_markdown_roundtrip.py`: **101 passed**
- `ruff check dockyard tests scripts`: **pass**

For reproducible quality checks, run:

```bash
python3 -m pytest tests/test_cli_integration.py
python3 -m pytest tests/test_non_interference.py
python3 -m pytest tests/test_search.py
python3 -m pytest tests/test_perf_smoke.py tests/test_markdown_roundtrip.py
python3 -m ruff check dockyard tests scripts
```

See also:

- `docs/METRICS.md`
- `docs/MONTHLY_STATUS_TEMPLATE.md`

## 6) Known strengths right now

- Alias parity and validation behavior are strongly hardened.
- JSON output contracts are machine-friendly and stable.
- Non-interference guarantees are extensively tested.
- Template/config validation paths are robust and actionable.

## 7) Known gaps / next iteration targets

Priority next steps:

1. Tighten first-run onboarding and `--help` discoverability.
2. Add handoff-centric summary modes for external sharing.
3. Publish monthly metric trends (time-to-context, safety, latency).

## 8) Public proof assets

Recommended proof bundle for external posts:

1. Quickstart walkthrough (`python3 -m dockyard quickstart`)
2. End-to-end terminal demo (save → harbor → search → resume)
3. Current reliability + safety checks (commands above)
4. Monthly metrics snapshot using the template in docs
