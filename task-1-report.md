# 任务一报告：文档文本提取

## 状态

已完成并提交前验证。

## 修改文件

- `backend/pyproject.toml`：新增 `python-docx` 与 `pypdf` 运行时依赖。
- `backend/app/quality_standards/__init__.py`：新增公司质量标准包。
- `backend/app/quality_standards/documents.py`：实现纯内存 DOCX/PDF 文本提取、分段定位、20 MB 限制、文件类型与内容签名校验及 SHA-256。
- `backend/tests/unit/test_quality_standard_documents.py`：新增 DOCX 段落、PDF 页定位、格式伪装、文件大小、空文档与无文本 PDF 的单元测试。

## 测试证据

- TDD 红灯：`backend/.venv/bin/python -m pytest tests/unit/test_quality_standard_documents.py -q` 在实现前因 `app.quality_standards` 不存在而收集失败。
- TDD 绿灯：实现后同一命令通过，结果为 `7 passed`。
- 静态检查：`backend/.venv/bin/ruff check app/quality_standards tests/unit/test_quality_standard_documents.py` 通过，结果为 `All checks passed!`。
- 差异检查：`git diff --check` 无输出，未发现空白错误。

## 遗留风险

- 第一版仅从 PDF 的可复制文字层提取文本；扫描件及图片文字不会进行 OCR，且会给出中文提示。
- DOCX 内容签名以 ZIP 头识别，损坏或非 Office 的 ZIP 内容会在解析阶段被拒绝并提示重新上传。
