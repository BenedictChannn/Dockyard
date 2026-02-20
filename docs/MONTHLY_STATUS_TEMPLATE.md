# Dockyard Monthly Status Template

_Month:_ `<YYYY-MM>`  
_Prepared by:_ `<name>`  

## 1) Executive summary

- What improved this month:
  - `<bullet>`
  - `<bullet>`
- What remains highest priority:
  - `<bullet>`

## 2) Product state snapshot

- Core workflow status (`save`/`resume`/`search`/`harbor`): `<green|yellow|red>`
- Safety model status (non-invasive by default): `<green|yellow|red>`
- Documentation freshness: `<green|yellow|red>`

## 3) Reliability and safety

| Signal | Result | Notes |
|---|---:|---|
| Integration suite (`tests/test_cli_integration.py`) | `<count passed>` | `<notes>` |
| Non-interference suite (`tests/test_non_interference.py`) | `<count passed>` | `<notes>` |
| Search suite (`tests/test_search.py`) | `<count passed>` | `<notes>` |
| Perf+roundtrip suites | `<count passed>` | `<notes>` |
| Ruff lint | `<pass/fail>` | `<notes>` |

## 4) Metrics

| Metric | Current | Prior | Delta | Notes |
|---|---:|---:|---:|---|
| Time-to-Context (p50 seconds) | `<value>` | `<value>` | `<delta>` | `<notes>` |
| Time-to-Context (p95 seconds) | `<value>` | `<value>` | `<delta>` | `<notes>` |
| Resume success rate | `<value>%` | `<value>%` | `<delta>` | `<notes>` |
| Search usefulness rate | `<value>%` | `<value>%` | `<delta>` | `<notes>` |
| Non-interference pass rate | `<value>%` | `<value>%` | `<delta>` | `<notes>` |
| Harbor latency p95 (ms) | `<value>` | `<value>` | `<delta>` | `<notes>` |
| Search latency p95 (ms) | `<value>` | `<value>` | `<delta>` | `<notes>` |

## 5) Public proof assets

- Demo video: `<link/path>`
- Transcript: `<link/path>`
- Launch thread: `<link>`
- Carousel deck: `<link>`

## 6) User feedback summary

- Top positive themes:
  - `<bullet>`
- Top pain points:
  - `<bullet>`
- Highest-impact asks:
  - `<bullet>`

## 7) Next 30-day priorities

1. `<priority 1>`
2. `<priority 2>`
3. `<priority 3>`

## 8) Appendix: reproducibility command log

```bash
python3 -m pytest tests/test_cli_integration.py
python3 -m pytest tests/test_non_interference.py
python3 -m pytest tests/test_search.py
python3 -m pytest tests/test_perf_smoke.py tests/test_markdown_roundtrip.py
python3 -m ruff check dockyard tests scripts
python3 scripts/perf_smoke.py --json
```
