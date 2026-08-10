# QA 审核工作台实施计划

> **执行要求：** 使用测试驱动方式逐项实现；用户的前后端服务由用户手动启动，本计划不得代为启动。

**目标：** 把知识缺失任务处理成可按需生成、人工审核、版本化批准或驳回，并可从浏览器下载的 QA 文件。

**架构：** 复用现有任务、QA 草稿、不可变版本、证据和导出模型，不新增核心表。后端增加 QA 工作台查询、驳回和文件响应接口；前端增加与问题归因一致的左队列右详情页面。只有生成草稿接口调用真实模型。

**技术栈：** FastAPI、SQLAlchemy、Pydantic、MySQL/SQLite 测试库、React 19、TypeScript、Vite、Vitest。

## 全局约束

- 不新增数据库迁移。
- 不自动生成、批准或发布 QA。
- 同一任务生成草稿必须幂等，重复操作不增加模型调用。
- 批准必须包含至少一条业务依据。
- 已批准或已驳回内容只读。
- 下载只允许已批准版本，使用 UTF-8 JSON 或 CSV。
- 中文页面文案符合全站可读性规范。

---

### 任务一：QA 工作台查询接口

**文件：**

- 修改：`backend/app/remediation/service.py`
- 修改：`backend/app/remediation/router.py`
- 新建：`backend/tests/integration/test_qa_workspace_api.py`

**接口：**

- `list_qa_workspace(session, status) -> dict`
- `qa_workspace_detail(session, task_id) -> dict`
- `GET /api/qa-workspace?status=pending|approved|rejected|all`
- `GET /api/qa-workspace/{task_id}`

- [ ] 编写失败测试，创建一个知识缺失任务，断言列表返回待生成数量和真实任务。
- [ ] 编写失败测试，断言详情包含问题摘要、最多三条脱敏代表对话，以及空草稿状态。
- [ ] 运行 `./.venv/bin/pytest tests/integration/test_qa_workspace_api.py -q`，确认接口因 `404` 失败。
- [ ] 实现任务、草稿和当前版本的查询组装；详情复用问题服务的脱敏样本。
- [ ] 重新运行测试，要求查询测试通过。

### 任务二：真实模型生成与幂等

**文件：**

- 修改：`backend/app/remediation/router.py`
- 修改：`backend/tests/integration/test_qa_workspace_api.py`

**接口：**

- `get_remediation_provider() -> EvaluationProvider`
- `POST /api/qa-workspace/{task_id}/generate`

- [ ] 编写失败测试，用可覆盖的测试 Provider 生成 QA，连续请求两次并断言 Provider 只调用一次。
- [ ] 编写失败测试，断言模型未配置时依赖返回 `503`。
- [ ] 运行目标测试，确认当前假模型依赖或缺少接口导致失败。
- [ ] 将生成依赖改为读取 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL` 的真实 Provider；通过任务定位问题簇并调用现有 `generate_qa_draft`。
- [ ] 将模型错误映射为 `502`，业务状态错误映射为 `422`，任务不存在映射为 `404`。
- [ ] 重新运行目标测试，要求生成与幂等测试通过。

### 任务三：批准、驳回与浏览器下载

**文件：**

- 修改：`backend/app/remediation/service.py`
- 修改：`backend/app/remediation/router.py`
- 修改：`backend/tests/integration/test_qa_workspace_api.py`

**接口：**

- `reject_qa(session, draft_id, actor, reason) -> QADraft`
- `POST /api/qa-drafts/{draft_id}/reject`
- `POST /api/qa-exports/download`

- [ ] 编写失败测试，断言缺少业务依据不能批准；完整编辑与依据可创建版本 2，并将任务标记完成。
- [ ] 编写失败测试，断言驳回必须填写原因、状态变为 `rejected`、任务取消且写入审计。
- [ ] 编写失败测试，断言批准后 JSON/CSV 下载返回附件响应，驳回或待审核草稿不能下载。
- [ ] 运行目标测试，确认驳回和下载接口缺失。
- [ ] 实现驳回服务和任务状态同步；批准成功后同步任务为 `done`。
- [ ] 复用 `export_qa` 的字节内容返回 `Content-Disposition: attachment`，不向页面暴露服务器路径。
- [ ] 重新运行目标测试，要求审核与下载测试通过。

### 任务四：前端 API 与审核工作台

**文件：**

- 新建：`frontend/src/app/qaApi.ts`
- 新建：`frontend/src/app/qaApi.test.ts`
- 新建：`frontend/src/features/qa/QAWorkspacePage.tsx`
- 新建：`frontend/src/features/qa/QAWorkspacePage.test.tsx`
- 修改：`frontend/src/app/router.tsx`
- 修改：`frontend/src/styles/theme.css`

**接口：**

- `listQAWorkspace(status)`
- `getQAWorkspaceDetail(taskId)`
- `generateQADraft(taskId)`
- `approveQADraft(draftId, input)`
- `rejectQADraft(draftId, reason)`
- `downloadQA(draftId, format)`

- [ ] 先编写 API 失败测试，断言请求路径、HTTP 方法和批准请求体。
- [ ] 先编写页面失败测试，断言待生成状态、六个编辑字段、业务依据、批准与驳回入口。
- [ ] 运行 `npm test -- --run src/app/qaApi.test.ts src/features/qa/QAWorkspacePage.test.tsx`，确认模块不存在而失败。
- [ ] 实现 API 类型和请求函数；下载使用 Blob 和临时链接触发浏览器保存。
- [ ] 实现顶部概况、状态筛选、左侧队列、代表样本、按需生成、草稿编辑、业务依据、批准、驳回和下载。
- [ ] 已批准或已驳回时锁定编辑区；错误状态展示具体后端信息并允许重试。
- [ ] 将 `/qa/*` 从占位页替换为 `QAWorkspacePage`，并增加桌面与移动端样式。
- [ ] 重新运行目标前端测试，要求通过。

### 任务五：说明与最终验证

**文件：**

- 修改：`使用说明.md`
- 修改：`docs/文档索引.md`

- [ ] 在使用说明增加从知识缺失任务到生成、审核、批准和下载的操作步骤。
- [ ] 在文档索引加入本实施计划。
- [ ] 运行后端目标测试、现有安全测试集和 Ruff。
- [ ] 运行前端全部测试和 `npm run build`。
- [ ] 运行 `git diff --check`，确认没有空白错误。
- [ ] 检查 Git 状态，只提交本功能相关文件。
