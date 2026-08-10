import { useEffect, useState } from "react";

import { getProviderStatus } from "../../app/evaluationApi";
import { confirmIssueAttribution, generateIssueAttribution, getIssueDetail, listIssues, type IssueDetail, type IssueItem, type IssueListResponse, type IssueStatus, type RootCause } from "../../app/issueApi";

const ROOT_CAUSES: RootCause[] = ["missing_knowledge", "misunderstanding", "process_failure", "service_tone", "other"];
const ROOT_CAUSE_LABELS: Record<RootCause, string> = {
  missing_knowledge: "知识缺失",
  misunderstanding: "理解错误",
  process_failure: "流程执行错误",
  service_tone: "服务态度",
  other: "评测误报 / 其他",
};
const DIMENSION_LABELS: Record<string, string> = {
  correctness: "准确性",
  completeness: "完整性",
  relevance: "相关性",
  service_experience: "服务体验",
  compliance: "合规性",
};

export function rootCauseLabel(value: string): string {
  return ROOT_CAUSE_LABELS[value as RootCause] ?? value;
}

export function issueCauseDisplay(issue: Pick<IssueItem, "confirmed_root_cause" | "suggestion">): string {
  if (issue.confirmed_root_cause) return `人工：${rootCauseLabel(issue.confirmed_root_cause)}`;
  if (issue.suggestion) return `AI：${rootCauseLabel(issue.suggestion.root_cause)}`;
  return "未归因";
}

function confidenceLabel(value: string): string {
  return { high: "高置信度", medium: "中置信度", low: "低置信度" }[value] ?? value;
}

function taskLabel(value: string): string {
  return {
    qa_review: "QA 审核任务",
    prompt_optimization: "Prompt 优化任务",
    process_investigation: "流程排查任务",
    tone_optimization: "话术优化任务",
    evaluation_calibration: "评测校准任务",
  }[value] ?? value;
}

interface DetailProps {
  detail: IssueDetail;
  providerConfigured: boolean;
  busy: string;
  rootCause: RootCause;
  evidence: string;
  clusterConfirmed: boolean;
  onGenerate: () => void;
  onRootCauseChange: (value: RootCause) => void;
  onEvidenceChange: (value: string) => void;
  onClusterConfirmedChange: (value: boolean) => void;
  onConfirm: () => void;
}

export function IssueDetailView(props: DetailProps) {
  const { detail, providerConfigured, busy, rootCause, evidence, clusterConfirmed } = props;
  const needsExplicitConfirmation = detail.suggestion?.confidence !== "high";
  const canConfirm = Boolean(evidence.trim()) && (!needsExplicitConfirmation || clusterConfirmed);
  return <main className="issue-detail">
    <header className="issue-detail-head">
      <div><span>{detail.priority} · {detail.status === "confirmed" ? "已确认" : "待确认"}</span><h2>{detail.scenario || "未分类场景"}</h2><p>{detail.problem_summary}</p></div>
      <div className="issue-impact"><strong>{detail.impact_count}</strong><small>条受影响对话</small></div>
    </header>

    <section className="issue-facts">
      <div><span>最低维度</span><strong>{DIMENSION_LABELS[detail.weakest_dimension] ?? detail.weakest_dimension}</strong></div>
      <div><span>关联运行</span><a href={`/runs/${detail.run_id}`}>查看评测 →</a></div>
      <div><span>异常幅度</span><strong>{detail.alert ? `${Math.round(detail.alert.baseline_value * 100)}% → ${Math.round(detail.alert.current_value * 100)}%` : "未关联告警"}</strong></div>
    </section>

    <section className="issue-section">
      <div className="issue-section-title"><span>01 / EVIDENCE</span><h3>代表性失败样本</h3><small>展示最多 3 条，内容已脱敏</small></div>
      <div className="issue-samples">{detail.samples.map((sample) => <article key={sample.result_id}>
        <header><div><strong>{sample.score}</strong><span>分 · {confidenceLabel(sample.confidence)}</span></div><small>{sample.external_id}</small></header>
        <p className="sample-reason">{sample.reason}</p>
        <div className="message-stack">{sample.messages.map((message, index) => <p className={message.role === "assistant" ? "assistant" : "user"} key={`${message.role}-${index}`}><b>{message.role === "assistant" ? "AI" : "用户"}</b><span>{message.content}</span></p>)}</div>
      </article>)}</div>
    </section>

    <section className="issue-section attribution-section">
      <div className="issue-section-title"><span>02 / ATTRIBUTION</span><h3>AI 归因建议</h3><small>仅点击时调用一次模型</small></div>
      {detail.suggestion ? <div className="suggestion-card">
        <header><strong>{rootCauseLabel(detail.suggestion.root_cause)}</strong><span>{confidenceLabel(detail.suggestion.confidence)}</span></header>
        <p>{detail.suggestion.reason}</p>
        <blockquote>{detail.suggestion.evidence.map((item) => <span key={item}>“{item}”</span>)}</blockquote>
        <small>{detail.suggestion.provider} · {detail.suggestion.model}</small>
      </div> : <div className="generate-attribution"><div><strong>尚未分析根因</strong><p>查看上方样本后，再按需调用模型，避免无效 Token 消耗。</p></div><button className="primary-button" disabled={!providerConfigured || Boolean(busy)} onClick={props.onGenerate}>{busy === "generate" ? "正在分析…" : providerConfigured ? "生成 AI 归因建议 →" : "模型未配置"}</button></div>}
    </section>

    {detail.suggestion && <section className="issue-section decision-section">
      <div className="issue-section-title"><span>03 / HUMAN DECISION</span><h3>人工确认与任务分流</h3><small>最终原因以人工确认结果为准</small></div>
      {detail.confirmation ? <div className="confirmed-attribution"><span>已确认</span><div><strong>{rootCauseLabel(detail.confirmation.root_cause)}</strong><p>{detail.confirmation.confirmed_by} · {detail.confirmation.confirmed_at ? new Date(detail.confirmation.confirmed_at).toLocaleString("zh-CN") : "时间未记录"}</p></div>{detail.task && <div className="routed-task"><small>已创建</small><strong>{taskLabel(detail.task.type)}</strong><span>{detail.task.status}</span></div>}</div> : <div className="decision-form">
        <label><span>最终原因</span><select value={rootCause} onChange={(event) => props.onRootCauseChange(event.target.value as RootCause)}>{ROOT_CAUSES.map((cause) => <option value={cause} key={cause}>{rootCauseLabel(cause)}</option>)}</select></label>
        <label><span>人工确认依据</span><textarea value={evidence} placeholder="写明你根据哪些样本或业务事实作出判断" onChange={(event) => props.onEvidenceChange(event.target.value)} /></label>
        {needsExplicitConfirmation && <label className="cluster-confirm"><input type="checkbox" checked={clusterConfirmed} onChange={(event) => props.onClusterConfirmedChange(event.target.checked)} /><span><strong>我已检查代表样本，并确认整个问题簇使用同一原因</strong><small>当前为{confidenceLabel(detail.suggestion.confidence)}，需要人工明确确认后才能批量处理。</small></span></label>}
        <button className="primary-button" disabled={!canConfirm || Boolean(busy)} onClick={props.onConfirm}>{busy === "confirm" ? "正在创建任务…" : "确认归因并创建任务 →"}</button>
      </div>}
    </section>}
  </main>;
}

export function IssueWorkspacePage() {
  const [status, setStatus] = useState<IssueStatus>("pending");
  const [data, setData] = useState<IssueListResponse | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState<IssueDetail | null>(null);
  const [providerConfigured, setProviderConfigured] = useState(false);
  const [rootCause, setRootCause] = useState<RootCause>("other");
  const [evidence, setEvidence] = useState("");
  const [clusterConfirmed, setClusterConfirmed] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  function applyDetail(value: IssueDetail) {
    setDetail(value);
    setRootCause(value.suggestion?.root_cause ?? "other");
    setEvidence(value.suggestion?.reason ?? "");
    setClusterConfirmed(false);
  }

  async function refresh(preferredId?: string) {
    const response = await listIssues(status);
    setData(response);
    const nextId = response.items.find((item) => item.id === (preferredId || selectedId))?.id ?? response.items[0]?.id ?? "";
    setSelectedId(nextId);
    if (nextId) applyDetail(await getIssueDetail(nextId));
    else setDetail(null);
  }

  useEffect(() => { void refresh().catch((reason) => setError(reason instanceof Error ? reason.message : "问题列表加载失败")); }, [status]);
  useEffect(() => { void getProviderStatus().then((value) => setProviderConfigured(value.configured)).catch(() => setProviderConfigured(false)); }, []);

  async function choose(item: IssueItem) {
    setSelectedId(item.id); setError(""); setBusy("detail");
    try { applyDetail(await getIssueDetail(item.id)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "问题详情加载失败"); }
    finally { setBusy(""); }
  }

  async function generate() {
    if (!detail) return;
    setBusy("generate"); setError("");
    try { await generateIssueAttribution(detail.id); await refresh(detail.id); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "AI 归因失败"); }
    finally { setBusy(""); }
  }

  async function confirm() {
    if (!detail) return;
    setBusy("confirm"); setError("");
    try {
      await confirmIssueAttribution(detail.id, { actor: "林乔", root_cause: rootCause, evidence: [evidence.trim()], confirm_cluster: true });
      await refresh(detail.id);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "归因确认失败"); }
    finally { setBusy(""); }
  }

  if (!data && error) return <div className="placeholder-page"><span className="eyebrow">LOAD FAILED</span><h1>问题数据暂时无法加载</h1><p>{error}</p><a className="text-link" href="/alerts">重新加载</a></div>;
  if (!data) return <div className="page-state"><span className="loader" />正在整理失败案例…</div>;
  return <section className="operation-page issue-page">
    <header className="operation-hero"><div><span className="eyebrow">ISSUE ATTRIBUTION</span><h1>从“不好”定位到<br />具体该改什么</h1></div><p>系统把相似失败案例聚成问题。先核对证据，再按需让 AI 建议原因，最终由你确认并生成改进任务。</p></header>
    <section className="issue-summary" aria-label="问题概况">
      <div><strong>{data.summary.pending_count}</strong><span>待确认问题<small>需要人工判断原因</small></span></div>
      <div><strong>{data.summary.confirmed_count}</strong><span>已确认问题<small>已经进入改进流程</small></span></div>
      <div><strong>{data.summary.impacted_count}</strong><span>影响案例<small>按问题簇累计</small></span></div>
      <div><strong>{data.summary.missing_knowledge_count}</strong><span>知识缺失<small>可进入 QA 审核</small></span></div>
    </section>
    <div className="issue-filter"><span>处理队列</span>{(["pending", "confirmed", "all"] as IssueStatus[]).map((value) => <button className={status === value ? "active" : ""} key={value} onClick={() => setStatus(value)}>{value === "pending" ? "待确认" : value === "confirmed" ? "已确认" : "全部"}</button>)}</div>
    {data.items.length ? <div className="issue-layout">
      <aside className="issue-queue">{data.items.map((item, index) => <button className={selectedId === item.id ? "active" : ""} key={item.id} onClick={() => void choose(item)}><span className={`issue-priority ${item.priority.toLowerCase()}`}>{item.priority}</span><small>{String(index + 1).padStart(2, "0")} · {item.status === "confirmed" ? "已确认" : item.suggestion ? "待人工确认" : "待 AI 分析"}</small><strong>{item.scenario || "未分类场景"}</strong><p>{item.problem_summary}</p><footer><span>影响 {item.impact_count} 条</span><b>{issueCauseDisplay(item)}</b></footer></button>)}</aside>
      {detail ? <IssueDetailView detail={detail} providerConfigured={providerConfigured} busy={busy} rootCause={rootCause} evidence={evidence} clusterConfirmed={clusterConfirmed} onGenerate={() => void generate()} onRootCauseChange={setRootCause} onEvidenceChange={setEvidence} onClusterConfirmedChange={setClusterConfirmed} onConfirm={() => void confirm()} /> : <div className="issue-detail-empty">请选择一个问题</div>}
    </div> : <div className="issue-empty"><span>00</span><h2>{status === "pending" ? "当前没有待确认问题" : "当前筛选下没有问题"}</h2><p>完成一次包含失败案例的真实评测后，系统会自动在这里生成问题簇。</p><a className="primary-button" href="/runs/new">发起一次评测 →</a></div>}
    {error && <div className="operation-error" role="alert">{error}</div>}
  </section>;
}
