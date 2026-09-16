# AI 评测迭代工作台实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single-server AI quality operations workbench that turns sampled customer-service conversations into traceable evaluations, actionable alerts, confirmed root causes, reviewable QA drafts, and verified retest outcomes.

**Architecture:** Use a modular monolith with a React/TypeScript browser client, a FastAPI application, a MySQL/InnoDB database-backed job queue, and a separate worker process importing the same Python application modules. Implement one complete vertical slice first and keep model providers behind typed adapters so deterministic fake responses can drive tests and demos.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, MySQL 8.0+ with InnoDB, PyMySQL, pytest, React 19, TypeScript 5, Vite, React Router, TanStack Query, Vitest, Testing Library, Playwright, Docker Compose.

## Global Constraints

- One maintainer, one server, and fewer than 10,000 source conversations per day.
- Deploy exactly three containers for v1: `web`, `worker`, and `mysql`.
- Use MySQL 8.0+ with InnoDB and `utf8mb4`; queue claiming must use `SELECT ... FOR UPDATE SKIP LOCKED`.
- Do not add Redis, Kafka, microservices, a standalone workflow engine, multi-tenancy, or direct knowledge-base writes.
- The task workbench is the default route; dashboards and pipeline history are supporting views.
- AI may suggest evaluations, root causes, and QA drafts, but humans confirm attribution and approve QA exports.
- QA drafts without cited business evidence cannot be approved.
- Alerts close only after a passing retest or an audited human false-positive decision.
- Every evaluation stores model, model parameters, prompt, template, and rule versions.
- A failed item must not fail its batch; retries resume at the failed stage.
- Source conversations are deduplicated by `(data_source_id, external_conversation_id)` and redacted before model calls.
- Use ASCII in source identifiers and code; Chinese product copy is allowed in UI and fixture data.

## Planned File Structure

```text
backend/
  pyproject.toml
  alembic.ini
  alembic/
    env.py
    versions/0001_initial.py
  app/
    main.py                 # FastAPI composition and static frontend hosting
    config.py               # Environment-backed settings
    db.py                   # SQLAlchemy engine/session lifecycle
    shared/
      enums.py              # Cross-module states and categories
      audit.py              # Audit event writer
    ingestion/
      contracts.py          # Normalized conversation DTOs
      models.py             # Source and conversation persistence
      redaction.py          # PII redaction rules
      sampling.py           # Random, scenario, and risk selection
      service.py            # Idempotent simulated ingestion
      router.py             # Ingestion HTTP endpoints
    evaluation/
      contracts.py          # Typed model request/response contracts
      models.py             # Templates, runs, and results
      providers.py          # LLM provider protocol and fake adapter
      scoring.py            # Weighted score and veto rules
      service.py            # Evaluation orchestration
      router.py             # Run and result endpoints
    jobs/
      models.py             # Database queue rows
      repository.py         # Claim, retry, complete, fail operations
      worker.py             # Polling process and job dispatch
    analysis/
      models.py             # Badcase clusters and root-cause suggestions
      service.py            # Deterministic grouping and attribution
    alerts/
      models.py             # Alert and task persistence
      rules.py              # Spike, scenario, and overall triggers
      service.py            # Merge, transition, and false-positive actions
      router.py             # Workbench and alert detail endpoints
    remediation/
      models.py             # QA drafts, versions, evidence, and exports
      service.py            # Draft generation and approval constraints
      export.py             # CSV and JSON serialization
      router.py             # QA review/export endpoints
    retest/
      models.py             # Retest runs and sample membership
      service.py            # Replay/new-sample comparison and closure
      router.py             # Publish/retest endpoints
    dashboard/
      service.py            # Workbench summary and supporting metrics
      router.py             # Dashboard API
    operations/
      provider.py           # Configured OpenAI-compatible model adapter
      service.py            # Non-secret settings, audit, and stuck-job actions
      router.py             # Settings and operations endpoints
  tests/
    unit/                   # Pure rule and state-machine tests
    integration/            # MySQL-backed repository/service tests
    contract/               # Provider response compatibility tests
    e2e/                    # Full API workflow test
    fixtures/               # Simulated conversations and golden labels
frontend/
  package.json
  vite.config.ts
  src/
    main.tsx                # Browser entry
    app/router.tsx          # Six-section route map
    app/api.ts              # Typed HTTP client
    components/AppShell.tsx # Navigation and page frame
    features/workbench/     # Task-first home page
    features/alerts/        # Alert evidence and attribution UI
    features/remediation/   # QA review and export UI
    features/evaluation/    # Runs, templates, and supporting views
    features/quality/       # Trend and distribution dashboard
    features/badcases/      # Searchable cluster center
    features/settings/      # Sampling, alert, model, and audit operations
    styles/theme.css        # Visual tokens and responsive layout
  tests/                    # Vitest component tests
  e2e/                      # Playwright critical-flow test
deploy/
  Dockerfile.web
  Dockerfile.worker
  docker-compose.yml
  backup.sh
.env.example
Makefile
README.md
```

---

### Task 1: Application Skeleton and Health Contract

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/app/config.py`
- Create: `backend/app/db.py`
- Create: `backend/app/main.py`
- Create: `backend/tests/unit/test_health.py`
- Create: `frontend/package.json`
- Create: `frontend/src/main.tsx`
- Create: `.env.example`
- Create: `Makefile`

**Interfaces:**
- Consumes: Environment variables `APP_ENV`, `DATABASE_URL`, `MODEL_PROVIDER`, and `MODEL_API_KEY`.
- Produces: `app.main:create_app() -> FastAPI`, `app.db:get_session() -> Iterator[Session]`, and `GET /api/health -> {"status":"ok"}`.

- [ ] **Step 1: Write the failing health test**

```python
from fastapi.testclient import TestClient
from app.main import create_app

def test_health_returns_ok() -> None:
    response = TestClient(create_app()).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run the test and verify the missing application failure**

Run: `cd backend && python -m pytest tests/unit/test_health.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'app'`.

- [ ] **Step 3: Add the minimal FastAPI app, settings, dependency manifests, and empty React entry**

```python
# backend/app/main.py
from fastapi import FastAPI

def create_app() -> FastAPI:
    app = FastAPI(title="AI Evaluation Iteration Workbench")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app

app = create_app()
```

Set Python dependencies for FastAPI, Pydantic Settings, SQLAlchemy, PyMySQL, Alembic, pytest, httpx, and ruff. Set frontend scripts for `dev`, `build`, `test`, and `test:e2e`; add React, Vite, TypeScript, React Router, TanStack Query, Vitest, Testing Library, and Playwright.

- [ ] **Step 4: Run backend tests and frontend type checking**

Run: `cd backend && python -m pytest tests/unit/test_health.py -v`

Expected: PASS.

Run: `cd frontend && npm run build`

Expected: Vite build succeeds and emits `frontend/dist`.

- [ ] **Step 5: Commit the skeleton**

```bash
git add backend frontend .env.example Makefile
git commit -m "chore: scaffold workbench applications"
```

### Task 2: Core Persistence, Audit, and State Enums

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/app/config.py`
- Modify: `.env.example`
- Create: `backend/app/shared/enums.py`
- Create: `backend/app/shared/types.py`
- Create: `backend/app/shared/audit.py`
- Create: `backend/app/ingestion/models.py`
- Create: `backend/app/evaluation/models.py`
- Create: `backend/app/analysis/models.py`
- Create: `backend/app/alerts/models.py`
- Create: `backend/app/remediation/models.py`
- Create: `backend/app/retest/models.py`
- Create: `backend/app/jobs/models.py`
- Create: `backend/alembic/versions/0001_initial.py`
- Create: `backend/tests/integration/test_schema.py`

**Interfaces:**
- Consumes: `app.db.Base` and `app.db.session_factory` from Task 1.
- Produces: SQLAlchemy models and enums `AlertStatus`, `TaskType`, `RootCause`, `Confidence`, `QADraftStatus`, and `RunStatus`; `record_audit(session, actor, action, entity_type, entity_id, payload)`.

**Schema contract:**

- IDs are UUID strings stored as `CHAR(36)`. All tables use InnoDB and `utf8mb4`.
- `UTCDateTime` stores UTC-normalized values in MySQL `DATETIME(6)` without an offset and restores timezone-aware UTC values on ORM reads. `utc_now()` is the only Python default for timestamps.
- SQLAlchemy enums use `VARCHAR(32)` (`native_enum=False`) so adding states does not require altering a native MySQL enum.
- `AlertStatus`: `OPEN="open"`, `ANALYZING="analyzing"`, `AWAITING_FIX="awaiting_fix"`, `AWAITING_RETEST="awaiting_retest"`, `RECOVERED="recovered"`, `NOT_RECOVERED="not_recovered"`, `FALSE_POSITIVE="false_positive"`.
- `RootCause`: `MISSING_KNOWLEDGE="missing_knowledge"`, `MISUNDERSTANDING="misunderstanding"`, `PROCESS_FAILURE="process_failure"`, `SERVICE_TONE="service_tone"`, `OTHER="other"`.
- `TaskType`: `ATTRIBUTION_REVIEW="attribution_review"`, `QA_REVIEW="qa_review"`, `PROMPT_OPTIMIZATION="prompt_optimization"`, `PROCESS_INVESTIGATION="process_investigation"`, `TONE_OPTIMIZATION="tone_optimization"`, `EVALUATION_CALIBRATION="evaluation_calibration"`, `RETEST="retest"`.
- `Confidence`: `HIGH="high"`, `MEDIUM="medium"`, `LOW="low"`.
- `QADraftStatus`: `DRAFT="draft"`, `PENDING_REVIEW="pending_review"`, `APPROVED="approved"`, `REJECTED="rejected"`, `REGENERATION_REQUESTED="regeneration_requested"`.
- `RunStatus`: `QUEUED="queued"`, `RUNNING="running"`, `SUCCEEDED="succeeded"`, `PARTIAL="partial"`, `FAILED="failed"`, `MANUAL_REVIEW="manual_review"`.
- Add internal string enums `TaskStatus(open,in_progress,done,cancelled)`, `JobStatus(queued,claimed,succeeded,failed,manual_review)`, `RetestStatus(queued,running,recovered,not_recovered,failed)`, and `RetestCohort(replay,new)` with uppercase member names and the listed lowercase values.
- `DataSource`: id, unique name, kind, config JSON, enabled, created_at, updated_at.
- `Conversation`: id, data_source_id FK, external_id, scenario nullable, status nullable, body JSON, occurred_at, created_at; unique `(data_source_id, external_id)`.
- `SamplingBatch`: id, policy_version, seed, status, selected_count, created_at, started_at nullable, completed_at nullable. `SamplingBatchConversation`: batch_id + conversation_id composite PK, selection_reason.
- `EvaluationTemplate`: id, name, version, weights JSON, threshold `DECIMAL(5,2)`, veto_rules JSON, active, created_at; unique `(name, version)`.
- `PromptVersion`: id, name, version, content TEXT, active, created_at; unique `(name, version)`. `RuleVersion`: id, kind, version, config JSON, active, created_at; unique `(kind, version)`.
- `EvaluationRun`: id, sampling_batch_id nullable FK, template_id FK, prompt_version_id FK, rule_version_id FK, provider, model, model_parameters JSON, status, succeeded_count, failed_count, created_at, started_at nullable, completed_at nullable.
- `EvaluationResult`: id, run_id FK, conversation_id FK, total_score `DECIMAL(5,2)`, dimension_scores JSON, passed, reason TEXT, evidence JSON, confidence, severe_factual_error, severe_compliance_error, created_at; unique `(run_id, conversation_id)`.
- `BadcaseCluster`: id, run_id FK, scenario nullable, weakest_dimension, normalized_reason TEXT, algorithm_version, created_at. `ClusterMember`: cluster_id + evaluation_result_id composite PK, representative_rank nullable, confirmed_root_cause nullable, confirmed_by nullable, confirmed_at nullable.
- `RootCauseSuggestion`: id, cluster_id FK, root_cause, reason TEXT, evidence JSON, confidence, created_at. A cluster may have many suggestions; later services choose the latest.
- `Alert`: id, kind, priority, scenario nullable, root_cause nullable, status, merge_key, baseline_value/current_value `DECIMAL(8,4)`, impact_count, window_started_at, window_ended_at, created_at, updated_at. Index `(status, merge_key)`; do not make merge_key unique because closed alerts retain history. `AlertResult`: alert_id + evaluation_result_id composite PK.
- `Task`: id, type, status, alert_id nullable FK, cluster_id nullable FK, title, priority, payload JSON, created_at, updated_at, completed_at nullable.
- `QADraft`: id, cluster_id FK, task_id nullable FK, status, current_version_number, confidence, created_at, updated_at. `QAVersion`: id, draft_id FK, version_number, content JSON, created_by, approved_by nullable, approved_at nullable, created_at; unique `(draft_id, version_number)`.
- `QAEvidence`: id, qa_version_id FK, source_type, source_ref, excerpt TEXT, conversation_id nullable FK, evaluation_result_id nullable FK, created_at. Evidence belongs to the immutable version it supports, not the mutable draft lifecycle.
- `ExportRecord`: id, format, created_by, artifact_path, artifact_hash, status, created_at. `QAExportItem`: export_id + qa_version_id composite PK.
- `RetestRun`: id, alert_id FK, qa_version_id nullable FK, rule_version_id FK, status, before_pass_rate/replay_pass_rate/new_sample_pass_rate nullable `DECIMAL(8,4)`, created_at, started_at nullable, completed_at nullable.
- `RetestSample`: retest_run_id + conversation_id + cohort composite PK, source_evaluation_result_id nullable FK, retest_evaluation_result_id nullable FK. A sample always references a conversation; result links describe before/after evaluations.
- `Job`: id, kind, payload JSON, status, unique idempotency_key, attempts, max_attempts, run_after, claimed_by nullable, claimed_at nullable, last_error TEXT nullable, created_at, updated_at. Add claim index `(status, run_after, created_at)`.
- `ModelCallRecord`: id, evaluation_run_id nullable FK, provider, model, operation, provider_request_id nullable, input_tokens, output_tokens, estimated_cost `DECIMAL(12,6)`, status, error_code nullable, duration_ms, created_at.
- `AuditEvent`: id, actor, action, entity_type, entity_id, payload JSON, created_at. `record_audit` inserts and flushes an event but leaves commit ownership to the caller.
- ORM `before_update` and `before_delete` listeners reject mutation of `EvaluationResult` and `QAVersion`; do not add database triggers. New evaluations and QA edits create new rows.

- [ ] **Step 1: Write schema invariants as an integration test**

```python
def test_conversation_external_id_is_unique_per_source(session):
    source = DataSource(name="demo", kind="simulated")
    session.add(source)
    session.flush()
    session.add(Conversation(data_source_id=source.id, external_id="c-1", body={}))
    session.commit()
    session.add(Conversation(data_source_id=source.id, external_id="c-1", body={}))
    with pytest.raises(IntegrityError):
        session.commit()
```

- [ ] **Step 2: Run the schema test against the test MySQL database**

Run: `cd backend && TEST_DATABASE_URL=mysql+pymysql://workbench:workbench@127.0.0.1:3306/workbench_test?charset=utf8mb4 python -m pytest tests/integration/test_schema.py -v`

Expected: FAIL because persistence models do not exist.

- [ ] **Step 3: Switch the runtime driver to PyMySQL and implement focused models, foreign keys, indexes, and the initial migration**

```python
class AlertStatus(StrEnum):
    OPEN = "open"
    ANALYZING = "analyzing"
    AWAITING_FIX = "awaiting_fix"
    AWAITING_RETEST = "awaiting_retest"
    RECOVERED = "recovered"
    NOT_RECOVERED = "not_recovered"
    FALSE_POSITIVE = "false_positive"

class RootCause(StrEnum):
    MISSING_KNOWLEDGE = "missing_knowledge"
    MISUNDERSTANDING = "misunderstanding"
    PROCESS_FAILURE = "process_failure"
    SERVICE_TONE = "service_tone"
    OTHER = "other"
```

Replace the Task 1 PostgreSQL driver/default URL with PyMySQL and `mysql+pymysql://workbench:workbench@127.0.0.1:3306/workbench?charset=utf8mb4`. Create immutable evaluation result rows, append-only QA versions, an audit table, and explicit join tables for cluster members, alert results, QA evidence, and retest samples. Add the unique conversation constraint and queue claim indexes. Configure every table for InnoDB and `utf8mb4`.

- [ ] **Step 4: Apply migrations and run schema tests**

Run: `cd backend && alembic upgrade head && python -m pytest tests/integration/test_schema.py -v`

Expected: PASS.

- [ ] **Step 5: Commit persistence contracts**

```bash
git add backend/app backend/alembic backend/tests/integration/test_schema.py
git commit -m "feat: add workbench persistence model"
```

### Task 3: Simulated Ingestion, Redaction, and Sampling

**Files:**
- Create: `backend/app/ingestion/contracts.py`
- Create: `backend/app/ingestion/redaction.py`
- Create: `backend/app/ingestion/sampling.py`
- Create: `backend/app/ingestion/service.py`
- Create: `backend/app/ingestion/router.py`
- Create: `backend/tests/fixtures/conversations.json`
- Create: `backend/tests/unit/test_redaction.py`
- Create: `backend/tests/unit/test_sampling.py`
- Create: `backend/tests/integration/test_ingestion.py`

**Interfaces:**
- Consumes: `DataSource`, `Conversation`, and database session from Tasks 1-2.
- Produces: `ingest_conversations(session, source_id, items) -> IngestionSummary`; `redact_conversation(conversation) -> NormalizedConversation`; `select_sample(items, policy, seed) -> list[UUID]`; `POST /api/ingestion/simulated`.

- [ ] **Step 1: Write failing redaction, deterministic sampling, and deduplication tests**

```python
def test_redaction_removes_phone_and_order_id():
    text = "电话 13800138000，订单 ORD-20260729-8899"
    assert redact_text(text) == "电话 [PHONE]，订单 [ORDER_ID]"

def test_sampling_is_reproducible():
    assert select_sample(items, policy, seed=42) == select_sample(items, policy, seed=42)
```

- [ ] **Step 2: Verify all ingestion tests fail for missing services**

Run: `cd backend && python -m pytest tests/unit/test_redaction.py tests/unit/test_sampling.py tests/integration/test_ingestion.py -v`

Expected: FAIL with missing imports.

- [ ] **Step 3: Implement normalization, PII replacement, three-bucket sampling, and idempotent upsert**

```python
@dataclass(frozen=True)
class SamplingPolicy:
    daily_budget: int
    random_ratio: float
    scenario_ratio: float
    risk_ratio: float
    priority_scenarios: frozenset[str]

def ingest_conversations(session, source_id, items):
    inserted = skipped = 0
    for item in items:
        if conversation_exists(session, source_id, item.external_id):
            skipped += 1
            continue
        session.add(to_model(item, source_id))
        inserted += 1
    session.commit()
    return IngestionSummary(inserted=inserted, skipped=skipped)
```

Fixture data must cover退款进度、物流异常催单, good responses, every root cause, repeated questions, transfer-to-human, negative feedback, and duplicate external IDs.

- [ ] **Step 4: Run ingestion tests**

Run: `cd backend && python -m pytest tests/unit/test_redaction.py tests/unit/test_sampling.py tests/integration/test_ingestion.py -v`

Expected: PASS and duplicate fixture ingestion reports zero new rows on the second call.

- [ ] **Step 5: Commit ingestion**

```bash
git add backend/app/ingestion backend/tests
git commit -m "feat: ingest and sample simulated conversations"
```

### Task 4: Typed Evaluation Provider and Scoring Rules

**Files:**
- Create: `backend/app/evaluation/contracts.py`
- Create: `backend/app/evaluation/providers.py`
- Create: `backend/app/evaluation/scoring.py`
- Create: `backend/tests/contract/test_provider_contract.py`
- Create: `backend/tests/unit/test_scoring.py`
- Create: `backend/tests/fixtures/provider_responses.json`

**Interfaces:**
- Consumes: redacted `NormalizedConversation` from Task 3.
- Produces: `EvaluationProvider.evaluate(request) -> ProviderEvaluation`; `calculate_outcome(provider_result, template) -> EvaluationOutcome`; `FakeEvaluationProvider` for deterministic development and tests.

- [ ] **Step 1: Write failing contract and veto tests**

```python
def test_compliance_veto_fails_even_with_high_weighted_score():
    result = ProviderEvaluation(
        dimensions={"correctness": 95, "completeness": 95, "relevance": 95,
                    "service_experience": 95, "compliance": 20},
        severe_compliance_error=True,
        reason="泄露敏感信息",
        evidence=["用户手机号是..."], confidence=0.96,
    )
    assert calculate_outcome(result, template).passed is False
```

- [ ] **Step 2: Run contract tests and observe missing types**

Run: `cd backend && python -m pytest tests/contract/test_provider_contract.py tests/unit/test_scoring.py -v`

Expected: FAIL with missing contract classes.

- [ ] **Step 3: Implement strict Pydantic responses, provider protocol, fake provider, weighted score, and vetoes**

```python
class EvaluationProvider(Protocol):
    def evaluate(self, request: EvaluationRequest) -> ProviderEvaluation: ...
    def attribute(self, request: AttributionRequest) -> ProviderAttribution: ...
    def draft_qa(self, request: QADraftRequest) -> ProviderQADraft: ...

def calculate_outcome(result, template):
    score = sum(result.dimensions[key] * template.weights[key] for key in template.weights)
    vetoed = result.severe_factual_error or result.severe_compliance_error
    return EvaluationOutcome(score=round(score, 2), passed=not vetoed and score >= template.threshold)
```

Reject unknown dimensions, scores outside 0-100, empty reasons, evidence not found in the input transcript, and confidence outside 0-1.

- [ ] **Step 4: Run contract and scoring tests**

Run: `cd backend && python -m pytest tests/contract/test_provider_contract.py tests/unit/test_scoring.py -v`

Expected: PASS for valid fixtures and explicit validation failures for malformed, truncated, and non-JSON fixtures.

- [ ] **Step 5: Commit evaluation contracts**

```bash
git add backend/app/evaluation backend/tests/contract backend/tests/unit/test_scoring.py backend/tests/fixtures/provider_responses.json
git commit -m "feat: add traceable evaluation contract"
```

### Task 5: Database Job Queue and Resumable Evaluation Pipeline

**Files:**
- Create: `backend/app/jobs/repository.py`
- Create: `backend/app/jobs/worker.py`
- Create: `backend/app/evaluation/service.py`
- Create: `backend/app/evaluation/router.py`
- Create: `backend/tests/integration/test_job_queue.py`
- Create: `backend/tests/integration/test_evaluation_pipeline.py`

**Interfaces:**
- Consumes: sampled conversation IDs, provider contracts, evaluation models, and `record_audit`.
- Produces: `enqueue_job(session, kind, payload, idempotency_key) -> Job`; `claim_jobs(session, worker_id, limit) -> list[Job]`; `run_evaluation_batch(session, run_id, provider) -> RunSummary`; `POST /api/evaluation/runs`.

- [ ] **Step 1: Write failing concurrency, retry, and partial-success tests**

```python
def test_batch_keeps_success_when_one_item_fails(session, flaky_provider, run):
    summary = run_evaluation_batch(session, run.id, flaky_provider)
    assert summary.succeeded == 2
    assert summary.failed == 1
    assert session.get(EvaluationRun, run.id).status == RunStatus.PARTIAL
```

- [ ] **Step 2: Run queue and pipeline tests**

Run: `cd backend && python -m pytest tests/integration/test_job_queue.py tests/integration/test_evaluation_pipeline.py -v`

Expected: FAIL with missing queue operations.

- [ ] **Step 3: Implement `FOR UPDATE SKIP LOCKED`, stage checkpoints, exponential retry metadata, and item isolation**

```python
def claim_jobs(session, worker_id, limit):
    jobs = session.scalars(
        select(Job).where(Job.status == "queued", Job.run_after <= utcnow())
        .order_by(Job.created_at).with_for_update(skip_locked=True).limit(limit)
    ).all()
    for job in jobs:
        job.claim(worker_id)
    session.commit()
    return jobs
```

Persist each result immediately, save provider/model/prompt/template/rule versions, redact before provider calls, and schedule only failed items for retry. After the maximum attempt count, mark the item `manual_review` without failing successful siblings.

- [ ] **Step 4: Run queue and pipeline tests including two concurrent claimers**

Run: `cd backend && python -m pytest tests/integration/test_job_queue.py tests/integration/test_evaluation_pipeline.py -v`

Expected: PASS; two workers never claim the same job.

- [ ] **Step 5: Commit the worker pipeline**

```bash
git add backend/app/jobs backend/app/evaluation backend/tests/integration
git commit -m "feat: run resumable evaluation jobs"
```

### Task 6: Badcase Clustering, Attribution, and Alert Rules

**Files:**
- Create: `backend/app/analysis/service.py`
- Create: `backend/app/alerts/rules.py`
- Create: `backend/app/alerts/service.py`
- Create: `backend/app/alerts/router.py`
- Create: `backend/tests/unit/test_alert_rules.py`
- Create: `backend/tests/integration/test_badcase_alert_flow.py`

**Interfaces:**
- Consumes: failed evaluation results and `EvaluationProvider.attribute`.
- Produces: `cluster_badcases(results) -> list[ClusterDraft]`; `attribute_cluster(session, cluster_id, provider) -> RootCauseSuggestion`; `evaluate_alert_rules(window, baseline, config) -> list[AlertSignal]`; `merge_alert(session, signal) -> Alert`; workbench and alert detail APIs.

- [ ] **Step 1: Write failing tests for minimum sample size, spike priority, merge window, and representative samples**

```python
def test_issue_spike_is_primary_alert():
    signal = evaluate_alert_rules(
        window=metrics(failures=28, samples=100),
        baseline=metrics(failures=9, samples=100),
        config=alert_config(min_samples=30, spike_delta=0.15),
    )[0]
    assert signal.kind == "issue_spike"
    assert signal.priority == "P1"
```

- [ ] **Step 2: Run analysis and alert tests**

Run: `cd backend && python -m pytest tests/unit/test_alert_rules.py tests/integration/test_badcase_alert_flow.py -v`

Expected: FAIL with missing rule evaluator.

- [ ] **Step 3: Implement normalized-reason clustering, 2-3 representative samples, attribution confidence, three alert layers, and alert merging**

```python
ALERT_PRECEDENCE = {"issue_spike": 0, "priority_scenario": 1, "overall_drop": 2}

def representative_members(members):
    return sorted(members, key=lambda item: (-item.confidence, item.created_at))[:3]
```

Use an interpretable deterministic grouping key `(scenario, weakest_dimension, normalized_reason)` for v1; store the grouping algorithm version. Merge open alerts with the same scenario and root-cause key inside the configured window, increasing impact count instead of duplicating cards.

- [ ] **Step 4: Run badcase and alert tests**

Run: `cd backend && python -m pytest tests/unit/test_alert_rules.py tests/integration/test_badcase_alert_flow.py -v`

Expected: PASS; low-volume fluctuations do not alert and merged alerts retain all linked results.

- [ ] **Step 5: Commit analysis and alerts**

```bash
git add backend/app/analysis backend/app/alerts backend/tests
git commit -m "feat: turn badcases into actionable alerts"
```

### Task 7: Human Attribution and QA Draft Lifecycle

**Files:**
- Create: `backend/app/remediation/service.py`
- Create: `backend/app/remediation/export.py`
- Create: `backend/app/remediation/router.py`
- Create: `backend/tests/unit/test_qa_lifecycle.py`
- Create: `backend/tests/integration/test_attribution_remediation.py`

**Interfaces:**
- Consumes: alerts, clusters, root-cause suggestions, provider QA draft output, and audit writer.
- Produces: `confirm_attribution(session, command) -> RemediationTask`; `generate_qa_draft(session, cluster_id, provider) -> QADraft`; `approve_qa(session, draft_id, actor, edits) -> QAVersion`; `export_qa(session, draft_ids, format) -> ExportArtifact`.

- [ ] **Step 1: Write failing human-gate, evidence, versioning, and export tests**

```python
def test_qa_without_business_evidence_cannot_be_approved(session, draft):
    draft.evidence = []
    with pytest.raises(MissingBusinessEvidence):
        approve_qa(session, draft.id, actor="operator-1", edits=None)

def test_only_approved_version_can_be_exported(session, draft):
    with pytest.raises(InvalidQAState):
        export_qa(session, [draft.id], "csv")
```

- [ ] **Step 2: Run remediation tests**

Run: `cd backend && python -m pytest tests/unit/test_qa_lifecycle.py tests/integration/test_attribution_remediation.py -v`

Expected: FAIL because lifecycle services do not exist.

- [ ] **Step 3: Implement attribution confirmation, task routing, append-only QA versions, approval guards, CSV/JSON export, and auditing**

```python
ROOT_CAUSE_TASK = {
    RootCause.MISSING_KNOWLEDGE: TaskType.QA_REVIEW,
    RootCause.MISUNDERSTANDING: TaskType.PROMPT_OPTIMIZATION,
    RootCause.PROCESS_FAILURE: TaskType.PROCESS_INVESTIGATION,
    RootCause.SERVICE_TONE: TaskType.TONE_OPTIMIZATION,
    RootCause.OTHER: TaskType.EVALUATION_CALIBRATION,
}
```

High-confidence clusters may use bulk confirmation; medium/low-confidence clusters require every member to have a human-confirmed root cause. Keep original AI suggestions after human edits.

- [ ] **Step 4: Run remediation tests and inspect exported fixtures**

Run: `cd backend && python -m pytest tests/unit/test_qa_lifecycle.py tests/integration/test_attribution_remediation.py -v`

Expected: PASS; CSV is UTF-8 with a stable header and JSON validates against the export schema.

- [ ] **Step 5: Commit remediation workflow**

```bash
git add backend/app/remediation backend/tests
git commit -m "feat: add reviewed QA remediation workflow"
```

### Task 8: Publish Acknowledgement and Retest Closure

**Files:**
- Create: `backend/app/retest/service.py`
- Create: `backend/app/retest/router.py`
- Create: `backend/tests/unit/test_retest_decision.py`
- Create: `backend/tests/integration/test_retest_flow.py`

**Interfaces:**
- Consumes: approved QA version, linked alert results, post-publication conversations, evaluation service, and alert transition service.
- Produces: `mark_published(session, qa_version_id, actor, published_at) -> RetestRun`; `build_retest_sample(session, run_id) -> RetestSample`; `complete_retest(session, run_id) -> RetestOutcome`.

- [ ] **Step 1: Write failing tests for replay/new samples and closure guards**

```python
def test_failed_retest_reopens_action(session, retest_run):
    outcome = complete_retest(session, retest_run.id, recovered=False)
    assert outcome.alert.status == AlertStatus.NOT_RECOVERED
    assert outcome.follow_up_task.status == "open"

def test_alert_cannot_close_before_retest(session, open_alert):
    with pytest.raises(InvalidAlertTransition):
        transition_alert(session, open_alert.id, AlertStatus.RECOVERED, actor="operator-1")
```

- [ ] **Step 2: Run retest tests**

Run: `cd backend && python -m pytest tests/unit/test_retest_decision.py tests/integration/test_retest_flow.py -v`

Expected: FAIL with missing retest services.

- [ ] **Step 3: Implement publication acknowledgement, separate replay/new cohorts, before/after metrics, and guarded alert transitions**

```python
@dataclass(frozen=True)
class RetestOutcome:
    before_pass_rate: float
    replay_pass_rate: float
    new_sample_pass_rate: float
    recovered: bool
    remaining_failure_reasons: tuple[str, ...]
```

Require minimum sample counts from the rule version. A false-positive close remains a separate audited action requiring a reason; it does not create a fake retest.

- [ ] **Step 4: Run retest and alert-state tests**

Run: `cd backend && python -m pytest tests/unit/test_retest_decision.py tests/integration/test_retest_flow.py -v`

Expected: PASS; only recovered or false-positive paths produce terminal alerts.

- [ ] **Step 5: Commit retest closure**

```bash
git add backend/app/retest backend/tests
git commit -m "feat: verify remediation with retests"
```

### Task 9: Task Workbench and Supporting API

**Files:**
- Create: `backend/app/dashboard/service.py`
- Create: `backend/app/dashboard/router.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/integration/test_workbench_api.py`

**Interfaces:**
- Consumes: evaluation runs, alerts, tasks, QA drafts, retests, and audit events.
- Produces: `get_workbench_summary(session, now) -> WorkbenchSummary`; `GET /api/workbench`; paginated APIs for alerts, badcases, QA drafts, runs, and metrics.

- [ ] **Step 1: Write failing API response and priority-order tests**

```python
def test_workbench_orders_actionable_items(client, seeded_workbench):
    payload = client.get("/api/workbench").json()
    assert payload["priority_items"][0]["priority"] == "P1"
    assert set(payload["counts"]) == {
        "new_alerts", "pending_attributions", "pending_qa", "pending_retests"
    }
```

- [ ] **Step 2: Run the workbench API test**

Run: `cd backend && python -m pytest tests/integration/test_workbench_api.py -v`

Expected: FAIL with 404.

- [ ] **Step 3: Implement task-first query services, stable response DTOs, pagination, filters, and router composition**

```python
class WorkbenchSummary(BaseModel):
    pass_rate: float
    pass_rate_delta: float
    counts: WorkbenchCounts
    priority_items: list[TaskCard]
    recent_activity: list[ActivityItem]
    recent_runs: list[RunSummary]
```

Sort by priority, impact count, duration, then creation time. Every task card returns one `next_action` object with label, method, and path.

- [ ] **Step 4: Run all backend tests**

Run: `cd backend && python -m pytest -v`

Expected: PASS with no API schema snapshots changed unexpectedly.

- [ ] **Step 5: Commit API composition**

```bash
git add backend/app backend/tests/integration/test_workbench_api.py
git commit -m "feat: expose task-first workbench API"
```

### Task 10: Responsive Frontend Shell and Workbench Home

**Files:**
- Create: `frontend/src/app/router.tsx`
- Create: `frontend/src/app/api.ts`
- Create: `frontend/src/components/AppShell.tsx`
- Create: `frontend/src/features/workbench/WorkbenchPage.tsx`
- Create: `frontend/src/features/workbench/TaskCard.tsx`
- Create: `frontend/src/styles/theme.css`
- Create: `frontend/tests/WorkbenchPage.test.tsx`

**Interfaces:**
- Consumes: `GET /api/workbench` response from Task 9.
- Produces: default `/` task workbench and six-section navigation routes.

- [ ] **Step 1: Write a failing component test for the task-first hierarchy**

```tsx
it("shows priority work before recent runs", async () => {
  render(<WorkbenchPage />, { wrapper: testApp({ workbench: fixture }) });
  expect(await screen.findByText("优先处理")).toBeVisible();
  expect(screen.getByText("物流异常类知识缺失激增")).toBeVisible();
  expect(screen.getByText("查看样本并确认归因")).toBeVisible();
});
```

- [ ] **Step 2: Run the component test**

Run: `cd frontend && npm test -- WorkbenchPage.test.tsx`

Expected: FAIL because the page does not exist.

- [ ] **Step 3: Implement responsive shell, expressive non-system typography, task cards, status strip, empty/loading/error states, and six routes**

```tsx
export function WorkbenchPage() {
  const query = useQuery({ queryKey: ["workbench"], queryFn: api.getWorkbench });
  if (query.isPending) return <WorkbenchSkeleton />;
  if (query.isError) return <RetryState onRetry={() => query.refetch()} />;
  return <WorkbenchView summary={query.data} />;
}
```

Use a warm operations-console visual direction with ink, paper, signal cyan, amber, and red tokens; use a subtle grid/paper texture rather than a flat background. Preserve a dense desktop view and convert navigation to a compact mobile drawer below 768px.

- [ ] **Step 4: Run component tests and production build**

Run: `cd frontend && npm test && npm run build`

Expected: PASS; build has no TypeScript errors.

- [ ] **Step 5: Commit the workbench UI**

```bash
git add frontend
git commit -m "feat: add task-first workbench interface"
```

### Task 11: Alert Attribution and QA Review Interfaces

**Files:**
- Create: `frontend/src/features/alerts/AlertDetailPage.tsx`
- Create: `frontend/src/features/alerts/ClusterReview.tsx`
- Create: `frontend/src/features/remediation/QAReviewPage.tsx`
- Create: `frontend/src/features/remediation/RetestSummary.tsx`
- Modify: `frontend/src/app/router.tsx`
- Create: `frontend/tests/AlertDetailPage.test.tsx`
- Create: `frontend/tests/QAReviewPage.test.tsx`

**Interfaces:**
- Consumes: alert detail, confirm attribution, QA lifecycle, export, publish, and retest APIs from Tasks 6-9.
- Produces: `/alerts/:id`, `/improvements/qa/:id`, and embedded retest result flows.

- [ ] **Step 1: Write failing tests for confidence gates and QA evidence gates**

```tsx
it("requires review for low-confidence attribution", async () => {
  render(<AlertDetailPage />, { wrapper: testApp({ alert: lowConfidenceFixture }) });
  expect(await screen.findByRole("button", { name: "批量确认" })).toBeDisabled();
});

it("disables approval when business evidence is missing", async () => {
  render(<QAReviewPage />, { wrapper: testApp({ qa: noEvidenceFixture }) });
  expect(await screen.findByRole("button", { name: "批准" })).toBeDisabled();
});
```

- [ ] **Step 2: Run focused frontend tests**

Run: `cd frontend && npm test -- AlertDetailPage.test.tsx QAReviewPage.test.tsx`

Expected: FAIL because detail pages do not exist.

- [ ] **Step 3: Implement evidence-first alert layout, representative conversation viewer, attribution edits, QA version editor, export controls, publication acknowledgement, and retest comparison**

```tsx
const canBulkConfirm = cluster.confidence === "high";
const canApprove = qa.businessEvidence.length > 0 && qa.status === "pending_review";
```

Require confirmation dialogs for false-positive closure and publication acknowledgement. Use mutation pending states to prevent duplicate submissions and show the server audit event ID after success.

- [ ] **Step 4: Run frontend tests and accessibility checks**

Run: `cd frontend && npm test && npm run build`

Expected: PASS; all controls have accessible names and keyboard focus remains inside dialogs.

- [ ] **Step 5: Commit detail workflows**

```bash
git add frontend
git commit -m "feat: add attribution and QA review flows"
```

### Task 12: Supporting Views, Runtime Configuration, and Real Model Adapter

**Files:**
- Create: `backend/app/operations/provider.py`
- Create: `backend/app/operations/service.py`
- Create: `backend/app/operations/router.py`
- Modify: `backend/app/evaluation/models.py`
- Modify: `backend/app/alerts/models.py`
- Modify: `backend/app/ingestion/models.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/contract/test_openai_compatible_provider.py`
- Create: `backend/tests/integration/test_operations_api.py`
- Create: `frontend/src/features/quality/QualityDashboardPage.tsx`
- Create: `frontend/src/features/evaluation/EvaluationManagementPage.tsx`
- Create: `frontend/src/features/badcases/BadcaseCenterPage.tsx`
- Create: `frontend/src/features/settings/SystemSettingsPage.tsx`
- Modify: `frontend/src/app/router.tsx`
- Create: `frontend/tests/SupportingViews.test.tsx`

**Interfaces:**
- Consumes: provider contracts, metrics, runs, badcase clusters, persisted rule versions, queue jobs, and audit events.
- Produces: `OpenAICompatibleProvider`; `GET/PUT /api/settings/{sampling,evaluation,alerts,model}`; `GET /api/operations/jobs`; `POST /api/operations/jobs/{id}/retry`; `GET /api/operations/audit`; and functional routes for quality, evaluation management, badcases, improvements, and settings.

- [ ] **Step 1: Write failing provider, settings safety, retry, and route tests**

```python
def test_model_api_key_is_never_returned(client, configured_model):
    payload = client.get("/api/settings/model").json()
    assert "api_key" not in payload
    assert payload["api_key_configured"] is True

def test_retry_only_accepts_terminal_failed_job(client, succeeded_job):
    response = client.post(f"/api/operations/jobs/{succeeded_job.id}/retry")
    assert response.status_code == 409
```

```tsx
it("provides all six working primary routes", async () => {
  for (const path of ["/", "/quality", "/evaluations", "/badcases", "/improvements", "/settings"]) {
    expect(routeFor(path)).toBeDefined();
  }
});
```

- [ ] **Step 2: Run focused backend and frontend tests**

Run: `cd backend && python -m pytest tests/contract/test_openai_compatible_provider.py tests/integration/test_operations_api.py -v`

Expected: FAIL with missing operations modules.

Run: `cd frontend && npm test -- SupportingViews.test.tsx`

Expected: FAIL because supporting pages do not exist.

- [ ] **Step 3: Implement the real provider adapter, immutable rule versions, safe configuration APIs, operations actions, and supporting pages**

```python
class OpenAICompatibleProvider(EvaluationProvider):
    def __init__(self, *, base_url: str, api_key: str, model: str, timeout_seconds: float):
        self._client = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout_seconds,
        )
        self.model = model

    def evaluate(self, request: EvaluationRequest) -> ProviderEvaluation:
        response = self._client.post(
            "/v1/chat/completions",
            json=build_structured_evaluation_payload(self.model, request),
        )
        response.raise_for_status()
        return parse_evaluation_response(response.json())
```

Store sampling, evaluation, alert, and model metadata as versioned non-secret rows. Read the base URL and API key from environment variables only; the API returns whether a key is configured but never its value. The quality page shows trends and distributions, evaluation management exposes sources/templates/runs, Badcase Center supports filters and cluster detail links, and settings exposes rule versions plus audit/job operations.

- [ ] **Step 4: Run contract, integration, component, and build verification**

Run: `cd backend && python -m pytest tests/contract/test_openai_compatible_provider.py tests/integration/test_operations_api.py -v`

Expected: PASS with HTTP calls served by `httpx.MockTransport`, including timeout, 429, malformed JSON, and valid structured response cases.

Run: `cd frontend && npm test && npm run build`

Expected: PASS; every primary navigation route renders useful data or a specific empty state.

- [ ] **Step 5: Commit supporting operations**

```bash
git add backend frontend
git commit -m "feat: add quality operations and model settings"
```

### Task 13: Golden Regression, End-to-End Demo, and Single-Server Operations

**Files:**
- Create: `backend/tests/fixtures/golden_dataset.json`
- Create: `backend/tests/contract/test_golden_regression.py`
- Create: `backend/tests/e2e/test_quality_loop.py`
- Create: `frontend/e2e/quality-loop.spec.ts`
- Create: `deploy/Dockerfile.web`
- Create: `deploy/Dockerfile.worker`
- Create: `deploy/docker-compose.yml`
- Create: `deploy/backup.sh`
- Create: `README.md`
- Modify: `Makefile`

**Interfaces:**
- Consumes: the complete backend and frontend vertical slice.
- Produces: `make test`, `make demo`, `make up`, `make backup`, a deterministic golden regression report, and one deployable three-container stack.

- [ ] **Step 1: Write the failing full-loop and regression tests**

```python
def test_complete_quality_loop(api_client, simulated_dataset):
    run = api_client.start_demo_evaluation(simulated_dataset)
    alert = api_client.wait_for_alert(run.id)
    api_client.confirm_missing_knowledge(alert.id)
    qa = api_client.get_generated_qa(alert.id)
    api_client.approve_and_export(qa.id)
    retest = api_client.mark_published_and_retest(qa.id)
    assert retest.status == "recovered"
```

- [ ] **Step 2: Run the full suite before operations files exist**

Run: `make test`

Expected: backend and frontend unit tests pass; full-loop test fails until demo composition and operational commands are added.

- [ ] **Step 3: Add deterministic demo seeding, golden-label tolerance checks, structured logging, usage/cost counters, three-container deployment, backup/restore instructions, and operator runbook**

```yaml
services:
  web:
    build: {context: .., dockerfile: deploy/Dockerfile.web}
    depends_on: [mysql]
  worker:
    build: {context: .., dockerfile: deploy/Dockerfile.worker}
    command: ["python", "-m", "app.jobs.worker"]
    depends_on: [mysql]
  mysql:
    image: mysql:8.4
    command: ["--character-set-server=utf8mb4", "--collation-server=utf8mb4_0900_ai_ci"]
    volumes: ["mysql_data:/var/lib/mysql"]
```

The golden check must compare pass/fail agreement, dimension mean absolute error, root-cause agreement, and severe-error recall against configurable committed thresholds. `README.md` must document prerequisites, environment setup, migrations, local testing without Docker, backup, restore, retrying a stuck job, and changing the model provider.

- [ ] **Step 4: Run all verification commands**

Run: `make test`

Expected: backend unit/integration/contract/E2E tests and frontend component tests pass.

Run: `make demo`

Expected: simulated data creates at least one issue-spike alert, one confirmed missing-knowledge cluster, one approved QA export, and one recovered retest.

Run after Docker is installed: `docker compose -f deploy/docker-compose.yml config`

Expected: configuration is valid and contains exactly `web`, `worker`, and `mysql` services.

- [ ] **Step 5: Commit the deployable vertical slice**

```bash
git add backend frontend deploy README.md Makefile
git commit -m "feat: complete AI quality operations loop"
```

## Final Verification Gate

- [ ] Run `git status --short` and confirm no unexpected files.
- [ ] Run `make test` and record the passing backend/frontend test counts.
- [ ] Run `make demo` and record the alert ID, QA export ID, and recovered retest ID.
- [ ] Run `cd frontend && npm run build` and record the generated asset summary.
- [ ] If Docker is available, run `docker compose -f deploy/docker-compose.yml config` and `docker compose -f deploy/docker-compose.yml up --build`; verify `/api/health` and the default task workbench route.
- [ ] Review the implementation against every acceptance criterion in `docs/产品设计/00-产品总览/产品总体设计.md` before claiming completion.
