# JSON 数据采集与真实评测实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让运营人员从任意结构 JSON 文件完成字段映射、预览、真实入库，并通过 OpenAI 兼容接口执行可恢复的客服质量评测。

**Architecture:** 在现有 FastAPI 模块化单体中新增导入会话、OpenAI 兼容传输和评测操作编排三个边界；复用现有 MySQL、抽样、评测结果、任务队列、Badcase 与告警模块。React 增加数据采集、发起评测和运行详情页面，通过稳定 API 轮询状态。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy 2、Alembic、MySQL 8+、Pydantic、HTTPX、React 19、TypeScript、TanStack Query、Vite 6。

## 全局约束

- 单个 JSON 文件不超过 20 MB、单批不超过 10,000 条对话。
- 只支持 UTF-8 JSON；本轮不支持 CSV、Excel 和 HTTP 定时采集。
- 原始未映射字段保留；发送模型前必须使用现有脱敏逻辑。
- `LLM_API_KEY` 只能来自服务器环境变量，不进入数据库、前端、日志或错误响应。
- 自动测试使用假传输，不调用付费模型 API。
- 归因确认、QA 批准和发布仍由人工执行。
- 每个任务完成独立测试与提交；不得修改历史 Alembic 迁移。

---

### Task 1: 导入会话数据模型与迁移

**Files:**
- Create: `backend/app/imports/models.py`
- Create: `backend/alembic/versions/0004_add_json_import_sessions.py`
- Modify: `backend/alembic/env.py`
- Test: `backend/tests/integration/test_import_schema.py`

**Interfaces:**
- Produces: `ImportSession`，保存文件哈希、原始 JSON、候选数组路径、映射、状态、记录数、确认数据源和 24 小时过期时间。
- Consumes: `DataSource.id` 作为确认后的数据来源。

- [ ] **Step 1: 写入失败的迁移测试**

```python
def test_import_session_schema_is_mysql_native(engine):
    columns = inspect(engine).get_columns("import_sessions")
    assert {column["name"] for column in columns} >= {
        "id", "filename", "file_hash", "status", "document",
        "candidate_paths", "mapping", "result_summary", "record_count", "error_count",
        "confirmed_source_id", "expires_at", "created_at", "confirmed_at",
    }
    assert next(column for column in columns if column["name"] == "document")["type"].__class__.__name__ == "JSON"
```

- [ ] **Step 2: 验证测试先失败**

Run: `cd backend && python -m pytest tests/integration/test_import_schema.py -v`
Expected: FAIL because table `import_sessions` does not exist.

- [ ] **Step 3: 实现模型与 `0004` 迁移**

```python
class ImportSession(Base):
    __tablename__ = "import_sessions"
    __table_args__ = (
        UniqueConstraint("file_hash", name="uq_import_session_file_hash"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[str] = uuid_primary_key()
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    document: Mapped[Any] = mapped_column(JSON, nullable=False)
    candidate_paths: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    mapping: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    result_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    record_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    confirmed_source_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("data_sources.id", name="fk_import_session_source"), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
```

Migration requirements: InnoDB, `utf8mb4`, native JSON columns, named FK and unique constraint; downgrade drops only `import_sessions`.

- [ ] **Step 4: 运行迁移升级、降级、再升级及测试**

Run: `cd backend && python -m alembic upgrade head && python -m pytest tests/integration/test_import_schema.py -v`
Expected: PASS; disposable migration test confirms `0003 -> 0004 -> 0003 -> 0004`.

- [ ] **Step 5: 提交**

```bash
git add backend/app/imports backend/alembic backend/tests/integration/test_import_schema.py
git commit -m "feat: persist JSON import sessions"
```

### Task 2: 任意 JSON 结构发现与字段映射

**Files:**
- Create: `backend/app/imports/contracts.py`
- Create: `backend/app/imports/parser.py`
- Test: `backend/tests/unit/test_json_import_parser.py`

**Interfaces:**
- Produces: `discover_record_arrays(document, max_depth=8) -> list[ArrayCandidate]`。
- Produces: `suggest_mapping(records) -> ImportMapping`。
- Produces: `normalize_records(records, mapping, timezone_name, error_policy) -> NormalizationResult`。
- `ImportMapping` 支持 `messages` 与 `qa_pair` 两种模式。

- [ ] **Step 1: 写结构发现和双模式映射失败测试**

```python
def test_discovers_nested_records_and_normalizes_message_array():
    document = {"result": {"conversations": [{
        "sessionId": "s-1", "createdAt": "2026-07-30T09:00:00+08:00",
        "turns": [{"speaker": "customer", "text": "退款进度？"},
                  {"speaker": "bot", "text": "请耐心等待。"}],
        "extra": {"channel": "app"},
    }]}}
    assert discover_record_arrays(document)[0].path == "result.conversations"
    mapping = ImportMapping(
        record_path="result.conversations", id_path="sessionId",
        occurred_at_path="createdAt", message_mode="messages",
        messages_path="turns", role_path="speaker", content_path="text",
    )
    result = normalize_records(document, mapping, "Asia/Shanghai", "block")
    assert result.items[0].body["messages"][0] == {"role": "user", "content": "退款进度？"}
    assert result.items[0].body["raw"]["extra"] == {"channel": "app"}
```

```python
def test_normalizes_question_answer_and_uses_stable_hash_id():
    mapping = ImportMapping(
        record_path="$", occurred_at_path="time", message_mode="qa_pair",
        question_path="question", answer_path="answer",
    )
    first = normalize_records([{"time": 1722301200, "question": "Q", "answer": "A"}], mapping, "Asia/Shanghai", "block")
    second = normalize_records([{"time": 1722301200, "question": "Q", "answer": "A"}], mapping, "Asia/Shanghai", "block")
    assert first.items[0].external_id == second.items[0].external_id
```

- [ ] **Step 2: 验证解析测试先失败**

Run: `cd backend && python -m pytest tests/unit/test_json_import_parser.py -v`
Expected: FAIL with missing `app.imports.parser`.

- [ ] **Step 3: 实现有界路径读取、候选排序和本地字段建议**

```python
ID_NAMES = ("conversation_id", "conversationId", "session_id", "sessionId", "id")
TIME_NAMES = ("occurred_at", "occurredAt", "created_at", "createdAt", "timestamp", "time")
MESSAGE_NAMES = ("messages", "turns", "records")

def discover_record_arrays(document: Any, max_depth: int = 8) -> list[ArrayCandidate]:
    candidates: list[ArrayCandidate] = []
    _walk_arrays(document, path="$", depth=0, max_depth=max_depth, output=candidates)
    return sorted(candidates, key=lambda item: (-item.object_ratio, -item.length, item.path))
```

Role normalization maps `customer/human/user` to `user` and `bot/assistant/agent` to `assistant`; unknown roles remain unchanged. Unix seconds, Unix milliseconds and timezone-aware ISO-8601 are accepted. Naive time requires `timezone_name` and is converted to aware UTC.

- [ ] **Step 4: 实现错误策略和限制测试**

```python
def test_block_policy_reports_rows_without_returning_items():
    result = normalize_records(document, mapping, "Asia/Shanghai", "block")
    assert result.items == ()
    assert result.errors[0].row_index == 1

def test_skip_policy_keeps_valid_rows():
    result = normalize_records(document, mapping, "Asia/Shanghai", "skip")
    assert len(result.items) == 1
    assert len(result.errors) == 1
```

Reject nesting deeper than 8, more than 10,000 records, string fields longer than their database limits, empty transcripts and non-object records.

- [ ] **Step 5: 运行解析测试并提交**

Run: `cd backend && python -m pytest tests/unit/test_json_import_parser.py -v`
Expected: PASS.

```bash
git add backend/app/imports backend/tests/unit/test_json_import_parser.py
git commit -m "feat: map arbitrary JSON conversations"
```

### Task 3: 上传预览与确认入库 API

**Files:**
- Create: `backend/app/imports/service.py`
- Create: `backend/app/imports/router.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/integration/test_json_import_api.py`

**Interfaces:**
- Produces: `POST /api/imports/json`，接收 `{filename, document}` 并返回导入会话和候选路径。
- Produces: `GET /api/imports?status=confirmed`，返回可用于评测的导入批次、数据源和可用对话数。
- Produces: `POST /api/imports/{id}/preview`，接收映射、时区和错误策略，返回最多 10 条原始/标准化/脱敏预览。
- Produces: `POST /api/imports/{id}/confirm`，接收 `source_name`、`actor`，返回入库统计。
- Produces: `DELETE /api/imports/{id}`，仅放弃未确认会话。

- [ ] **Step 1: 写失败的 API 测试**

```python
def test_upload_preview_confirm_is_idempotent(client, session):
    uploaded = client.post("/api/imports/json", json={
        "filename": "dialogs.json", "document": SAMPLE_DOCUMENT,
    }).json()
    preview = client.post(f"/api/imports/{uploaded['id']}/preview", json=MAPPING).json()
    assert preview["valid_count"] == 2
    assert preview["items"][0]["redacted_messages"][0]["content"] == "手机号 [PHONE]"
    first = client.post(f"/api/imports/{uploaded['id']}/confirm", json={
        "source_name": "7月客服导出", "actor": "operator-1",
    }).json()
    second = client.post(f"/api/imports/{uploaded['id']}/confirm", json={
        "source_name": "7月客服导出", "actor": "operator-1",
    }).json()
    assert first == second
    assert first["inserted"] == 2
```

- [ ] **Step 2: 验证 API 测试先失败**

Run: `cd backend && python -m pytest tests/integration/test_json_import_api.py -v`
Expected: FAIL with 404.

- [ ] **Step 3: 实现上传与预览服务**

```python
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
MAX_RECORDS = 10_000
IMPORT_TTL = timedelta(hours=24)

def create_import_session(session: Session, filename: str, document: Any) -> ImportSession:
    encoded = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) > MAX_DOCUMENT_BYTES:
        raise ImportLimitError("JSON 文件不能超过 20 MB")
    file_hash = sha256(encoded).hexdigest()
    # Return an existing unexpired session for an exact replay.
```

Preview persists the validated mapping and error count but does not create `DataSource` or `Conversation` rows.

- [ ] **Step 4: 实现事务性确认和审计**

```python
def confirm_import(session: Session, import_id: str, source_name: str, actor: str) -> ImportSummary:
    import_session = session.scalar(
        select(ImportSession).where(ImportSession.id == import_id).with_for_update()
    )
    if import_session.status == "confirmed":
        return ImportSummary.model_validate(import_session.result_summary)
    mapping = ImportMapping.model_validate(import_session.mapping)
    result = normalize_records(
        import_session.document,
        mapping,
        mapping.timezone_name,
        mapping.error_policy,
    )
    source = DataSource(name=source_name, kind="json_upload", config={"file_hash": import_session.file_hash})
    session.add(source)
    session.flush()
    summary = ingest_conversations(session, source.id, list(result.items))
```

Set `import_session.result_summary` before the final commit. Refactor `ingest_conversations(..., commit: bool = True)` so the import service owns the final transaction; existing callers retain current behavior. Record `json_import_confirmed` with file hash, mapping, inserted/skipped/error counts and actor.

Creating or listing import sessions deletes unconfirmed sessions whose `expires_at` is older than the current UTC time. Confirmed sessions retain lineage and are never removed by this cleanup.

- [ ] **Step 5: 运行导入、原有采集和完整后端测试并提交**

Run: `cd backend && python -m pytest tests/integration/test_json_import_api.py tests/integration/test_ingestion.py -v`
Expected: PASS.

```bash
git add backend/app/imports backend/app/ingestion backend/app/main.py backend/tests
git commit -m "feat: import mapped JSON conversations"
```

### Task 4: OpenAI 兼容真实模型适配器

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/app/config.py`
- Create: `backend/app/evaluation/openai_compatible.py`
- Modify: `backend/app/evaluation/providers.py`
- Modify: `backend/app/evaluation/router.py`
- Test: `backend/tests/unit/test_openai_compatible_provider.py`

**Interfaces:**
- Produces: `OpenAICompatibleTransport(settings, client)`，实现现有 `_EvaluationTransport`。
- Produces: `build_evaluation_provider(settings) -> EvaluationProvider`。
- Produces: `GET /api/evaluation/provider-status`，只返回 `configured`、`base_url`、`model` 和安全错误摘要。

- [ ] **Step 1: 写请求、响应验证和密钥泄漏失败测试**

```python
def test_openai_transport_posts_redacted_transcript_and_parses_json():
    transport = OpenAICompatibleTransport(settings, httpx.Client(transport=fake_transport))
    response = transport.evaluate(redacted_request)
    assert response.dimensions["correctness"] == 90
    sent = json.loads(captured_request.content)
    assert sent["model"] == "judge-model"
    assert "13800138000" not in captured_request.content.decode()

def test_provider_error_never_contains_api_key():
    with pytest.raises(ModelProviderError) as error:
        transport.evaluate(redacted_request)
    assert settings.llm_api_key not in str(error.value)
```

- [ ] **Step 2: 验证适配器测试先失败**

Run: `cd backend && python -m pytest tests/unit/test_openai_compatible_provider.py -v`
Expected: FAIL with missing adapter.

- [ ] **Step 3: 增加配置和 HTTPX 生产依赖**

```python
class Settings(BaseSettings):
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_timeout_seconds: float = 30.0
```

`backend/pyproject.toml` adds `httpx>=0.27` to production dependencies. `.env.example` documents the three required variables with empty values.

- [ ] **Step 4: 实现 Chat Completions 请求和严格 JSON 响应**

```python
payload = {
    "model": settings.llm_model,
    "temperature": 0,
    "response_format": {"type": "json_object"},
    "messages": [
        {"role": "system", "content": EVALUATION_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(transcript, ensure_ascii=False)},
    ],
}
response = client.post(
    f"{settings.llm_base_url.rstrip('/')}/chat/completions",
    headers={"Authorization": f"Bearer {settings.llm_api_key}"},
    json=payload,
    timeout=settings.llm_timeout_seconds,
)
```

Parse `choices[0].message.content` with existing `parse_evaluation_response`, `parse_attribution_response`, or `parse_qa_draft_response` according to the operation. `EvaluationProvider` remains responsible for the public type and transcript-evidence validation boundary. Attribution and QA methods use separate fixed system prompts.

- [ ] **Step 5: 运行适配器及评分测试并提交**

Run: `cd backend && python -m pytest tests/unit/test_openai_compatible_provider.py tests/unit/test_scoring.py -v`
Expected: PASS.

```bash
git add backend/pyproject.toml backend/app/config.py backend/app/evaluation backend/tests/unit/test_openai_compatible_provider.py .env.example
git commit -m "feat: call OpenAI-compatible evaluation models"
```

### Task 5: 一键评测编排、Worker 与进度 API

**Files:**
- Create: `backend/app/operations/service.py`
- Create: `backend/app/operations/router.py`
- Create: `backend/app/operations/worker.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/dashboard/service.py`
- Test: `backend/tests/integration/test_real_evaluation_operation.py`

**Interfaces:**
- Produces: `POST /api/operations/evaluations`，接收 `import_id`、`sample_size`、`strategy`、`threshold`、`seed`。
- Produces: `GET /api/operations/evaluations/{run_id}`，返回阶段、数量、指标、错误摘要。
- Produces: `GET /api/operations/evaluations/{run_id}/results?offset=0&limit=50`。
- Produces: `python -m app.operations.worker`，持续领取现有 MySQL 队列任务。
- Produces: `get_or_create_template`、`get_or_create_prompt`、`get_or_create_rule`、`create_sampling_batch` 和 `enqueue_evaluation_run`，作为运行创建的私有幂等步骤。
- Produces: `create_alerts_for_run(session, run_id, clusters) -> list[Alert]`，按场景汇总当前运行失败结果，并通过现有 `merge_alert` 生成可追溯告警。

- [ ] **Step 1: 写创建运行和恢复进度失败测试**

```python
def test_create_operation_samples_import_and_enqueues_real_run(client, confirmed_import):
    response = client.post("/api/operations/evaluations", json={
        "import_id": confirmed_import.id,
        "sample_size": 20,
        "strategy": "risk_first",
        "threshold": 75,
        "seed": 20260730,
    })
    assert response.status_code == 201
    detail = client.get(f"/api/operations/evaluations/{response.json()['run_id']}").json()
    assert detail["stage"] == "queued"
    assert detail["sample_count"] == 20
```

- [ ] **Step 2: 验证操作 API 测试先失败**

Run: `cd backend && python -m pytest tests/integration/test_real_evaluation_operation.py -v`
Expected: FAIL with 404.

- [ ] **Step 3: 实现默认版本、抽样批次和幂等运行创建**

```python
def create_evaluation_operation(session: Session, command: StartEvaluation) -> EvaluationRun:
    import_session = require_confirmed_import(session, command.import_id)
    template = get_or_create_template(session, "customer-support-quality", "v1", command.threshold)
    prompt = get_or_create_prompt(session, "customer-support-judge", "v1", EVALUATION_SYSTEM_PROMPT)
    rule = get_or_create_rule(session, "evaluation-operation", "v1", DEFAULT_RULE_CONFIG)
    batch = create_sampling_batch(session, import_session.confirmed_source_id, command)
    return enqueue_evaluation_run(session, batch, template, prompt, rule, provider.identity)
```

Map strategy to existing `SamplingPolicy`: random=`1/0/0`; risk_first=`0.3/0.2/0.5`; scenario_weighted=`0.3/0.5/0.2`. Risk candidates include escalated, negative-feedback and repeated-question statuses or message markers.

- [ ] **Step 4: 实现 Worker 处理器和后处理阶段**

```python
def handle_job(job: Job) -> None:
    if job.kind == "evaluation_batch":
        summary = run_evaluation_batch(session, job.payload["run_id"], provider)
        if summary.failed == 0 or summary.succeeded > 0:
            enqueue_job(session, "evaluation_postprocess", {"run_id": run_id}, f"postprocess:{run_id}")
    elif job.kind == "evaluation_postprocess":
        results = load_run_results(session, job.payload["run_id"])
        clusters = persist_clusters(session, cluster_badcases(results))
        create_alerts_for_run(session, job.payload["run_id"], clusters)
```

The worker loop sleeps 1 second when no job is claimed and handles SIGINT cleanly. Post-processing creates clusters and rule-based alerts but does not human-confirm attribution or generate approved QA.

- [ ] **Step 5: 实现进度和分页结果 DTO**

```python
class OperationDetail(BaseModel):
    run_id: str
    stage: Literal["queued", "evaluating", "analyzing", "completed", "partial", "manual_review"]
    sample_count: int
    completed_count: int
    passed_count: int
    failed_count: int
    retrying_count: int
    pass_rate: float | None
    average_score: float | None
    dimension_averages: dict[str, float]
    latest_error: str | None
```

Stage is derived from immutable results, run status and queued/claimed post-process jobs; no separate mutable stage column is introduced.

- [ ] **Step 6: 运行操作、队列、分析和完整后端测试并提交**

Run: `cd backend && python -m pytest tests/integration/test_real_evaluation_operation.py tests/integration/test_evaluation_pipeline.py tests/integration/test_job_queue.py tests/integration/test_badcase_alert_flow.py -v`
Expected: PASS.

```bash
git add backend/app/operations backend/app/main.py backend/app/dashboard/service.py backend/tests
git commit -m "feat: orchestrate real evaluation operations"
```

### Task 6: 数据采集页面

**Files:**
- Create: `frontend/src/features/imports/ImportPage.tsx`
- Create: `frontend/src/features/imports/MappingForm.tsx`
- Create: `frontend/src/features/imports/ConversationPreview.tsx`
- Create: `frontend/src/app/importApi.ts`
- Create: `frontend/src/test/setup.ts`
- Create: `frontend/src/test/server.ts`
- Create: `frontend/src/test/TestApp.tsx`
- Create: `frontend/vite.config.ts`
- Modify: `frontend/package.json`
- Modify: `frontend/pnpm-lock.yaml`
- Modify: `frontend/src/app/router.tsx`
- Modify: `frontend/src/components/AppShell.tsx`
- Modify: `frontend/src/styles/theme.css`
- Test: `frontend/tests/ImportPage.test.tsx`

**Interfaces:**
- Consumes: Task 3 import APIs.
- Produces: `/runs/import` four-step JSON import page and navigation from “评测运行”.

- [ ] **Step 1: 写四步流程失败测试**

```tsx
it("uploads, maps, previews and confirms a JSON import", async () => {
  render(<ImportPage />, { wrapper: testApp(serverHandlers) });
  await user.upload(screen.getByLabelText("选择 JSON 文件"), jsonFile);
  expect(await screen.findByText("发现 100 条对话记录")).toBeVisible();
  await user.selectOptions(screen.getByLabelText("记录数组"), "result.conversations");
  await user.click(screen.getByRole("button", { name: "生成预览" }));
  expect(await screen.findByText("脱敏预览")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "确认入库" }));
  expect(await screen.findByText("成功写入 100 条")).toBeVisible();
});
```

- [ ] **Step 2: 验证组件测试先失败**

Run: `cd frontend && npm test -- ImportPage.test.tsx --run`
Expected: FAIL because `ImportPage` does not exist.

- [ ] **Step 3: 实现浏览器文件读取和导入 API 客户端**

```ts
export async function uploadJsonFile(file: File): Promise<ImportSession> {
  if (file.size > 20 * 1024 * 1024) throw new Error("JSON 文件不能超过 20 MB");
  const document = JSON.parse(await file.text());
  return request("/api/imports/json", {
    method: "POST",
    body: JSON.stringify({ filename: file.name, document }),
  });
}
```

Add `@vitejs/plugin-react`, `jsdom`, `msw` and `@testing-library/user-event` as dev dependencies. Configure Vitest with `environment: "jsdom"` and `setupFiles: ["./src/test/setup.ts"]`; setup imports `@testing-library/jest-dom/vitest` and starts, resets and stops the MSW server. `TestApp` creates a fresh `QueryClient` and `MemoryRouter` for every component test.

- [ ] **Step 4: 实现字段映射、错误策略和预览组件**

Mapping form conditionally renders message-array fields or question/answer fields. Required unmapped fields disable “生成预览”. Preview shows original record, normalized messages, redacted messages and row errors; default error policy is `block`.

- [ ] **Step 5: 实现确认结果和下一步导航**

After confirmation show inserted/skipped/error counts and one primary action: `使用这批数据发起评测`, linking to `/runs/new?import=<id>`.

- [ ] **Step 6: 运行组件测试和构建并提交**

Run: `cd frontend && npm test -- ImportPage.test.tsx --run && npm run build`
Expected: PASS.

```bash
git add frontend/src frontend/tests/ImportPage.test.tsx
git commit -m "feat: add guided JSON data collection"
```

### Task 7: 发起评测与运行详情页面

**Files:**
- Create: `frontend/src/features/runs/NewEvaluationPage.tsx`
- Create: `frontend/src/features/runs/RunDetailPage.tsx`
- Create: `frontend/src/features/runs/StageRail.tsx`
- Create: `frontend/src/app/evaluationApi.ts`
- Modify: `frontend/vite.config.ts`
- Modify: `frontend/src/app/router.tsx`
- Modify: `frontend/src/styles/theme.css`
- Modify: `README.md`
- Test: `frontend/tests/EvaluationRun.test.tsx`

**Interfaces:**
- Consumes: Task 4 provider status and Task 5 operation APIs.
- Produces: `/runs/new` configuration page and `/runs/:runId` polling detail page.

- [ ] **Step 1: 写模型未配置、启动和刷新恢复失败测试**

```tsx
it("blocks real evaluation until the model is configured", async () => {
  render(<NewEvaluationPage />, { wrapper: testApp(unconfiguredProvider) });
  expect(await screen.findByText("模型尚未配置")).toBeVisible();
  expect(screen.getByRole("button", { name: "启动真实评测" })).toBeDisabled();
});

it("starts a run and restores progress by run id", async () => {
  render(<RunDetailPage />, { wrapper: testApp(runningOperation) });
  expect(await screen.findByText("模型评测")).toBeVisible();
  expect(screen.getByText("38 / 100")).toBeVisible();
});
```

- [ ] **Step 2: 验证组件测试先失败**

Run: `cd frontend && npm test -- EvaluationRun.test.tsx --run`
Expected: FAIL with missing pages.

- [ ] **Step 3: 实现评测配置与明确启动确认**

The form loads confirmed imports and provider status, validates `1 <= sample_size <= available_count`, and shows `将使用 <model> 评测 <N> 条对话` above the only primary button.

- [ ] **Step 4: 实现阶段轨道、指标和分页结果**

```tsx
const operation = useQuery({
  queryKey: ["evaluation-operation", runId],
  queryFn: () => getOperation(runId),
  refetchInterval: (query) => isTerminal(query.state.data?.stage) ? false : 1500,
});
```

Stages are 采集完成、抽样完成、模型评测、Badcase 聚类、告警生成、等待人工处理. Results table includes scenario, score, status, reason, evidence and retry error. Mobile view converts rows to stacked cards.

- [ ] **Step 5: 配置本地代理并完善手动启动说明**

```ts
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
});
```

README uses reader-friendly sections: “只看演示页面” and “运行真实采集与评测”. The full mode lists four manually started terminals: MySQL, `uvicorn app.main:app --reload --port 8000`, `python -m app.operations.worker`, and the frontend `npm run dev` after `nvm use`.

- [ ] **Step 6: 运行前端测试、构建并提交**

Run: `cd frontend && npm test -- --run && npm run build`
Expected: PASS with no TypeScript errors.

```bash
git add frontend README.md
git commit -m "feat: operate and monitor real evaluations"
```

### Task 8: 端到端验收与运行文档

**Files:**
- Create: `backend/tests/e2e/test_json_to_evaluation_flow.py`
- Create: `frontend/tests/e2e/real-evaluation.spec.ts`
- Modify: `README.md`

**Interfaces:**
- Consumes: Tasks 1-7.
- Produces: 可重复的假传输 E2E 证据，以及真实模型的人工冒烟步骤。

- [ ] **Step 1: 写后端纵向闭环测试**

```python
def test_json_import_to_alert_flow(client, worker, fake_openai_transport):
    imported = upload_preview_and_confirm(client, SAMPLE_JSON, SAMPLE_MAPPING)
    run_id = start_operation(client, imported["import_id"], sample_size=4)
    worker.run_until_idle()
    detail = client.get(f"/api/operations/evaluations/{run_id}").json()
    assert detail["stage"] == "completed"
    assert detail["completed_count"] == 4
    assert detail["failed_count"] == 0
    assert client.get("/api/workbench").json()["counts"]["new_alerts"] >= 1
```

- [ ] **Step 2: 运行后端完整测试**

Run: `cd backend && python -m pytest -q`
Expected: PASS on a clean MySQL schema upgraded to `0004`.

- [ ] **Step 3: 运行前端 E2E 和响应式检查**

Run: `cd frontend && npm run build && npm run test:e2e`
Expected: upload fixture, preview, confirm, start evaluation and restore run detail all pass at desktop and 390 px mobile viewport; no horizontal overflow.

- [ ] **Step 4: 执行安全与差异检查**

Run: `rg -n "sk-[A-Za-z0-9]{12,}|LLM_API_KEY=.*[^=[:space:]]" frontend backend README.md`
Expected: no embedded API key values; only the environment-variable name and empty examples are present.

Run: `cd backend && python -m ruff check . && python -m ruff format --check . && cd .. && git diff --check`
Expected: all checks pass.

- [ ] **Step 5: 更新 README 验收清单并提交**

README must include exact environment variables, database migration command, three-terminal startup order, sample JSON structure, browser URL and stop commands. It must state that paid model calls occur only when the user manually starts a real evaluation.

```bash
git add backend/tests/e2e frontend/tests/e2e README.md
git commit -m "test: verify real evaluation workflow"
```
