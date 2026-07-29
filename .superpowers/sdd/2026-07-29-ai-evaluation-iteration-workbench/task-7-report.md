# Task 7 Report: Human Attribution and QA Draft Lifecycle

## Status

Implemented human attribution confirmation, root-cause task routing, provider-validated QA drafting, append-only QA approval, deterministic CSV/JSON export, remediation APIs, audit evidence, and MySQL replay constraints.

## Delivered

- High-confidence clusters support bulk confirmation; medium/low confidence requires one human confirmation per member before routing.
- Original `RootCauseSuggestion` records remain unchanged after human attribution edits. Confirmation, routing, generation, approval, and export append audit payloads with evidence.
- Only fully confirmed `missing_knowledge` clusters can generate QA through the public `EvaluationProvider.draft_qa` boundary using a representative redacted conversation and attribution evidence.
- QA generation is idempotent per QA review task. Approval requires structured business evidence and writes a new immutable version, including edits, instead of changing an earlier version.
- Exports select only a draft's current approved version. CSV uses a fixed UTF-8 header; JSON uses the strict `qa-export-v1` Pydantic schema; content hashes, paths, and metadata are deterministic.
- Migration `0003` adds unique replay constraints for `(cluster_id, task.type)`, `qa_drafts.task_id`, and `(export_records.format, artifact_hash)`.

## Verification

- Focused lifecycle and attribution suite: `8 passed` using a temporary SQLite schema.
- Ruff: `All checks passed` for application, tests, and migration.
- MySQL migration SQL check: `alembic heads` reports `0003 (head)` and `alembic upgrade 0002:0003 --sql` emits all three expected unique constraints.
- Full backend suite on the temporary SQLite schema: `80 passed, 14 failed`. The failures are existing MySQL-specific tests (InnoDB/JSON information schema, `FOR UPDATE SKIP LOCKED`, concurrency, and data migrations) and SQLite transaction isolation differences; no MySQL server or Docker daemon was available in this environment.

## Commit

Pending final verification and commit.

## Final Verification

Controller verification:

- MySQL `alembic upgrade head` succeeded.
- Focused backend tests: `11 passed in 0.41s`.
- Full backend suite: `97 passed in 1.06s`.

Local mechanical checks:

- `cd backend && python3 -m ruff check .`: `All checks passed!`
- `cd backend && python3 -m ruff format --check .`: `51 files already formatted`.
- `git diff --check`: passed.

Workspace hygiene:

- `backend/.venv` is absent.
- `tests/conftest.py` is absent.
- Git status contains only the intended Task 7 implementation files; ignored caches and SDD artifacts remain unstaged.
