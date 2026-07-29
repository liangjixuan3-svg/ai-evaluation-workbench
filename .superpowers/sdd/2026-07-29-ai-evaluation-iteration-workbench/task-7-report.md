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

## Fix Round 1

Implemented all six requested review fixes:

- QA generation now treats the representative member's human-confirmed root cause as authoritative while retaining the immutable AI suggestion in generation audit metadata and version evidence.
- Representative transcript and suggestion provenance are selected as one evaluation-result pair. If no member has a paired suggestion, attribution is constructed from the chosen representative's confirmed root cause and evaluation reason/evidence.
- QA approval locks the `qa_drafts` row with `FOR UPDATE` before reading `current_version_number` and loads the exact current version in the same transaction.
- Every successful export call records its actor, including calls that reuse an existing artifact; canonical artifact provenance is unchanged.
- Human confirmation evidence is stripped before persistence and any blank entry is rejected before graph mutation.
- Migration `0003` deduplicates legacy tasks, drafts, and exports before MySQL unique DDL, preserving canonical rows and rewiring versions, evidence/retest links, export items, and audit references. The dirty-`0002` test covers upgrade, downgrade, and re-upgrade in a disposable database.

Test isolation was also corrected after controller full-suite verification exposed committed Task 7 fixture graphs leaking into `test_persist_clusters_is_idempotent_for_an_exact_replay`. Cleanup is scoped to cluster IDs created by `test_attribution_remediation.py` and deletes only those graphs in reverse FK order; no production behavior or global database truncation was added.

### Exact RED/GREEN

- Attribution authority/provenance/evidence RED: `5 failed, 4 deselected in 0.34s`.
- Attribution authority/provenance/evidence GREEN: `5 passed, 4 deselected in 0.30s`.
- Approval lock/export audit RED: `2 failed, 8 deselected in 0.46s`.
- Approval lock/export audit GREEN: `2 passed, 8 deselected in 0.23s`.
- Migration preflight-order RED: `1 failed in 0.28s` because cleanup was not called before unique DDL.
- Migration operation-order GREEN: `2 passed in 0.25s`.
- Isolation RED on a fresh schema: `9 passed, 1 failed in 0.36s`; the final probe found a committed `remediation-*` cluster.
- Isolation GREEN on a fresh schema: `10 passed in 0.41s`.
- Full-suite-order regression GREEN: Task 7 attribution tests followed immediately by `test_persist_clusters_is_idempotent_for_an_exact_replay` produced `11 passed in 0.36s`.

### Controller Evidence

- Correct controller MySQL on port `3307`: migration `0001 -> 0003` passed.
- Focused Task 7 suite before the isolation follow-up: `20 passed`.
- Full suite before the isolation follow-up: `105 passed, 1 failed`; the sole failure was the committed Task 7 fixture graph described above.

### Final Local Verification

- Task 7 focused SQLite suite: `19 passed, 2 skipped in 0.48s`. The skips are the MySQL-only two-session approval and disposable dirty-migration tests covered by controller verification.
- Full unit suite: `31 passed, 1 skipped in 0.35s`; the skipped test requires MySQL/InnoDB row-lock semantics.
- `ruff check .`: `All checks passed!`.
- `ruff format --check .`: `52 files already formatted`.
- `git diff --check`: passed.
- Local MySQL credentials were unavailable, so the post-isolation full MySQL suite is left for the controller rerun as requested.

### Controller Final Verification

- Recreated the isolated MySQL database and applied migrations `0001 -> 0003` successfully.
- Full backend suite: `107 passed in 1.61s`.
- `ruff check .`, `ruff format --check .`, and `git diff --check` passed.
