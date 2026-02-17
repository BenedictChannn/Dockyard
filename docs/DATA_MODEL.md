# Dockyard Data Model (MVP)

Dockyard uses SQLite as an index and Markdown files for checkpoint payload
persistence.

## Entities

## Berth

Repository identity.

| Field | Type | Notes |
|---|---|---|
| `repo_id` | text (pk) | stable hash (any configured remote URL preferred, path fallback) |
| `name` | text | inferred from repo root dir |
| `root_path` | text | absolute path |
| `remote_url` | text nullable | optional |
| `created_at` | text | ISO timestamp |
| `updated_at` | text | ISO timestamp |

## Slip

Branch/workstream under a berth.

| Field | Type | Notes |
|---|---|---|
| `repo_id` | text | fk -> berths |
| `branch` | text | branch key |
| `last_checkpoint_id` | text nullable | newest checkpoint |
| `status` | text | `green`/`yellow`/`red` |
| `tags_json` | text | serialized tag list |
| `updated_at` | text | ISO timestamp |

Primary key: `(repo_id, branch)`

## Checkpoint

Core captured checkpoint payload.

| Field | Type | Notes |
|---|---|---|
| `id` | text (pk) | checkpoint id |
| `repo_id` | text | fk -> berths |
| `branch` | text | branch |
| `created_at` | text | ISO timestamp |
| `objective` | text | required |
| `decisions` | text | required |
| `next_steps_json` | text | array (1-3 intended) |
| `risks_review` | text | required |
| `resume_commands_json` | text | array (0-5 intended) |
| `git_dirty` | int | 0/1 |
| `head_sha` | text | commit sha |
| `head_subject` | text | commit subject |
| `recent_commits_json` | text | recent commit summaries |
| `diff_files_changed` | int | aggregate |
| `diff_insertions` | int | aggregate |
| `diff_deletions` | int | aggregate |
| `touched_files_json` | text | array |
| `diff_stat_text` | text | raw `git diff --stat HEAD` |
| `tests_run` | int | 0/1 |
| `tests_command` | text nullable | optional |
| `tests_timestamp` | text nullable | optional |
| `build_ok` | int | 0/1 |
| `build_command` | text nullable | optional |
| `build_timestamp` | text nullable | optional |
| `lint_ok` | int | 0/1 |
| `lint_command` | text nullable | optional |
| `lint_timestamp` | text nullable | optional |
| `smoke_ok` | int | 0/1 |
| `smoke_notes` | text nullable | optional |
| `smoke_timestamp` | text nullable | optional |
| `tags_json` | text | serialized tags |

## Review Item

Cross-repo review ledger item.

| Field | Type | Notes |
|---|---|---|
| `id` | text (pk) | review id |
| `repo_id` | text | fk -> berths |
| `branch` | text | branch |
| `checkpoint_id` | text nullable | associated checkpoint |
| `created_at` | text | ISO timestamp |
| `reason` | text | enum-ish + free text |
| `severity` | text | `low`/`med`/`high` |
| `status` | text | `open`/`done` |
| `notes` | text nullable | optional |
| `files_json` | text | related files |

## Link

URL attached to branch context.

| Field | Type | Notes |
|---|---|---|
| `id` | text (pk) | link id |
| `repo_id` | text | fk -> berths |
| `branch` | text | branch |
| `url` | text | attached URL |
| `created_at` | text | ISO timestamp |

## Markdown storage

Path format:

`checkpoints/<repo_id>/<branch>/<checkpoint_id>.md`

Contains:

- objective
- decisions/findings
- next steps
- risks/review notes
- resume commands
- git evidence snapshot
- verification block

Parser normalization notes:

- `next steps` accepts numbered list markers in `1.`, `1)`, or `(1)` style.
- Numbered next-step markers may include optional whitespace between marker
  and content (for example, `1. step` and `1.step` are both accepted).
- `next steps` also accepts markdown bullet markers (`-`, `*`, `+`) as a
  parser fallback for manually edited checkpoint files.
- Next-step bullet markers accept optional spacing after delimiter
  (for example, both `- step` and `-step` are accepted).
- `next steps` also accepts plain non-bulleted lines as list items in manually
  edited checkpoint files.
- Structural markdown separator/fence lines (`---`, `***`, `___`, ``````,
  `~~~`, and language-tagged fences like `````bash`) are ignored within
  `next steps` (including longer 4+ marker variants).
- Next-step parser strips checklist prefixes from markdown list entries
  (for example, `- [ ] step` and `1. [x] step` normalize to `step`).
- Checklist prefix stripping for next steps requires separator spacing
  (`[x] step` is stripped, `[x]step` remains literal).
- `resume commands` accepts `-`, `*`, or `+` bullet markers.
- `resume commands` also accepts numbered list markers (`1.`, `1)`, `(1)`) as a
  parser fallback for manually edited checkpoint files.
- Resume command bullets may be backtick-wrapped (for renderer parity) or
  plain text when manually edited.
- Resume command bullets accept optional spacing after bullet delimiters
  (for example, both `- cmd` and `-cmd` parse correctly).
- `resume commands` also accepts plain non-bulleted command lines in manually
  edited checkpoint files.
- Malformed backtick command lines are ignored for both bulleted and plain-line
  resume command entries.
- Structural markdown separator/fence lines (`---`, `***`, `___`, ``````,
  `~~~`, and language-tagged fences like `````bash`) are ignored within
  `resume commands` (including longer 4+ marker variants).
- Resume command parser strips checklist prefixes only when they include
  separator spacing (for example, `- [x] cmd` -> `cmd`; `- [x]cmd` remains
  literal).
- Section heading lookup normalizes spacing and slash variants (for example,
  `Decisions / Findings`, `Risks/Review Needed`, and `Resume   Commands`).
- Section heading lookup is case-insensitive for known Dockyard sections.
- Known section heading lookups ignore trailing colon suffixes
  (for example, `Objective:`).
- Known section heading lookups also tolerate compact ATX forms like
  `##Objective##` (no spacing after the marker, optional closing hashes).
- Known section heading lookups work with deeper ATX levels (`##`, `###`,
  `####`, etc.), not only level-2 headings.
- Parser also accepts singular heading aliases for known sections
  (for example, `Decision/Finding`, `Next Step`, and `Resume Command`).
- Decisions heading aliases also accept hyphen-separated forms
  (`Decisions-Findings`, `Decision-Finding`).
- Decisions heading aliases also accept ampersand-separated forms
  (`Decisions & Findings`, `Decision & Finding`).
- Decisions heading aliases also accept space-separated forms
  (`Decisions Findings`, `Decision Finding`).
- Risks heading aliases also accept hyphen-separated forms
  (`Risks - Review Needed`, `Risk - Review Needed`).
- Risks heading aliases also accept ampersand-separated forms
  (`Risks & Review Needed`, `Risk & Review Needed`).
- Risks heading aliases also accept space-separated forms
  (`Risks Review Needed`, `Risk Review Needed`).
- Symbolic heading delimiters (`/`, `-`, `&`, `:`, `+`) are normalized
  equivalently,
  including tight forms without surrounding spaces (for example,
  `Decision&Finding`, `Risks-Review Needed`, `Decision:Finding`,
  `Decision+Finding`).
- Unicode dash separators (`–`, `—`) are also normalized in heading labels
  (for example, `Next–Steps`, `Decision—Finding`).
- This delimiter normalization also applies to list-section headings such as
  `Next-Steps` and `Resume&Commands`.
- Known heading labels may be wrapped with simple markdown emphasis markers
  (`**...**`, `__...__`, `` `...` ``, `*...*`, `_..._`).
- Nested combinations of these wrappers are also normalized (for example,
  `**`Objective`**`).
- Triple-emphasis heading labels (for example, `***Objective***`) are also
  normalized.
