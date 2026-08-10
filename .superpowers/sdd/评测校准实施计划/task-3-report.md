# Task 3 校准工作台与人工复核 API 报告

## Red

- 在 `backend/tests/integration/test_calibration_api.py` 先新建自包含 SQLite `StaticPool` 集成测试，不读取、连接或迁移 `TEST_DATABASE_URL`。
- 测试种入三条已完成评测结果、锁定的公司质量标准/Prompt/模型和一条 `ModelCallRecord`。
- 使用 `./.venv/bin/pytest tests/integration/test_calibration_api.py -q` 执行，在实现前结果为 `2 failed`：`POST /api/calibration/batches/today/ensure` 返回 `404 Not Found`。
- 失败测试覆盖工作台汇总、详情的递归脱敏、锁定运行快照、认同/不认同、空白及超长输入、首次提交获胜、批次完成和模型调用计数不变。

## Green

- 新建 `backend/app/calibration/contracts.py`：严格的认同/不认同 body，`actor` 及 `review_basis` 均去首尾空格、不可为空，后者最长 1000 字符。
- 新建 `backend/app/calibration/router.py` 并在 `backend/app/main.py` 注册。提供要求的六个接口，不注册、不解析、不调用任何 Provider。
- 扩展 `backend/app/calibration/service.py`：支持当日工作台查询、详情、认同与不认同提交。已复核记录直接返回首次内容，不覆盖任何人工字段；不认同强制 `include_in_regression=true`；最后一条待复核完成后批次置为 `completed`。
- 详情的 `conversation.messages` 使用递归 JSON 遍历，对所有字符串复用 `redact_text`，脱敏手机号、邮箱和订单号。
- 实现后以同一命令重跑 focused API 测试，结果 `2 passed` 。

## Self-review

- `calibration_workspace(session, status="pending")` 、`calibration_review_detail(session, review_id)`、`agree_with_evaluation(session, review_id, actor)` 和 `disagree_with_evaluation(session, review_id, input)` 均按约定提供。
- 不认同和认同只更新 `CalibrationReview` 和必要的 `CalibrationBatch.status`；没有任何 `EvaluationResult` 赋值或 Provider 依赖。
- 重复提交不论端点是 `agree` 还是 `disagree`，都在已复核状态下返回既有行，因而不更改 `reviewed_by`、`review_basis` 或纠正字段。
- 不存在的复核记录映射为 `404`；body 约束和非法 `status` query 由 FastAPI/Pydantic 返回 `422`。
- 工作台统计基于当日批次的全部复核记录，状态筛选仅影响 `items`。

## Verification

```text
./.venv/bin/pytest tests/integration/test_calibration_api.py -q
2 passed, 1 warning

./.venv/bin/pytest tests/unit/test_calibration_sampling.py -q
12 passed

./.venv/bin/pytest tests/unit/test_calibration_models.py -q
9 passed

./.venv/bin/ruff check app/calibration app/main.py tests/integration/test_calibration_api.py
All checks passed!

git diff --check
exit 0
```

## Concerns

- 无。FastAPI `TestClient` 输出一条既存 Starlette `httpx` 弃用警告，不影响本任务测试结果。

## Fix Round 1

### Red

- 在 focused SQLite API 测试中补充了详情中包含手机号、邮箱和订单号的 `reason` 与任意嵌套 `evidence`、trim 后 1000/1001 字符边界、workspace 三种 status 的全量汇总与分歧维度并列稳定性、两个独立 session 处理最后两条任务，以及 MySQL SQL 编译和锁调用顺序检查。
- 第一次执行 `./.venv/bin/pytest tests/integration/test_calibration_api.py -q` 结果为 `3 failed, 3 passed`：`reason`/`evidence` 包含原始敏感信息，前空格包围的 1000 字符 `review_basis` 被误拒绝，且不存在 batch 锁 helper。
- 将 SQLite fixture 调整为生产 `session_factory` 同样的 `autoflush=False` 后再次执行，结果为 `2 failed, 4 passed`：最后两条复核后 batch 仍为 `open`。这确认 pending 锁定查询之前还需显式 flush 当前完成。

### Green

- `DisagreeReviewInput` 的 `actor` 和 `review_basis` validator 改为 `mode="before"`，因而 trim 后再执行 `min_length`/`max_length` 约束。
- 复核流程先读取不变的 `batch_id`，然后 `SELECT calibration_batches ... FOR UPDATE` 锁定共享 batch，再锁当前 review。在锁内 flush 当前复核写入后，以 `SELECT calibration_reviews ... FOR UPDATE` 重查 pending，只有无待审记录时设为 `completed`。
- 详情、workspace 和复核响应在组装后使用 `_redact_json` 递归脱敏。因此 `reason`、嵌套 `evidence`、人工依据与其他直接展示的字符串都会复用 `redact_text`。
- 修复后 focused API 测试结果为 `6 passed, 1 warning`。

### Self-review

- 两个独立 SQLite session 测试以 `autoflush=False` 证明最后两条连续完成后批次为 `completed`。SQLite 不提供行级 `FOR UPDATE` 语义，因此同时以 MySQL dialect 编译断言 `FOR UPDATE` 存在，并以 monkeypatch 断言 batch 锁调用在 review 锁之前；未连接 MySQL。
- 三种 workspace status 均断言同一份 full-batch summary：`reviewed=3`、`total=4`、`pending=1`、`agreement_rate=1/3`，且 `completeness`/`correctness` 并列时稳定返回字典序最先的 `completeness`。
- 本轮不添加 Provider，不更改 `EvaluationResult`，不连接/迁移 MySQL，也不启动服务。
