import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { getEvaluation, getEvaluationResults } from "../../app/evaluationApi";

const stages = ["采样", "评测", "归因", "产物", "完成"];
const dimensionLabels: Record<string, string> = { correctness: "准确性", completeness: "完整性", relevance: "相关性", service_experience: "服务体验", compliance: "合规性" };

export function RunDetailPage() {
  const { runId = "" } = useParams();
  const detailQuery = useQuery({
    queryKey: ["evaluation", runId],
    queryFn: () => getEvaluation(runId),
    enabled: Boolean(runId),
    refetchInterval: (query) => ["completed", "partial", "manual_review"].includes(query.state.data?.stage || "") ? false : 1500,
  });
  const resultsQuery = useQuery({
    queryKey: ["evaluation-results", runId, detailQuery.data?.completed_count],
    queryFn: () => getEvaluationResults(runId),
    enabled: Boolean(detailQuery.data?.completed_count),
  });
  const detail = detailQuery.data;
  if (detailQuery.isLoading) return <div className="page-state"><span className="loader" />正在读取运行状态</div>;
  if (!detail) return <div className="placeholder-page"><h1>评测运行不可用</h1><p>{detailQuery.error?.message}</p></div>;
  const progress = detail.sample_count ? Math.round(detail.completed_count / detail.sample_count * 100) : 0;
  const activeStage = detail.stage === "completed" ? 4 : detail.stage === "evaluating" ? 1 : 0;

  return (
    <section className="operation-page run-page">
      <header className="run-header"><div><span className="eyebrow">LIVE EVALUATION</span><h1>评测运行</h1><p>{detail.run_id} · {detail.model} · Prompt {detail.prompt.version.toUpperCase()}{detail.quality_standard ? ` · ${detail.quality_standard.name} V${detail.quality_standard.version}` : ""}</p>{detail.quality_standard && <Link className="rule-version-link" to={`/rules/versions/${detail.quality_standard.version_id}`}>查看完整规则 →</Link>}</div><span className={`run-state ${detail.stage}`}>{detail.stage === "completed" ? "已完成" : detail.stage === "evaluating" ? "评测中" : detail.stage}</span></header>
      <div className="stage-rail">{stages.map((stage, index) => <div key={stage} className={index < activeStage || detail.stage === "completed" ? "done" : index === activeStage ? "active" : ""}><span>{String(index + 1).padStart(2, "0")}</span><strong>{stage}</strong></div>)}</div>
      <div className="run-metrics"><div><span>完成进度</span><strong>{detail.completed_count}<small> / {detail.sample_count}</small></strong><div className="progress-track"><i style={{ width: `${progress}%` }} /></div></div><div><span>通过率</span><strong>{detail.pass_rate === null ? "—" : `${(detail.pass_rate * 100).toFixed(1)}%`}</strong><small>{detail.passed_count} 通过 / {detail.failed_count} 失败</small></div><div><span>平均分</span><strong>{detail.average_score ?? "—"}</strong><small>通过阈值见本次配置</small></div></div>
      {detail.latest_error && <div className="operation-error">最近一次模型请求异常：{detail.latest_error}</div>}
      <div className="results-layout">
        <section className="result-list"><div className="section-heading compact"><div><span className="eyebrow">SAMPLE VERDICTS</span><h2>样本判定</h2></div><small>最近 {resultsQuery.data?.items.length || 0} 条</small></div>{resultsQuery.data?.items.map((result) => <article key={result.id} className={result.passed ? "passed" : "failed"}><div className="result-score"><strong>{result.score}</strong><small>{result.passed ? "PASS" : "FAIL"}</small></div><div><header><strong>{result.scenario || "未分类场景"}</strong><small>置信度 {result.confidence}</small></header><p>{result.reason}</p>{result.evidence.length > 0 && <blockquote>{result.evidence[0]}</blockquote>}</div></article>)}{!resultsQuery.data?.items.length && <div className="empty-results">评测 worker 完成第一条后，结果会自动出现在这里。</div>}</section>
        <aside className="dimension-card"><span className="eyebrow">DIMENSIONS</span><h2>维度均分</h2>{Object.entries(detail.dimension_averages).map(([name, score]) => <div key={name}><span>{dimensionLabels[name] || name}</span><strong>{score}</strong><i><b style={{ width: `${score}%` }} /></i></div>)}{Object.keys(detail.dimension_averages).length === 0 && <p>等待评测结果…</p>}<Link className="secondary-button" to="/runs/new">发起新评测</Link></aside>
      </div>
    </section>
  );
}
