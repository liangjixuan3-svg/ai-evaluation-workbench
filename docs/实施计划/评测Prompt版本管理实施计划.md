# 评测 Prompt 版本管理实施计划

> **执行要求：** 使用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans` 按任务逐项实施；每项遵循测试先行，并在通过验证后提交。

**目标：** 支持运营人员管理评测 Prompt 草稿和已发布版本，让发起评测时选择的版本真正参与模型请求并被运行记录追溯。

**架构：** 复用现有 `prompt_versions` 表并增加发布时间，在 FastAPI 单体中新增独立的 Prompt 管理服务和接口。模型调用把可版本化指令与系统固定输出协议组合；React 在“评测规则”模块增加 Prompt 页签，并在发起评测时选择已发布版本。

**技术栈：** Python 3.12、FastAPI、SQLAlchemy、Alembic、Pydantic、MySQL/SQLite 测试、React 19、TypeScript、Vite、Vitest。

## 全局约束

- 页面和错误提示使用易懂中文，代码标识保持现有英文风格。
- 只开放评测指令文本，五维字段、JSON 输出协议和证据校验不可编辑。
- 已发布版本不可修改或删除；历史运行继续绑定原版本。
- 不增加 Redis、独立 Worker 服务或新的前端依赖。
- 所有说明文件继续放在 `docs/产品设计` 或 `docs/实施计划`。

---

### 任务一：Prompt 发布状态与迁移

**文件：**
- 新建：`backend/alembic/versions/0008_add_prompt_published_at.py`
- 修改：`backend/app/evaluation/models.py`
- 新建测试：`backend/tests/integration/test_evaluation_prompt_schema.py`

**接口：**
- `PromptVersion.published_at: datetime | None`
- `published_at is None` 表示草稿；非空表示不可变发布版本。

- [ ] 编写失败测试，检查 `prompt_versions.published_at` 存在且历史记录迁移后等于原 `created_at`。
- [ ] 执行 `./.venv/bin/pytest tests/integration/test_evaluation_prompt_schema.py -q`，确认因字段或迁移不存在而失败。
- [ ] 新增迁移：添加可空 `published_at`，将现有记录更新为 `created_at`，并在 ORM 模型增加字段。
- [ ] 重跑测试并执行 `./.venv/bin/ruff check app/evaluation/models.py alembic/versions/0008_add_prompt_published_at.py tests/integration/test_evaluation_prompt_schema.py`。
- [ ] 提交 `feat: version evaluation prompt publication state`。

### 任务二：Prompt 版本管理 API

**文件：**
- 新建：`backend/app/evaluation_prompts/__init__.py`
- 新建：`backend/app/evaluation_prompts/service.py`
- 新建：`backend/app/evaluation_prompts/router.py`
- 修改：`backend/app/main.py`
- 新建测试：`backend/tests/integration/test_evaluation_prompt_api.py`

**接口：**

```python
def ensure_default_prompt(session: Session) -> PromptVersion: ...
def list_prompt_versions(session: Session) -> list[PromptVersion]: ...
def create_prompt_draft(session: Session, source_id: str) -> PromptVersion: ...
def update_prompt_draft(session: Session, prompt_id: str, content: str) -> PromptVersion: ...
def publish_prompt_draft(session: Session, prompt_id: str) -> PromptVersion: ...
```

HTTP 接口：

```text
GET  /api/evaluation-prompts
POST /api/evaluation-prompts/drafts       {"source_id": "..."}
PUT  /api/evaluation-prompts/{id}         {"content": "..."}
POST /api/evaluation-prompts/{id}/publish
```

- [ ] 编写失败 API 测试：首次列表自动生成 V1；复制得到 V2 草稿；草稿可保存；发布后 V2 为默认；V1 保留；已发布版本更新返回 409。
- [ ] 运行专项测试，确认路由不存在而失败。
- [ ] 实现服务：版本号按 `v数字` 递增，同一名称只允许一个草稿，内容去首尾空白且限制 20000 字，空内容或与来源完全相同的草稿不能发布。
- [ ] 实现事务发布：先停用同名称历史默认版本，再设置草稿 `published_at` 和 `active=true`。
- [ ] 注册路由并把异常映射为中文 404、409、422。
- [ ] 重跑专项测试与 Ruff。
- [ ] 提交 `feat: add evaluation prompt management api`。

### 任务三：让所选 Prompt 真正进入模型请求

**文件：**
- 修改：`backend/app/evaluation/contracts.py`
- 修改：`backend/app/evaluation/openai_compatible.py`
- 修改：`backend/app/evaluation/service.py`
- 修改：`backend/app/operations/router.py`
- 修改：`backend/app/operations/service.py`
- 新建测试：`backend/tests/unit/test_openai_compatible.py`
- 修改测试：`backend/tests/integration/test_real_evaluation_operation.py`

**接口：**

```python
class EvaluationRequest:
    conversation: NormalizedConversation
    criteria: dict
    instructions: str

class StartEvaluation:
    prompt_version_id: str
```

固定协议由 `EVALUATION_OUTPUT_CONTRACT` 保存，模型 system message 使用：

```python
system_prompt = f"{request.instructions.strip()}\n\n{EVALUATION_OUTPUT_CONTRACT}"
```

- [ ] 编写失败测试，断言模型请求包含所选数据库 Prompt 内容和固定输出协议。
- [ ] 编写失败运行测试，断言草稿 ID 被拒绝、已发布 ID 被写入运行、不同 Prompt 版本不会复用同一运行。
- [ ] 运行测试确认当前仍使用固定常量而失败。
- [ ] 给 `EvaluationRequest` 增加 `instructions`，Worker 从 `run.prompt_version.content` 构造请求。
- [ ] 将现有 Prompt 拆成可编辑默认指令与固定输出协议，真实传输层组合两段；Fake Provider 保持确定性。
- [ ] 发起评测参数增加 `prompt_version_id`，只接受已发布版本，并将版本 ID 加入运行幂等键。
- [ ] 运行详情返回 `prompt: {id, name, version}`。
- [ ] 重跑相关后端测试与 Ruff。
- [ ] 提交 `feat: evaluate with selected prompt version`。

### 任务四：Prompt 管理页面

**文件：**
- 新建：`frontend/src/app/evaluationPromptApi.ts`
- 新建测试：`frontend/src/app/evaluationPromptApi.test.ts`
- 新建：`frontend/src/features/rules/RuleSettingsNav.tsx`
- 新建：`frontend/src/features/rules/EvaluationPromptPage.tsx`
- 修改：`frontend/src/features/rules/QualityStandardPage.tsx`
- 修改：`frontend/src/app/router.tsx`
- 修改：`frontend/src/components/AppShell.tsx`
- 修改：`frontend/src/styles/theme.css`

**前端类型：**

```ts
interface EvaluationPromptVersion {
  id: string;
  name: string;
  version: string;
  content: string;
  active: boolean;
  published_at: string | null;
  created_at: string;
}
```

- [ ] 编写失败 API 测试，覆盖列表、复制、保存和发布请求路径与请求体。
- [ ] 实现 `evaluationPromptApi.ts` 并让测试通过。
- [ ] 新增共享页签“公司质量标准 / 评测 Prompt”；`/rules/prompts` 进入 Prompt 页面，侧栏“评测规则”保持选中。
- [ ] 实现左侧版本列表和右侧工作区：已发布版只读并可复制，草稿可保存和发布，错误使用中文提示。
- [ ] 为桌面和移动端补充响应式样式，不新增第三方组件。
- [ ] 执行 `npm test -- --run` 和 `npm run build`。
- [ ] 提交 `feat: add evaluation prompt workspace`。

### 任务五：发起评测选择与运行追溯

**文件：**
- 修改：`frontend/src/app/evaluationApi.ts`
- 修改测试：`frontend/src/app/evaluationApi.test.ts`
- 修改：`frontend/src/features/evaluations/NewEvaluationPage.tsx`
- 修改：`frontend/src/features/evaluations/RunDetailPage.tsx`
- 修改：`frontend/src/styles/theme.css`

- [ ] 先修改 API 测试，要求创建运行请求包含 `prompt_version_id`。
- [ ] 在发起评测页同时加载 Prompt 列表，仅展示已发布版本，默认选中 `active=true` 的版本。
- [ ] 增加“评测 Prompt”下拉框和运行前检查项；未选择时禁用启动按钮。
- [ ] 运行详情显示本次 Prompt 名称和版本，与公司质量标准版本并列。
- [ ] 重跑全部前端测试和生产构建。
- [ ] 提交 `feat: select and trace evaluation prompts`。

### 任务六：说明与端到端验收

**文件：**
- 修改：`使用说明.md`
- 修改：`docs/文档索引.md`

- [ ] 在使用说明增加“创建 Prompt V2、发布、选择版本发起评测、查看运行版本”的操作步骤。
- [ ] 执行后端 Prompt API、模型传输和真实运行专项测试，并运行 Ruff。
- [ ] 执行完整前端测试、生产构建和 `git diff --check`。
- [ ] 使用有效公司标准和已发布 Prompt 创建两条小样本评测，确认运行详情记录所选 Prompt；如果本机服务未启动，明确记录未做浏览器联调，不代替用户启动。
- [ ] 提交 `docs: explain evaluation prompt workflow`。

## 完成条件

- 页面配置的 Prompt 内容确实出现在模型 system message 中。
- 固定输出协议始终存在且不可从页面修改。
- 草稿不能参与评测，已发布历史版本可以被选择和追溯。
- 数据库迁移、后端专项测试、前端测试和生产构建全部通过。
