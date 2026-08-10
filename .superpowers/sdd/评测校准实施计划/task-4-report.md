# Task 4 报告

## Red

- 新增 `calibrationApi` 与校准工作台静态渲染测试，首次运行因目标模块不存在而失败。
- 补充 FastAPI 校验数组本地化断言后，测试先失败于英文 `actor is required` 提示。

## Green

- 新增校准 API 封装、工作台页面、`/calibration` 路由和“08 评测校准”导航。
- 页面首次挂载仅执行一次今日批次准备，随后加载待复核队列；筛选与提交后刷新只重新查询工作台。
- 实现审核人输入、认同二次确认、不认同必填表单、已复核只读和回归案例标记。
- 完成纸张式墨绿/青绿样式、360px 桌面队列和 900px 以下单列布局，并复用全站字号变量。

## Self-review

- API 错误优先显示后端 `detail`；字符串、中文数组及常见 FastAPI 校验数组均有可理解提示。
- 静态渲染测试覆盖必需内容、空状态、已复核只读和用户/AI 脱敏对话角色。
- 提交前运行 Task 4 聚焦测试、相关 QA/问题归因/复测回归、生产构建和 `git diff --check`。

## Concerns

- 未启动服务或进行浏览器手测，符合任务约束；验证范围为静态渲染、API 请求封装和生产构建。
- 后端当前校准维度枚举为准确性、完整性、合规性和服务体验（`tone`）；页面严格使用该接口允许的集合。

## Fix Round 1

- 使用结算后清空的模块级 ensure promise，StrictMode 重放共享同一请求，失败后可再次发起。
- workspace 与 detail 均使用 latest generation 和 latest status/selection refs；切换时清空旧详情，过期响应不再覆盖当前选择，提交完成按最新筛选刷新。
- 补充真实 StrictMode 挂载测试，验证 ensure 仅一次且在成功后才查询 pending；静态测试补充可访问性与审核人长度约束。
- 审核人输入限制为 128 字符，标准后端长度校验映射为中文；详情 landmark 改为 article，筛选和队列增加状态语义，确认区使用 alertdialog 并在打开后聚焦确认按钮。

## Fix Round 2

- workspace 查询的成功与失败统一受 generation 与 requested status 守卫；迟到的旧筛选失败不再写入当前错误状态。
- 切换筛选时立即清空 workspace、详情与错误，加载新筛选期间不会保留旧队列。

## Fix Round 3

- 新增无 React 依赖的生产请求协调器，页面实际用它管理 current status、workspace/detail generation 与当前 review id。
- 协调器 deferred 单测覆盖 workspace 成功/失败失效、状态切换、A/B 详情乱序、提交期间 latest status 与 ensure 合并/失败重试。
