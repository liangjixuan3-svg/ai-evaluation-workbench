import { useEffect, useState } from "react";

import { getProviderStatus } from "../../app/evaluationApi";
import { approveQA, downloadQA, generateQA, getQADetail, listQA, rejectQA, type QAContent, type QADetail, type QAFilter, type QAItem, type QAListResponse, type QAState } from "../../app/qaApi";

const EMPTY_CONTENT: QAContent = {
  question: "",
  answer: "",
  applicability: "",
  handling_steps: [],
  estimated_time: "",
  escalation: "",
};

const FIELD_LABELS: Record<keyof QAContent, string> = {
  question: "问题写法",
  answer: "标准回答",
  applicability: "适用范围",
  handling_steps: "处理步骤",
  estimated_time: "预计时效",
  escalation: "升级条件",
};

export function qaStateLabel(value: QAState): string {
  return {
    awaiting_generation: "待生成",
    pending_review: "待审核",
    approved: "已通过",
    rejected: "已驳回",
  }[value];
}

interface QADetailViewProps {
  detail: QADetail;
  providerConfigured: boolean;
  busy: string;
  content: QAContent;
  evidence: { source_ref: string; excerpt: string };
  rejectionReason: string;
  onContentChange: (value: QAContent) => void;
  onEvidenceChange: (value: { source_ref: string; excerpt: string }) => void;
  onRejectionReasonChange: (value: string) => void;
  onGenerate: () => void;
  onApprove: () => void;
  onReject: () => void;
  onDownload: (format: "json" | "csv") => void;
}

export function QADetailView(props: QADetailViewProps) {
  const { detail, content, evidence, rejectionReason, busy } = props;
  const complete = Object.entries(content).every(([, value]) => Array.isArray(value) ? value.length > 0 && value.every(Boolean) : Boolean(value.trim()));
  const canApprove = complete && Boolean(evidence.source_ref.trim()) && Boolean(evidence.excerpt.trim());

  function update(field: keyof QAContent, value: string) {
    props.onContentChange({
      ...content,
      [field]: field === "handling_steps" ? value.split("\n").map((item) => item.trim()).filter(Boolean) : value,
    });
  }

  return <main className="qa-detail">
    <header className="qa-detail-head">
      <div><span>{detail.priority} · {qaStateLabel(detail.state)}</span><h2>{detail.scenario || "未分类场景"}</h2><p>{detail.problem_summary}</p></div>
      <div className="qa-impact"><strong>{detail.impact_count}</strong><small>条失败对话</small></div>
    </header>

    <section className="qa-facts">
      <div><span>人工归因</span><strong>知识缺失</strong></div>
      <div><span>最低维度</span><strong>{detail.weakest_dimension}</strong></div>
      <div><span>任务状态</span><strong>{detail.task_status}</strong></div>
    </section>

    <section className="qa-section">
      <div className="qa-section-title"><span>01 / EVIDENCE</span><h3>问题证据</h3><small>生成和审核前先核对真实失败对话</small></div>
      <div className="qa-samples">{detail.samples.map((sample) => <article key={sample.result_id}>
        <header><strong>{sample.score} 分</strong><small>{sample.external_id}</small></header>
        <p>{sample.reason}</p>
        <div className="message-stack">{sample.messages.map((message, index) => <p className={message.role === "assistant" ? "assistant" : "user"} key={`${message.role}-${index}`}><b>{message.role === "assistant" ? "AI" : "用户"}</b><span>{message.content}</span></p>)}</div>
      </article>)}</div>
    </section>

    {!detail.draft && <section className="qa-section qa-generate">
      <div className="qa-section-title"><span>02 / GENERATE</span><h3>按需生成 QA 草稿</h3><small>仅点击后调用一次模型，避免无效 Token 消耗</small></div>
      <div className="generate-attribution"><div><strong>还没有 QA 草稿</strong><p>模型会参考问题、归因和代表样本生成六项可编辑内容。</p></div><button className="primary-button" disabled={!props.providerConfigured || Boolean(busy)} onClick={props.onGenerate}>{busy === "generate" ? "正在生成…" : props.providerConfigured ? "生成 QA 草稿 →" : "模型未配置"}</button></div>
    </section>}

    {detail.draft && detail.state === "pending_review" && <section className="qa-section">
      <div className="qa-section-title"><span>02 / REVIEW</span><h3>编辑并审核 QA</h3><small>AI 草稿不是最终答案，发布前必须补充业务依据</small></div>
      <div className="qa-editor">
        {(Object.keys(FIELD_LABELS) as Array<keyof QAContent>).map((field) => <label className={field === "answer" || field === "handling_steps" ? "wide" : ""} key={field}><span>{FIELD_LABELS[field]}</span>{field === "answer" || field === "handling_steps" ? <textarea value={field === "handling_steps" ? content[field].join("\n") : content[field]} onChange={(event) => update(field, event.target.value)} /> : <input value={content[field] as string} onChange={(event) => update(field, event.target.value)} />}</label>)}
      </div>
      <div className="qa-business-evidence">
        <header><strong>业务依据</strong><span>必填，不能只凭模型判断</span></header>
        <label><span>制度 / 文档名称</span><input value={evidence.source_ref} placeholder="例如：退款规则 2026 V3" onChange={(event) => props.onEvidenceChange({ ...evidence, source_ref: event.target.value })} /></label>
        <label><span>支持本 QA 的原文摘录</span><textarea value={evidence.excerpt} placeholder="粘贴能够证明回答内容的制度原文" onChange={(event) => props.onEvidenceChange({ ...evidence, excerpt: event.target.value })} /></label>
      </div>
      <div className="qa-review-actions">
        <div><label><span>驳回原因</span><input value={rejectionReason} placeholder="仅在驳回时填写" onChange={(event) => props.onRejectionReasonChange(event.target.value)} /></label><button className="danger-button" disabled={!rejectionReason.trim() || Boolean(busy)} onClick={props.onReject}>{busy === "reject" ? "正在驳回…" : "驳回草稿"}</button></div>
        <button className="primary-button" disabled={!canApprove || Boolean(busy)} onClick={props.onApprove}>{busy === "approve" ? "正在锁定…" : "审核通过并锁定 →"}</button>
      </div>
    </section>}

    {detail.draft && detail.state === "approved" && <section className="qa-section qa-finished approved">
      <div className="qa-section-title"><span>02 / APPROVED</span><h3>QA 已审核通过</h3><small>V{detail.draft.version_number} 已锁定，可交付知识库团队</small></div>
      <div className="qa-readonly">{(Object.keys(FIELD_LABELS) as Array<keyof QAContent>).map((field) => <div key={field}><span>{FIELD_LABELS[field]}</span><strong>{Array.isArray(content[field]) ? content[field].join("；") : content[field]}</strong></div>)}</div>
      <div className="qa-downloads"><button className="secondary-button" disabled={Boolean(busy)} onClick={() => props.onDownload("json")}>下载 JSON</button><button className="secondary-button" disabled={Boolean(busy)} onClick={() => props.onDownload("csv")}>下载 CSV</button></div>
    </section>}

    {detail.draft && detail.state === "rejected" && <section className="qa-section qa-finished rejected"><div className="qa-section-title"><span>02 / REJECTED</span><h3>QA 草稿已驳回</h3><small>任务已关闭，不会进入知识库交付</small></div><blockquote>{detail.draft.rejection_reason || "未记录驳回原因"}</blockquote></section>}
  </main>;
}

export function QAWorkspacePage() {
  const [status, setStatus] = useState<QAFilter>("pending");
  const [data, setData] = useState<QAListResponse | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState<QADetail | null>(null);
  const [content, setContent] = useState<QAContent>(EMPTY_CONTENT);
  const [evidence, setEvidence] = useState({ source_ref: "", excerpt: "" });
  const [rejectionReason, setRejectionReason] = useState("");
  const [providerConfigured, setProviderConfigured] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  function applyDetail(value: QADetail) {
    setDetail(value);
    setContent(value.draft?.content ?? EMPTY_CONTENT);
    const businessEvidence = value.draft?.evidence.find((item) => item.source_type === "business_reference");
    setEvidence({ source_ref: businessEvidence?.source_ref ?? "", excerpt: businessEvidence?.excerpt ?? "" });
    setRejectionReason(value.draft?.rejection_reason ?? "");
  }

  async function refresh(preferredId?: string) {
    const response = await listQA(status);
    setData(response);
    const nextId = response.items.find((item) => item.task_id === (preferredId || selectedId))?.task_id ?? response.items[0]?.task_id ?? "";
    setSelectedId(nextId);
    if (nextId) applyDetail(await getQADetail(nextId));
    else setDetail(null);
  }

  useEffect(() => { void refresh().catch((reason) => setError(reason instanceof Error ? reason.message : "QA 列表加载失败")); }, [status]);
  useEffect(() => { void getProviderStatus().then((value) => setProviderConfigured(value.configured)).catch(() => setProviderConfigured(false)); }, []);

  async function choose(item: QAItem) {
    setSelectedId(item.task_id); setBusy("detail"); setError("");
    try { applyDetail(await getQADetail(item.task_id)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "QA 详情加载失败"); }
    finally { setBusy(""); }
  }

  async function runAction(kind: string, action: () => Promise<unknown>, nextStatus?: QAFilter) {
    if (!detail) return;
    setBusy(kind); setError("");
    try {
      await action();
      if (nextStatus) setStatus(nextStatus);
      else await refresh(detail.task_id);
    }
    catch (reason) { setError(reason instanceof Error ? reason.message : "操作失败"); }
    finally { setBusy(""); }
  }

  async function download(format: "json" | "csv") {
    if (!detail?.draft) return;
    setBusy("download"); setError("");
    try {
      const response = await downloadQA([detail.draft.id], format, "林乔");
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url; link.download = `qa-export.${format}`; link.click();
      URL.revokeObjectURL(url);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "下载失败"); }
    finally { setBusy(""); }
  }

  if (!data && error) return <div className="placeholder-page"><span className="eyebrow">LOAD FAILED</span><h1>QA 任务暂时无法加载</h1><p>{error}</p><a className="text-link" href="/qa">重新加载</a></div>;
  if (!data) return <div className="page-state"><span className="loader" />正在整理 QA 审核任务…</div>;
  return <section className="operation-page qa-page">
    <header className="operation-hero"><div><span className="eyebrow">QA REVIEW DESK</span><h1>把知识缺口<br />变成可发布 QA</h1></div><p>先核对失败证据，再按需生成和编辑 QA。只有具备业务制度依据的内容才能审核通过并交付。</p></header>
    <section className="qa-summary" aria-label="QA 审核概况">
      <div><strong>{data.summary.awaiting_generation_count}</strong><span>待生成<small>尚未调用模型</small></span></div>
      <div><strong>{data.summary.pending_review_count}</strong><span>待审核<small>需要人工核对</small></span></div>
      <div><strong>{data.summary.approved_count}</strong><span>已通过<small>可下载交付</small></span></div>
      <div><strong>{data.summary.rejected_count}</strong><span>已驳回<small>已记录原因</small></span></div>
    </section>
    <div className="issue-filter"><span>审核队列</span>{(["pending", "approved", "rejected", "all"] as QAFilter[]).map((value) => <button className={status === value ? "active" : ""} key={value} onClick={() => setStatus(value)}>{value === "pending" ? "待处理" : value === "approved" ? "已通过" : value === "rejected" ? "已驳回" : "全部"}</button>)}</div>
    {data.items.length ? <div className="qa-layout"><aside className="qa-queue">{data.items.map((item, index) => <button className={selectedId === item.task_id ? "active" : ""} key={item.task_id} onClick={() => void choose(item)}><span className={`issue-priority ${item.priority.toLowerCase()}`}>{item.priority}</span><small>{String(index + 1).padStart(2, "0")} · {qaStateLabel(item.state)}</small><strong>{item.scenario || "未分类场景"}</strong><p>{item.problem_summary}</p><footer><span>影响 {item.impact_count} 条</span><b>{item.confidence ? `${item.confidence} 置信度` : "等待生成"}</b></footer></button>)}</aside>{detail ? <QADetailView detail={detail} providerConfigured={providerConfigured} busy={busy} content={content} evidence={evidence} rejectionReason={rejectionReason} onContentChange={setContent} onEvidenceChange={setEvidence} onRejectionReasonChange={setRejectionReason} onGenerate={() => void runAction("generate", () => generateQA(detail.task_id))} onApprove={() => void runAction("approve", () => approveQA(detail.draft!.id, { actor: "林乔", edits: { ...content, business_evidence: [evidence] } }), "approved")} onReject={() => void runAction("reject", () => rejectQA(detail.draft!.id, { actor: "林乔", reason: rejectionReason.trim() }), "rejected")} onDownload={(format) => void download(format)} /> : <div className="issue-detail-empty">请选择一个 QA 任务</div>}</div> : <div className="issue-empty"><span>00</span><h2>当前筛选下没有 QA 任务</h2><p>在“问题与归因”中确认知识缺失后，系统会在这里创建审核任务。</p><a className="primary-button" href="/alerts">前往问题与归因 →</a></div>}
    {error && <div className="operation-error" role="alert">{error}</div>}
  </section>;
}
