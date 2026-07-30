import { useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  confirmImport,
  previewImport,
  uploadJson,
  type ImportMapping,
  type ImportPreview,
  type UploadedImport,
} from "../../app/importApi";
import { MappingForm } from "./MappingForm";

export function ImportPage() {
  const navigate = useNavigate();
  const [uploaded, setUploaded] = useState<UploadedImport | null>(null);
  const [mapping, setMapping] = useState<ImportMapping | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [sourceName, setSourceName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function handleFile(file?: File) {
    if (!file) return;
    setBusy(true);
    setError("");
    setPreview(null);
    try {
      const document = JSON.parse(await file.text()) as unknown;
      const result = await uploadJson(file.name, document);
      const first = result.candidates[0];
      setUploaded(result);
      setMapping(first?.suggested_mapping ?? null);
      setSourceName(file.name.replace(/\.json$/i, ""));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "JSON 文件无法读取");
    } finally {
      setBusy(false);
    }
  }

  async function handlePreview() {
    if (!uploaded || !mapping) return;
    setBusy(true);
    setError("");
    try {
      setPreview(await previewImport(uploaded.id, mapping));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "预览失败");
    } finally {
      setBusy(false);
    }
  }

  async function handleConfirm() {
    if (!uploaded || !sourceName.trim()) return;
    setBusy(true);
    setError("");
    try {
      await confirmImport(uploaded.id, sourceName.trim());
      navigate(`/runs/new?import=${uploaded.id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "入库失败");
      setBusy(false);
    }
  }

  function chooseCandidate(index: number) {
    const candidate = uploaded?.candidates[index];
    if (!candidate) return;
    setMapping(candidate.suggested_mapping);
    setPreview(null);
  }

  return (
    <section className="operation-page">
      <header className="operation-hero">
        <div><span className="eyebrow">01 / DATA INTAKE</span><h1>把线上对话<br />变成可评测样本</h1></div>
        <p>不要求业务方先改 JSON。上传后自动找到对话数组，你只需确认字段对应关系。</p>
      </header>

      <div className="step-card upload-step">
        <div className="step-index">01</div>
        <div className="step-body">
          <span className="step-kicker">选择原始数据</span><h2>上传 JSON 文件</h2>
          <label className="file-drop">
            <input type="file" accept="application/json,.json" onChange={(event) => void handleFile(event.target.files?.[0])} />
            <strong>{busy && !uploaded ? "正在解析…" : "点击选择 JSON"}</strong>
            <small>支持任意嵌套结构，单文件最大 20 MB</small>
          </label>
        </div>
        <div className="step-status">{uploaded ? `已发现 ${uploaded.candidates.length} 个候选数组` : "等待文件"}</div>
      </div>

      {uploaded && mapping && (
        <div className="step-card">
          <div className="step-index">02</div>
          <div className="step-body wide">
            <span className="step-kicker">确认解析方式</span><h2>字段映射</h2>
            {uploaded.candidates.length > 1 && <div className="candidate-tabs">{uploaded.candidates.map((candidate, index) => (
              <button type="button" key={candidate.path} className={mapping.record_path === candidate.path ? "active" : ""} onClick={() => chooseCandidate(index)}>
                {candidate.path} <small>{candidate.length} 条</small>
              </button>
            ))}</div>}
            <MappingForm value={mapping} onChange={(next) => { setMapping(next); setPreview(null); }} />
            <details className="raw-sample"><summary>查看原始样本</summary><pre>{JSON.stringify(uploaded.candidates.find((item) => item.path === mapping.record_path)?.sample[0], null, 2)}</pre></details>
            <button className="primary-button" type="button" disabled={busy} onClick={() => void handlePreview()}>{busy ? "正在校验…" : "生成脱敏预览 →"}</button>
          </div>
          <div className="step-status">自动建议已填入<br /><small>请根据业务数据确认</small>
          </div>
        </div>
      )}

      {preview && (
        <div className="step-card preview-step">
          <div className="step-index">03</div>
          <div className="step-body wide">
            <span className="step-kicker">入库前最后确认</span><h2>样本预览</h2>
            <div className="preview-summary"><strong>{preview.valid_count}</strong> 条可入库 <span>{preview.error_count} 条异常</span></div>
            <div className="conversation-preview">{preview.items.slice(0, 3).map((item) => (
              <article key={item.external_id}>
                <header><strong>{item.scenario || "未分类场景"}</strong><small>{new Date(item.occurred_at).toLocaleString("zh-CN")}</small></header>
                {item.redacted_messages.map((message, index) => <p key={`${message.role}-${index}`} className={message.role === "assistant" ? "assistant-message" : ""}><b>{message.role === "assistant" ? "AI" : "用户"}</b>{message.content}</p>)}
              </article>
            ))}</div>
            <div className="confirm-bar">
              <label className="field"><span>数据源名称</span><input value={sourceName} onChange={(event) => setSourceName(event.target.value)} /></label>
              <button className="primary-button" type="button" disabled={busy || !sourceName.trim()} onClick={() => void handleConfirm()}>确认入库并去评测 →</button>
            </div>
          </div>
          <div className="step-status success">脱敏预览已就绪</div>
        </div>
      )}
      {error && <div className="operation-error" role="alert">{error}</div>}
    </section>
  );
}
