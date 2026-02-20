# Dockyard Metrics Framework

This document defines the core metrics Dockyard should publish for product
credibility and longitudinal improvement.

## 1) North Star: Time-to-Context (TTC)

**Definition:** elapsed time from opening a repo cold to identifying and
executing the next concrete step with confidence.

### Suggested measurement protocol

1. Start in a repo context where the latest checkpoint exists.
2. Start timer.
3. Run `python3 -m dockyard resume` (or berth/branch equivalent).
4. Stop timer when operator can state:
   - current objective,
   - first next step,
   - key risk/review note.

Track:

- `ttc_seconds_p50`
- `ttc_seconds_p95`
- sample count and scenario type.

## 2) Resume success rate

**Definition:** percentage of resume invocations that return expected context
without error for intended target scope.

Suggested slices:

- in-repo default resume
- explicit berth resume outside repo
- berth + branch scoped resume
- JSON mode parity.

## 3) Search usefulness rate

**Definition:** percentage of search sessions where returned result is used to
take a concrete next action (manual rubric or instrumentation-backed proxy).

Suggested proxy if manual tagging is unavailable:

- query followed by `resume` / `review open` / commit activity within short
  window.

## 4) Non-interference pass rate

**Definition:** pass rate for tests that assert Dockyard command paths do not
mutate project repositories unless explicitly in run mode.

Primary suite:

```bash
python3 -m pytest tests/test_non_interference.py
```

## 5) Harbor/Search latency

Track p50/p95 latency for dashboard/search query paths using perf smoke runs.

Primary script:

```bash
python3 scripts/perf_smoke.py --json
```

Optional target enforcement:

```bash
python3 scripts/perf_smoke.py --enforce-targets --json
```

## 6) Reproducible quality command pack

Use this exact set for public “health snapshot” updates:

```bash
python3 -m pytest tests/test_cli_integration.py
python3 -m pytest tests/test_non_interference.py
python3 -m pytest tests/test_search.py
python3 -m pytest tests/test_perf_smoke.py tests/test_markdown_roundtrip.py
python3 -m ruff check dockyard tests scripts
```

## 7) Reporting cadence

- Weekly: short quality + perf snapshot.
- Monthly: full metrics rollup with trend notes.

Use `docs/MONTHLY_STATUS_TEMPLATE.md` for standardized reporting.
