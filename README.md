# AI 评测迭代工作台

## 在线演示

本项目支持 GitHub Pages 静态演示模式：工作台、问题归因、QA 审核、发布复测、评测规则和校准均可在浏览器中体验。演示数据和操作都是模拟的，不连接 FastAPI/MySQL，也不调用 DeepSeek。

**在线体验：[打开 AI 评测迭代工作台](https://liangjixuan3-svg.github.io/ai-evaluation-workbench/)**

本地预览演示站：

```bash
cd frontend
nvm use 24
npm run dev:demo
```

仓库已配置 GitHub Actions：推送到 `main` 后会自动执行测试、构建并更新 GitHub Pages 演示站。

安装、配置、启动和停止方法请见 [使用说明.md](./使用说明.md)。

了解产品模块和完整业务流程，请见 [产品说明与使用指南](./docs/产品设计/产品说明与使用指南.md)。

查看简明功能范围和验收标准，请见 [产品需求总览](./docs/需求文档/产品需求总览.md)。

产品设计和实施计划请见 [文档索引](./docs/文档索引.md)。
