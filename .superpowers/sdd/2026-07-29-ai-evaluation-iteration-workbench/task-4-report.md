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

Observed result: `15 passed in 0.22s`. This includes valid fixture parsing,
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

Observed result: `37 passed in 0.39s` after allowing the standard local MySQL
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

## Concerns

None. Future real provider adapters must call the request-aware parser helpers
instead of directly constructing provider response models; those helpers are the
intentional evidence-provenance boundary for Task 12.
