# AI 评测迭代工作台

## 在线演示

本项目支持 GitHub Pages 静态演示模式：工作台、问题归因、QA 审核、发布复测、评测规则和校准均可在浏览器中体验。演示数据和操作都是模拟的，不连接 FastAPI/MySQL，也不调用 DeepSeek。

**在线体验：[打开 AI 评测迭代工作台](https://liangjixuan3-svg.github.io/ai-evaluation-workbench/)**

本地预览演示站（将 `/你的项目完整路径` 替换为电脑上包含 `backend`、`frontend` 的项目根目录完整路径，包括项目文件夹名称；保留双引号及末尾的 `/frontend`）：

```bash
cd "/你的项目完整路径/frontend"
nvm use 24
npm run dev:demo
```

仓库已配置 GitHub Actions：推送到 `main` 后会自动执行测试、构建并更新 GitHub Pages 演示站。

## 项目目录

- `backend`（后端）：负责数据入库、调用大模型、执行评测和保存结果，使用 Python/FastAPI。真实业务模式需要启动它；在线演示不需要。
- `frontend`（前端）：负责浏览器中看到的页面、按钮和交互，使用 React/Vite。
- `docs`（说明文档）：包含产品设计、功能需求和实施计划。
- `示例数据`：提供用于体验功能的虚构对话和公司质量标准。

安装、配置、启动和停止方法请见 [使用说明.md](./使用说明.md)。

了解产品模块和完整业务流程，请见 [产品说明与使用指南](./docs/产品设计/产品说明与使用指南.md)。

查看简明功能范围和验收标准，请见 [产品需求总览](./docs/需求文档/产品需求总览.md)。

产品设计和实施计划请见 [文档索引](./docs/文档索引.md)。
