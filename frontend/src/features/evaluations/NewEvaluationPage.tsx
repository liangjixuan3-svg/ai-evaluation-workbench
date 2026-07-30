import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { getConfirmedImports, type ConfirmedImport } from "../../app/importApi";
import { getProviderStatus, startEvaluation } from "../../app/evaluationApi";

export function NewEvaluationPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [imports, setImports] = useState<ConfirmedImport[]>([]);
  const [importId, setImportId] = useState(searchParams.get("import") || "");
  const [sampleSize, setSampleSize] = useState(100);
  const [strategy, setStrategy] = useState<"random" | "risk_first" | "scenario_weighted">("risk_first");
  const [threshold, setThreshold] = useState(75);
  const [provider, setProvider] = useState<{ configured: boolean; model: string | null } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void Promise.all([getConfirmedImports(), getProviderStatus()])
      .then(([items, status]) => {
        setImports(items);
        setProvider(status);
        setImportId((current) => current || items[0]?.id || "");
        const selected = items.find((item) => item.id === (searchParams.get("import") || items[0]?.id));
        if (selected) setSampleSize(Math.min(100, selected.available_count));
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : "无法读取评测配置"));
  }, [searchParams]);

  const selected = imports.find((item) => item.id === importId);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await startEvaluation({
        import_id: importId,
        sample_size: sampleSize,
        strategy,
        threshold,
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
          <div className="form-grid two-columns">
            <label className="field"><span>抽样数量</span><input type="number" min="1" max={selected?.available_count || 10000} value={sampleSize} onChange={(event) => setSampleSize(Number(event.target.value))} /></label>
            <label className="field"><span>通过阈值</span><input type="number" min="0" max="100" value={threshold} onChange={(event) => setThreshold(Number(event.target.value))} /></label>
          </div>
          <fieldset className="strategy-field"><legend>抽样策略</legend>{[
            ["risk_first", "风险优先", "优先覆盖转人工、差评等高风险对话"],
            ["scenario_weighted", "场景均衡", "减少高频场景对结果的掩盖"],
            ["random", "纯随机", "用于观察整体质量水位"],
          ].map(([value, label, hint]) => <label key={value} className={strategy === value ? "active" : ""}><input type="radio" name="strategy" value={value} checked={strategy === value} onChange={() => setStrategy(value as typeof strategy)} /><strong>{label}</strong><small>{hint}</small></label>)}</fieldset>
          <button className="primary-button launch-button" disabled={busy || !importId || !provider?.configured}>{busy ? "正在创建…" : "启动真实评测 →"}</button>
          {error && <div className="operation-error" role="alert">{error}</div>}
        </form>
        <aside className="readiness-card">
          <span className="eyebrow">PRE-FLIGHT CHECK</span><h2>运行前检查</h2>
          <dl><div><dt>数据</dt><dd className={selected ? "ready" : ""}>{selected ? `${selected.available_count} 条可用` : "待选择"}</dd></div><div><dt>模型</dt><dd className={provider?.configured ? "ready" : "blocked"}>{provider?.configured ? provider.model : "未配置 API"}</dd></div><div><dt>资源估算</dt><dd>{sampleSize || 0} 次模型请求</dd></div></dl>
          {!provider?.configured && <p className="config-hint">在后端 `.env` 中设置 LLM_BASE_URL、LLM_API_KEY 和 LLM_MODEL 后即可启动。</p>}
        </aside>
      </div>
    </section>
  );
}
