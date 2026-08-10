import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { getRetestDetail, type RetestDetail, type RetestSampleDetail } from "../../app/retestApi";

type SampleFilter = "all" | "replay" | "new";

const DIMENSION_LABELS: Record<string, string> = {
  correctness: "准确性",
  completeness: "完整性",
  relevance: "相关性",
  service_experience: "服务体验",
  compliance: "合规性",
};

const percent = (value: number | null) => value === null ? "待评测" : `${Math.round(value * 100)}%`;
const ROLE_LABELS: Record<string, string> = { user: "用户", assistant: "AI 客服", system: "系统指令", tool: "工具", agent: "人工客服" };

export function RetestDetailView({ detail, filter, onFilterChange }: { detail: RetestDetail; filter: SampleFilter; onFilterChange: (filter: SampleFilter) => void }) {
  const visibleSamples = filter === "all" ? detail.samples : detail.samples.filter((sample) => sample.cohort === filter);
  const threshold = detail.method.cohort_pass_rate_threshold;
  return <section className="operation-page retest-detail-page">
    <header className="retest-detail-hero">
      <div><a className="text-link" href="/retests">← 返回发布与复测</a><span className="eyebrow">RETEST TRACE</span><h1>{detail.scenario}</h1><p>QA V{detail.qa_version_number} · {detail.published_by} 发布 · {detail.release_note || "未填写发布备注"}</p></div>
      <strong className={`retest-verdict state-${detail.workspace_state}`}>{detail.explanation.verdict}</strong>
    </header>

    <section className="retest-explanation">
      <div><span className="eyebrow">WHY THIS VERDICT</span><h2>为什么得到这个结论</h2><p>{detail.explanation.formula}。本次要求两组分别达到 {threshold === null ? "未配置" : `${Math.round(threshold * 100)}%`}。</p></div>
      <CohortResult label="历史回放" stats={detail.explanation.replay} />
      <CohortResult label="发布后新对话" stats={detail.explanation.new} />
    </section>

    <section className="retest-method-panel">
      <header><span className="eyebrow">HOW IT WORKS</span><h2>本次怎么复测</h2></header>
      <div className="retest-method-grid">
        <article><small>01 / 样本</small><strong>历史回放 + 发布后新对话</strong><p>{detail.method.sample_selection.replay}；{detail.method.sample_selection.new}。</p></article>
        <article><small>02 / 裁判</small><strong>{detail.method.quality_standard ? `${detail.method.quality_standard.name} ${detail.method.quality_standard.version}` : "未绑定公司质量标准"}</strong><p>Prompt {detail.method.prompt?.version || "-"} · 模型 {detail.method.model || "-"}</p></article>
        <article><small>03 / 判定</small><strong>单条 {detail.method.single_score_threshold ?? "-"} 分通过</strong><p>两组都达到 {threshold === null ? "-" : `${Math.round(threshold * 100)}%`} 才算改善有效。</p></article>
      </div>
      <details className="retest-prompt"><summary>查看模型使用的完整 Prompt</summary><pre>{detail.method.prompt?.content || "该历史任务没有保存 Prompt 内容。"}</pre></details>
    </section>

    <section className="retest-samples-section">
      <header><div><span className="eyebrow">SAMPLE EVIDENCE</span><h2>逐条复测明细</h2></div><nav aria-label="样本筛选"><FilterButton active={filter === "all"} onClick={() => onFilterChange("all")}>全部 {detail.samples.length}</FilterButton><FilterButton active={filter === "replay"} onClick={() => onFilterChange("replay")}>历史回放 {detail.explanation.replay.total}</FilterButton><FilterButton active={filter === "new"} onClick={() => onFilterChange("new")}>新对话 {detail.explanation.new.total}</FilterButton></nav></header>
      {visibleSamples.length ? <div className="retest-sample-list">{visibleSamples.map((sample, index) => <SampleCard key={sample.id} sample={sample} index={index} />)}</div> : <div className="retest-empty">当前分组还没有样本。</div>}
    </section>
  </section>;
}

function CohortResult({ label, stats }: { label: string; stats: RetestDetail["explanation"]["replay"] }) {
  return <article><span>{label}</span><strong>{stats.passed}/{stats.completed} 通过</strong><small>已选 {stats.total} 条 · 通过率 {percent(stats.pass_rate)}</small></article>;
}

function FilterButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return <button className={active ? "active" : ""} onClick={onClick}>{children}</button>;
}

function SampleCard({ sample, index }: { sample: RetestSampleDetail; index: number }) {
  const evaluation = sample.evaluation;
  return <article className={`retest-sample-card ${evaluation ? evaluation.passed ? "passed" : "failed" : "pending"}`}>
    <header><div><span>{String(index + 1).padStart(2, "0")}</span><strong>{sample.cohort === "replay" ? "历史回放" : "发布后新对话"}</strong><small>{sample.external_id}</small></div><div className="retest-sample-score"><strong>{evaluation ? Math.round(evaluation.total_score) : "—"}</strong><span>{evaluation ? evaluation.passed ? "通过" : "未通过" : "待评测"}</span></div></header>
    <div className="retest-transcript">{sample.conversation.messages.length ? sample.conversation.messages.map((message, messageIndex) => <div className={message.role} key={`${sample.id}-${messageIndex}`}><span>{ROLE_LABELS[message.role] || `其他角色（${message.role}）`}</span><p>{message.content}</p></div>) : <p className="retest-transcript-empty">该样本没有可展示的对话消息。</p>}</div>
    {evaluation ? <div className="retest-evaluation-detail">
      <div className="retest-dimensions">{Object.entries(evaluation.dimension_scores).map(([dimension, score]) => <div key={dimension}><span>{DIMENSION_LABELS[dimension] || dimension}</span><strong>{Math.round(score)}</strong><i><b style={{ width: `${score}%` }} /></i></div>)}</div>
      <div className="retest-reason"><section><small>评测理由</small><p>{evaluation.reason}</p></section><section><small>引用证据</small>{evaluation.evidence.length ? evaluation.evidence.map((evidence) => <blockquote key={evidence}>{evidence}</blockquote>) : <p>模型未返回引用证据。</p>}</section>{(evaluation.severe_factual_error || evaluation.severe_compliance_error) && <div className="retest-severe">{evaluation.severe_factual_error && <span>严重事实错误</span>}{evaluation.severe_compliance_error && <span>严重合规错误</span>}</div>}</div>
    </div> : <div className="retest-pending-result">该样本已被选中，尚未产生评测结果。</div>}
  </article>;
}

export function RetestDetailPage() {
  const { runId = "" } = useParams();
  const [detail, setDetail] = useState<RetestDetail | null>(null);
  const [filter, setFilter] = useState<SampleFilter>("all");
  const [error, setError] = useState("");
  useEffect(() => { void getRetestDetail(runId).then(setDetail).catch((reason) => setError(reason instanceof Error ? reason.message : "复测详情加载失败")); }, [runId]);
  if (error) return <div className="placeholder-page"><span className="eyebrow">LOAD FAILED</span><h1>复测详情暂时无法加载</h1><p>{error}</p><Link className="text-link" to="/retests">返回发布与复测</Link></div>;
  if (!detail) return <div className="page-state"><span className="loader" />正在整理复测过程与逐条结果…</div>;
  return <RetestDetailView detail={detail} filter={filter} onFilterChange={setFilter} />;
}
