# Task 4 Report: Typed Evaluation Provider and Scoring Rules

## Status

DONE

## Implementation

- Added strict Pydantic contracts for evaluation, attribution, QA-draft requests and
  provider responses. Evaluation responses require exactly the five supported
  dimensions, 0-100 finite scores, a nonblank reason, nonblank evidence, and a
  0-1 confidence value. All models forbid unknown fields.
- Added JSON response parsers that reject malformed, truncated, non-object, and
  non-JSON provider output. They validate evidence against the redacted input
  `NormalizedConversation` before the result can cross the provider boundary.
- Added the runtime-checkable `EvaluationProvider` protocol with `evaluate`,
  `attribute`, and `draft_qa`, plus a deterministic `FakeEvaluationProvider`.
- Added deterministic weighted scoring against persisted-template-compatible
  `weights` and `threshold` fields. Severe factual and compliance errors always
  veto a passing outcome; template weights may not name an unknown dimension.
- Added valid and invalid provider response fixtures and contract/scoring tests.

## Files Changed

- `backend/app/evaluation/contracts.py`
- `backend/app/evaluation/providers.py`
- `backend/app/evaluation/scoring.py`
- `backend/tests/contract/test_provider_contract.py`
- `backend/tests/unit/test_scoring.py`
- `backend/tests/fixtures/provider_responses.json`

## TDD Evidence

### RED

The required focused command was run before production modules existed:

```sh
cd backend
PYTHONPATH=/private/tmp/codex-ai-workbench-python-deps \
/Users/liangjixuan/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
-m pytest tests/contract/test_provider_contract.py tests/unit/test_scoring.py -v
```

Observed result: collection failed with two expected
`ModuleNotFoundError: No module named 'app.evaluation.contracts'` errors.

During self-review, a `NaN` score contract case was added before its fix. Its
single-test command failed with `Failed: DID NOT RAISE ValidationError`, proving
that simple range comparisons accepted a non-finite score. The implementation
then added `math.isfinite` validation.

### GREEN

```sh
cd backend
PYTHONPATH=/private/tmp/codex-ai-workbench-python-deps \
/Users/liangjixuan/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
-m pytest tests/contract/test_provider_contract.py tests/unit/test_scoring.py -v
```

Observed result: `16 passed in 0.25s`. This includes valid fixture parsing,
unknown dimensions, numeric range and NaN rejection, empty reasons, evidence
provenance, malformed/truncated/non-JSON failures, fake-provider determinism,
weighted scoring, and both veto paths.

## Final Verification

```sh
cd backend
TEST_DATABASE_URL='mysql+pymysql://workbench:workbench@127.0.0.1:3307/workbench_test?charset=utf8mb4' \
PYTHONPATH=/private/tmp/codex-ai-workbench-python-deps \
/Users/liangjixuan/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
-m pytest -v
```

Observed result: `38 passed in 0.36s` after allowing the standard local MySQL
test connection.

```sh
cd backend
PYTHONPATH=/private/tmp/codex-ai-workbench-python-deps \
/Users/liangjixuan/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
-m ruff check app alembic tests
```

Observed result: `All checks passed!`

```sh
cd backend
PYTHONPATH=/private/tmp/codex-ai-workbench-python-deps \
/Users/liangjixuan/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
-m ruff format --check app alembic tests
```

Observed result: `31 files already formatted`.

## Self-Review

- Confirmed no MySQL model or migration changes were introduced; scoring accepts
  the existing persisted template shape without queue or persistence orchestration.
- Confirmed external structured responses are parsed through request-aware helpers
  so evidence cannot be accepted solely because its Pydantic structure is valid.
- Confirmed tests fail for unknown dimensions, scores outside the valid range,
  NaN, empty reasons, missing-transcript evidence, malformed JSON, truncated JSON,
  and non-JSON text.
- Confirmed both factual and compliance flags override an otherwise passing score.
- Ran `git diff --check`; it reported no whitespace errors.

## Post-Commit Review Fix

- Post-commit review found that globally strict Pydantic validation rejected the
  legitimate JSON string `"other"` for `ProviderAttribution.root_cause`, because
  the parser has already converted JSON into a mapping before validation.
- Added `test_attribution_parser_accepts_a_json_root_cause` first. It failed with
  `Input should be an instance of RootCause`.
- The `root_cause` field now explicitly accepts the JSON enum representation while
  still rejecting any value outside the existing `RootCause` enum. The focused
  suite then passed with `16 passed in 0.25s`; final full verification passed with
  `38 passed in 0.36s`.

## Concerns

None.

## Fix Round 1

### Implementation

- Added `ValidatedEvaluationProvider` as the public provider boundary around an
  `EvaluationProvider` implementation. It validates the exact returned response
  type and verifies every evaluation, attribution, and QA-draft evidence excerpt
  against the redacted request transcript.
- Hardened `EvaluationRequest` by reusing Task 3's `redact_text` function to
  reject any message that would still be redacted. This preserves the existing
  `[PHONE]`, `[ORDER_ID]`, and `[EMAIL]` placeholders and Task 3's SKU boundary
  behavior rather than duplicating PII regexes.
- Required template weights to name exactly the five evaluation dimensions, be
  finite and within 0..1, and sum to 1 within a `0.000001` Decimal tolerance.
- Replaced arbitrary QA content dictionaries with a strict `QADraftContent`
  model: `question`, `answer`, `applicability`, `handling_steps`,
  `estimated_time`, and `escalation`. Unknown, missing, nested, and blank fields
  are rejected.

### RED Evidence

Before the production changes, these focused commands failed as expected:

```sh
cd backend
PYTHONPATH=/private/tmp/codex-ai-workbench-python-deps \
/Users/liangjixuan/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
-m pytest tests/contract/test_provider_contract.py \
-k 'unredacted_sensitive or provider_qa_draft_rejects' -v
```

Observed result: `5 failed, 14 deselected`. Raw phone, order ID, and email
transcripts were accepted; unknown and nested QA content was also accepted.

```sh
cd backend
PYTHONPATH=/private/tmp/codex-ai-workbench-python-deps \
/Users/liangjixuan/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
-m pytest tests/unit/test_scoring.py::test_scoring_rejects_incomplete_or_invalid_weight_configurations -v
```

Observed result: `5 failed`. Incomplete, negative, NaN, oversized, and
unnormalized weights were accepted or reached uncontrolled downstream errors.

```sh
cd backend
PYTHONPATH=/private/tmp/codex-ai-workbench-python-deps \
/Users/liangjixuan/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
-m pytest tests/contract/test_provider_contract.py::test_validated_provider_boundary_rejects_fabricated_evidence_for_all_operations -v
```

Observed result: `1 failed` with the expected import error for the missing
`ValidatedEvaluationProvider`. The test defines a raw custom provider returning
structurally valid responses with fabricated evidence for all three operations.

### GREEN And Verification

```sh
cd backend
PYTHONPATH=/private/tmp/codex-ai-workbench-python-deps \
/Users/liangjixuan/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
-m pytest tests/contract/test_provider_contract.py tests/unit/test_scoring.py -v
```

Observed result: `29 passed in 0.18s`.

```sh
cd backend
TEST_DATABASE_URL='mysql+pymysql://workbench:workbench@127.0.0.1:3307/workbench_test?charset=utf8mb4' \
PYTHONPATH=/private/tmp/codex-ai-workbench-python-deps \
/Users/liangjixuan/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
-m pytest -v
```

Observed result: `51 passed in 0.38s`.

```sh
cd backend
PYTHONPATH=/private/tmp/codex-ai-workbench-python-deps \
/Users/liangjixuan/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
-m ruff check app alembic tests
PYTHONPATH=/private/tmp/codex-ai-workbench-python-deps \
/Users/liangjixuan/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
-m ruff format --check app alembic tests
```

Observed results: `All checks passed!` and `31 files already formatted`.

### Files Changed

- `backend/app/evaluation/contracts.py`
- `backend/app/evaluation/providers.py`
- `backend/app/evaluation/scoring.py`
- `backend/tests/contract/test_provider_contract.py`
- `backend/tests/unit/test_scoring.py`
- `.superpowers/sdd/2026-07-29-ai-evaluation-iteration-workbench/task-4-report.md`

### Self-Review

- A custom raw provider is rejected at the public validated boundary when any
  evidence is absent from the input transcript; all three provider operations are
  covered by one real behavior test.
- PII detection delegates to Task 3's established redactor, so placeholders stay
  valid and the phone-like SKU regression remains protected.
- Weight validation completes before multiplication, preventing non-finite or
  invalid configurations from reaching outcome construction.
- QA content has no free-form or nested value escape hatch, and the deterministic
  fake provider emits the complete allowlisted structure.

### Concerns

None. Task 5 remains unstarted.
