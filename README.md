# AI 评测迭代工作台

## 面试演示

本项目支持 GitHub Pages 静态演示模式：工作台、问题归因、QA 审核、发布复测、评测规则和校准均可在浏览器中体验。演示数据和操作都是模拟的，不连接 FastAPI/MySQL，也不调用 DeepSeek。

本地预览演示站：

```bash
cd frontend
nvm use 24
npm run dev:demo
```

发布时将仓库推送到 GitHub `main`，在仓库 Settings → Pages → Build and deployment 选择 **GitHub Actions**。工作流成功后，演示地址为 `https://<用户名>.github.io/<仓库名>/`。项目尚未配置 GitHub remote，因此此处不填写尚不存在的在线链接。

安装、配置、启动和停止方法请见 [使用说明.md](./使用说明.md)。

了解产品模块和完整业务流程，请见 [产品说明与使用指南](./docs/产品设计/产品说明与使用指南.md)。

查看简明功能范围和验收标准，请见 [产品需求总览](./docs/需求文档/产品需求总览.md)。

产品设计和实施计划请见 [文档索引](./docs/文档索引.md)。
