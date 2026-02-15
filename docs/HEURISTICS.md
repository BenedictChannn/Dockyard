# Dockyard Heuristics (MVP)

Dockyard uses deterministic (non-LLM) heuristics for review suggestion and slip
status computation.

## Review suggestion triggers

A review suggestion is generated when **any** of the following is true:

1. Risky path touched:
   - `auth/`
   - `infra/`
   - `.github/`
   - `terraform/`
   - `migrations/`
   - `payments/`
   - `security/`
2. `files_changed >= 15`
3. `insertions + deletions >= 400`
4. tests not run and diff is non-trivial
5. branch name starts with `release/` or `hotfix/`

### Non-trivial diff

Current implementation treats a diff as non-trivial if:

- files changed ≥ 3, or
- insertions + deletions ≥ 80

## Review severity mapping

- **high**: risky paths, very large churn, release/hotfix branch
- **med**: other triggered conditions
- **low**: manual/non-triggered item

## Slip status (Green / Yellow / Red)

Status is computed from latest checkpoint + open reviews.

## Green

- tests run = true
- build ok = true
- no high-severity open review
- no open reviews

## Yellow

- partial verification missing OR open low/med reviews

## Red

Any of:

- high-severity open review exists
- risky paths touched AND tests not run
- large diff and no review coverage

## Rationale

This model biases toward review safety while remaining simple and transparent.
All status outcomes are explainable from stored fields without model inference.

## Configuration

Heuristic thresholds and patterns can be overridden via `config.toml` in the
Dockyard data directory.

Example:

```toml
[review_heuristics]
files_changed_threshold = 12
churn_threshold = 300
non_trivial_files_threshold = 2
non_trivial_churn_threshold = 50
branch_prefixes = ["release/", "hotfix/", "urgent/"]
risky_path_patterns = [
  "(^|/)auth/",
  "(^|/)security/",
  "(^|/)critical/"
]
```
