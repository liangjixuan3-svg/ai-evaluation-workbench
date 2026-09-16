import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { getConfirmedImports, type ConfirmedImport } from "../../app/importApi";
import { getProviderStatus, startEvaluation } from "../../app/evaluationApi";
import { listEvaluationPrompts, type EvaluationPromptVersion } from "../../app/evaluationPromptApi";
import { listQualityStandards, type QualityStandardSummary } from "../../app/qualityStandardApi";
import { isDemoMode } from "../../demo/mode";

export function NewEvaluationPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [imports, setImports] = useState<ConfirmedImport[]>([]);
  const [importId, setImportId] = useState(searchParams.get("import") || "");
  const [standards, setStandards] = useState<QualityStandardSummary[]>([]);
  const [standardVersionId, setStandardVersionId] = useState("");
  const [prompts, setPrompts] = useState<EvaluationPromptVersion[]>([]);
  const [promptVersionId, setPromptVersionId] = useState("");
  const [sampleSize, setSampleSize] = useState(100);
  const [strategy, setStrategy] = useState<"random" | "risk_first" | "scenario_weighted">("risk_first");
  const [threshold, setThreshold] = useState(75);
  const [provider, setProvider] = useState<{ configured: boolean; model: string | null } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void Promise.all([getConfirmedImports(), getProviderStatus(), listQualityStandards(), listEvaluationPrompts()])
      .then(([items, status, standardItems, promptItems]) => {
        setImports(items);
        setProvider(status);
        const published = standardItems.filter((item) =>
          item.published_version_id
          && item.published_rules?.weights
          && Object.keys(item.published_rules.weights).length === 5
        );
        setStandards(published);
        setStandardVersionId((current) => current || published[0]?.published_version_id || "");
        const publishedPrompts = promptItems.filter((item) => item.published_at);
        setPrompts(publishedPrompts);
        setPromptVersionId((current) => current || publishedPrompts.find((item) => item.active)?.id || publishedPrompts[0]?.id || "");
        setImportId((current) => current || items[0]?.id || "");
        const selected = items.find((item) => item.id === (searchParams.get("import") || items[0]?.id));
        if (selected) setSampleSize(Math.min(100, selected.available_count));
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : "无法读取评测配置"));
  }, [searchParams]);

  const selected = imports.find((item) => item.id === importId);
  const selectedStandard = standards.find((item) => item.published_version_id === standardVersionId);
  const standardRules = selectedStandard?.published_rules;
  const selectedPrompt = prompts.find((item) => item.id === promptVersionId);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await startEvaluation({
        import_id: importId,
        quality_standard_version_id: standardVersionId,
        prompt_version_id: promptVersionId,
        sample_size: sampleSize,
        strategy,
        threshold: standardRules?.threshold ?? threshold,
        seed: Date.now() % 2_147_483_647,
        actor: "operator",
      });
      navigate(`/runs/${result.run_id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法发起评测");
      setBusy(false);
    }
  }

  return (
    <section className="operation-page compact-page">
      <header className="operation-hero">
        <div><span className="eyebrow">02 / EVALUATION RUN</span><h1>发起一次<br />可追溯的评测</h1></div>
        <p>每次运行都固定数据批次、抽样策略、阈值和模型，后续才能准确对比质量变化。</p>
      </header>
      <div className="launch-layout">
        <form className="launch-card" onSubmit={(event) => void submit(event)}>
          <div className="launch-heading"><span>RUN CONFIGURATION</span><strong>评测配置</strong></div>
          <label className="field"><span>已入库数据批次</span><select value={importId} onChange={(event) => {
            setImportId(event.target.value);
            const item = imports.find((entry) => entry.id === event.target.value);
            if (item) setSampleSize(Math.min(100, item.available_count));
          }}><option value="">请选择</option>{imports.map((item) => <option value={item.id} key={item.id}>{item.filename} · {item.available_count} 条</option>)}</select></label>
          {imports.length === 0 && <a className="inline-notice" href="/runs/import">还没有数据，先上传 JSON →</a>}
          <label className="field"><span>公司质量标准</span><select value={standardVersionId} onChange={(event) => setStandardVersionId(event.target.value)}><option value="">请选择已发布标准</option>{standards.map((item) => <option value={item.published_version_id || ""} key={item.id}>{item.name} · V{item.latest_version}</option>)}</select></label>
          {standards.length === 0 && <a className="inline-notice" href="/rules">还没有已发布标准，先配置评测规则 →</a>}
          <label className="field"><span>评测 Prompt</span><select value={promptVersionId} onChange={(event) => setPromptVersionId(event.target.value)}><option value="">请选择已发布 Prompt</option>{prompts.map((item) => <option value={item.id} key={item.id}>客服质量评测 · {item.version.toUpperCase()}{item.active ? " · 当前默认" : ""}</option>)}</select></label>
          {prompts.length === 0 && <a className="inline-notice" href="/rules/prompts">还没有已发布 Prompt，先配置评测 Prompt →</a>}
          <div className="form-grid two-columns">
            <label className="field"><span>抽样数量</span><input type="number" min="1" max={selected?.available_count || 10000} value={sampleSize} onChange={(event) => setSampleSize(Number(event.target.value))} /></label>
            <label className="field"><span>通过阈值（由公司标准固定）</span><input type="number" min="0" max="100" disabled={Boolean(standardRules)} value={standardRules?.threshold ?? threshold} onChange={(event) => setThreshold(Number(event.target.value))} /></label>
          </div>
          <fieldset className="strategy-field"><legend>抽样策略</legend>{[
            ["risk_first", "风险优先", "优先覆盖转人工、差评等高风险对话"],
            ["scenario_weighted", "场景均衡", "减少高频场景对结果的掩盖"],
            ["random", "纯随机", "用于观察整体质量水位"],
          ].map(([value, label, hint]) => <label key={value} className={strategy === value ? "active" : ""}><input type="radio" name="strategy" value={value} checked={strategy === value} onChange={() => setStrategy(value as typeof strategy)} /><strong>{label}</strong><small>{hint}</small></label>)}</fieldset>
          {standardRules && <div className="standard-snapshot">五维权重：准确 {Math.round(standardRules.weights.correctness * 100)}% · 完整 {Math.round(standardRules.weights.completeness * 100)}% · 相关 {Math.round(standardRules.weights.relevance * 100)}% · 体验 {Math.round(standardRules.weights.service_experience * 100)}% · 合规 {Math.round(standardRules.weights.compliance * 100)}%</div>}
          <button className="primary-button launch-button" disabled={busy || !importId || !standardVersionId || !promptVersionId || !provider?.configured}>{busy ? "正在创建…" : isDemoMode ? "启动模拟评测 →" : "启动真实评测 →"}</button>
          {error && <div className="operation-error" role="alert">{error}</div>}
        </form>
        <aside className="readiness-card">
          <span className="eyebrow">PRE-FLIGHT CHECK</span><h2>运行前检查</h2>
          <dl><div><dt>数据</dt><dd className={selected ? "ready" : ""}>{selected ? `${selected.available_count} 条可用` : "待选择"}</dd></div><div><dt>标准</dt><dd className={selectedStandard ? "ready" : "blocked"}>{selectedStandard ? `${selectedStandard.name} V${selectedStandard.latest_version}` : "待选择"}</dd></div><div><dt>Prompt</dt><dd className={selectedPrompt ? "ready" : "blocked"}>{selectedPrompt ? selectedPrompt.version.toUpperCase() : "待选择"}</dd></div><div><dt>模型</dt><dd className={provider?.configured ? "ready" : "blocked"}>{provider?.configured ? provider.model : "未配置 API"}</dd></div><div><dt>资源估算</dt><dd>{sampleSize || 0} 次模型请求</dd></div></dl>
          {!provider?.configured && <p className="config-hint">在后端 `.env` 中设置 LLM_BASE_URL、LLM_API_KEY 和 LLM_MODEL 后即可启动。</p>}
        </aside>
      </div>
    </section>
  );
}
