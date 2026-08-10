import { useEffect, useRef, useState } from "react";

import { agreeCalibration, disagreeCalibration, ensureTodayCalibrationBatch, getCalibrationReview, getCalibrationWorkspace, type CalibrationDimension, type CalibrationFilter, type CalibrationReviewDetail, type CalibrationWorkspace, type CalibrationWorkspaceItem } from "../../app/calibrationApi";

const DIMENSIONS: CalibrationDimension[] = ["correctness", "completeness", "compliance", "tone"];

const DIMENSION_LABELS: Record<CalibrationDimension, string> = {
  correctness: "准确性",
  completeness: "完整性",
  compliance: "合规性",
  tone: "服务体验",
};

const SELECTION_LABELS = {
  low_confidence: "低置信度",
  score_boundary: "临界分",
  severe_error: "严重错误",
  random_sample: "随机抽样",
};

let todayBatchPromise: Promise<unknown> | null = null;

function prepareTodayBatch(): Promise<unknown> {
  if (!todayBatchPromise) {
    todayBatchPromise = ensureTodayCalibrationBatch().finally(() => { todayBatchPromise = null; });
  }
  return todayBatchPromise;
}

export function calibrationDimensionLabel(value: CalibrationDimension | null): string {
  return value ? DIMENSION_LABELS[value] : "暂无";
}

function selectionLabel(value: CalibrationWorkspaceItem["selection_reason"]): string {
  return SELECTION_LABELS[value];
}

function percentage(value: number | null): string {
  return value === null ? "待复核" : `${Math.round(value * 100)}%`;
}

interface CalibrationWorkspaceViewProps {
  workspace: CalibrationWorkspace;
  status: CalibrationFilter;
  detail: CalibrationReviewDetail | null;
  selectedId: string;
  busy: string;
  error: string;
  actor: string;
  correctedPassed: boolean | null;
  disagreementDimension: CalibrationDimension | "";
  reviewBasis: string;
  showDisagreeForm: boolean;
  showAgreeConfirmation?: boolean;
  detailLoading?: boolean;
  onSelect: (item: CalibrationWorkspaceItem) => void;
  onStatusChange: (status: CalibrationFilter) => void;
  onActorChange: (value: string) => void;
  onCorrectedPassedChange: (value: boolean | null) => void;
  onDisagreementDimensionChange: (value: CalibrationDimension | "") => void;
  onReviewBasisChange: (value: string) => void;
  onShowDisagreeFormChange: (value: boolean) => void;
  onAgree: () => void;
  onDisagree: () => void;
  onRequestAgree?: () => void;
  onCancelAgree?: () => void;
}

export function CalibrationWorkspaceView(props: CalibrationWorkspaceViewProps) {
  const { workspace, detail } = props;
  const canDisagree = Boolean(props.actor.trim()) && props.correctedPassed !== null && Boolean(props.disagreementDimension) && Boolean(props.reviewBasis.trim());
  const isPending = detail?.status === "pending";
  const filterLabels: Record<CalibrationFilter, string> = { pending: "待复核", reviewed: "已复核", all: "全部" };
  return <section className="operation-page calibration-page">
    <header className="operation-hero"><div><span className="eyebrow">EVALUATION CALIBRATION</span><h1>评测校准</h1></div><p>核对模型判定是否可靠；不认同的案例会固定为回归案例，帮助后续规则和 Prompt 迭代。</p></header>
    <section className="calibration-summary" aria-label="今日校准概况">
      <div><strong>{workspace.summary.reviewed} / {workspace.summary.total}</strong><span>今日进度<small>已复核 / 今日案例</small></span></div>
      <div><strong>{workspace.summary.pending}</strong><span>待复核<small>仍需要人工判断</small></span></div>
      <div><strong>{percentage(workspace.summary.agreement_rate)}</strong><span>人机一致率<small>认同数 / 已复核数</small></span></div>
      <div><strong>{calibrationDimensionLabel(workspace.summary.top_disagreement_dimension)}</strong><span>主要分歧维度<small>不认同案例中出现最多</small></span></div>
    </section>
    <nav className="calibration-filter" aria-label="校准队列筛选"><span>复核队列</span>{(["pending", "reviewed", "all"] as CalibrationFilter[]).map((status) => <button aria-pressed={props.status === status} className={props.status === status ? "active" : ""} key={status} onClick={() => props.onStatusChange(status)}>{filterLabels[status]}</button>)}</nav>
    {workspace.items.length ? <div className="calibration-layout">
      <aside className="calibration-queue" aria-label="校准任务列表">{workspace.items.map((item, index) => <button aria-current={props.selectedId === item.review_id ? "true" : undefined} className={props.selectedId === item.review_id ? "active" : ""} key={item.review_id} onClick={() => props.onSelect(item)}>
        <span className={`calibration-status ${item.status}`}>{item.status === "pending" ? "待复核" : "已复核"}</span><small>{String(index + 1).padStart(2, "0")} · {selectionLabel(item.selection_reason)}</small><strong>{item.scenario || "未分类场景"}</strong><p>模型 {item.total_score} 分 · {item.passed ? "通过" : "不通过"}</p><footer><span>{item.confidence === "low" ? "低置信度" : item.confidence === "medium" ? "中置信度" : "高置信度"}</span><b>{item.include_in_regression ? "回归案例" : selectionLabel(item.selection_reason)}</b></footer>
      </button>)}</aside>
      {detail ? <CalibrationDetailView {...props} detail={detail} canDisagree={canDisagree} isPending={isPending} /> : <div className="calibration-detail-empty" aria-live="polite">{props.detailLoading ? "正在加载校准详情…" : props.selectedId ? "校准详情暂时无法加载" : "请选择一个校准任务"}</div>}
    </div> : <div className="calibration-empty"><span>00</span><h2>{workspace.summary.pending === 0 ? "今日复核已完成" : "当前筛选下没有校准任务"}</h2><p>{workspace.summary.pending === 0 ? "明天首次进入时，系统会准备新的待复核案例。" : "切换筛选可查看其他状态的校准任务。"}</p></div>}
    {props.error && <div className="operation-error" role="alert">{props.error}</div>}
  </section>;
}

function CalibrationDetailView(props: CalibrationWorkspaceViewProps & { detail: CalibrationReviewDetail; canDisagree: boolean; isPending: boolean }) {
  const confirmButtonRef = useRef<HTMLButtonElement>(null);
  useEffect(() => { if (props.showAgreeConfirmation) confirmButtonRef.current?.focus(); }, [props.showAgreeConfirmation]);
  const { detail } = props;
  return <article className="calibration-detail" aria-label="校准详情">
    <header className="calibration-detail-head"><div><span>{selectionLabel(detail.selection_reason)} · {detail.status === "pending" ? "等待人工复核" : "复核已完成"}</span><h2>{detail.conversation.scenario || "未分类场景"}</h2><p>为什么进入复核：{selectionLabel(detail.selection_reason)}。案例编号 {detail.conversation.external_id}</p></div><div className="calibration-score"><strong>{detail.evaluation.total_score}</strong><small>模型总分</small></div></header>
    <section className="calibration-section"><SectionTitle number="01" title="脱敏对话" description="仅展示已脱敏的完整对话内容" /><div className="calibration-transcript">{detail.conversation.messages.map((message, index) => <div className={message.role === "assistant" ? "assistant" : "user"} key={`${message.role}-${index}`}><span>{message.role === "assistant" ? "AI" : "用户"}</span><p>{message.content}</p></div>)}</div></section>
    <section className="calibration-section"><SectionTitle number="02" title="模型判定" description="原始模型结果不会被人工复核覆盖" /><div className="calibration-evaluation"><div><span>通过结论</span><strong>{detail.evaluation.passed ? "通过" : "不通过"}</strong></div><div><span>置信度</span><strong>{detail.evaluation.confidence === "low" ? "低" : detail.evaluation.confidence === "medium" ? "中" : "高"}</strong></div>{Object.entries(detail.evaluation.dimension_scores).map(([dimension, score]) => <div key={dimension}><span>{calibrationDimensionLabel(dimension as CalibrationDimension)}</span><strong>{score} 分</strong></div>)}</div></section>
    <section className="calibration-section"><SectionTitle number="03" title="模型评测理由" description="核对理由、证据和严重错误标记后再作出判断" /><div className="calibration-reason"><p>{detail.evaluation.reason}</p>{detail.evaluation.evidence.length > 0 && <blockquote>{detail.evaluation.evidence.map((item) => <span key={item}>{item}</span>)}</blockquote>}<div>{detail.evaluation.severe_factual_error && <b>标记：严重事实错误</b>}{detail.evaluation.severe_compliance_error && <b>标记：严重合规错误</b>}{!detail.evaluation.severe_factual_error && !detail.evaluation.severe_compliance_error && <b>未标记严重错误</b>}</div></div></section>
    <section className="calibration-section"><SectionTitle number="04" title="本次评测版本" description="用于判断的规则、Prompt 与模型均已锁定" /><dl className="calibration-versions"><div><dt>公司质量标准</dt><dd>{detail.locked_rule.quality_standard ? `V${detail.locked_rule.quality_standard.version_number}` : "未绑定"}</dd></div><div><dt>评测 Prompt</dt><dd>{detail.locked_rule.prompt.name} · {detail.locked_rule.prompt.version}</dd></div><div><dt>模型</dt><dd>{detail.locked_rule.model.provider} · {detail.locked_rule.model.model}</dd></div></dl></section>
    <section className="calibration-section"><SectionTitle number="05" title={props.isPending ? "人工复核" : "人工复核结论"} description={props.isPending ? "请先填写审核人，再确认或修正模型判定" : "已复核案例只读保存，原始模型结果保持不变"} />
      {props.isPending ? <div className="calibration-actions"><label><span>审核人</span><input aria-label="审核人" maxLength={128} value={props.actor} placeholder="请输入审核人姓名" onChange={(event) => props.onActorChange(event.target.value)} /><small>{props.actor.length} / 128</small></label>{props.showAgreeConfirmation ? <div className="calibration-confirm" role="alertdialog" aria-modal="true" aria-labelledby="calibration-agree-title" aria-describedby="calibration-agree-description"><strong id="calibration-agree-title">确认认同模型判定？</strong><p id="calibration-agree-description">提交后该案例将锁定为只读，无法在此页面修改。</p><div><button className="secondary-button" onClick={() => props.onCancelAgree?.()}>返回检查</button><button className="primary-button" ref={confirmButtonRef} disabled={!props.actor.trim() || Boolean(props.busy)} onClick={props.onAgree}>{props.busy === "agree" ? "正在提交…" : "确认提交"}</button></div></div> : <div className="calibration-action-buttons"><button className="primary-button" disabled={!props.actor.trim() || Boolean(props.busy)} onClick={() => props.onRequestAgree?.()}>认同模型判定</button><button className="secondary-button" disabled={Boolean(props.busy)} onClick={() => props.onShowDisagreeFormChange(!props.showDisagreeForm)}>不认同</button></div>}
        {props.showDisagreeForm && <div className="calibration-disagree"><label><span>正确结论</span><select aria-label="正确结论" value={props.correctedPassed === null ? "" : String(props.correctedPassed)} onChange={(event) => props.onCorrectedPassedChange(event.target.value === "" ? null : event.target.value === "true")}><option value="">请选择正确结论</option><option value="true">通过</option><option value="false">不通过</option></select></label><label><span>主要分歧维度</span><select aria-label="主要分歧维度" value={props.disagreementDimension} onChange={(event) => props.onDisagreementDimensionChange(event.target.value as CalibrationDimension | "")}><option value="">请选择分歧维度</option>{DIMENSIONS.map((dimension) => <option value={dimension} key={dimension}>{calibrationDimensionLabel(dimension)}</option>)}</select></label><label className="wide"><span>人工依据</span><textarea value={props.reviewBasis} maxLength={1000} placeholder="说明违反或满足了哪条业务规则" onChange={(event) => props.onReviewBasisChange(event.target.value)} /></label><button className="danger-button" disabled={!props.canDisagree || Boolean(props.busy)} onClick={props.onDisagree}>{props.busy === "disagree" ? "正在提交…" : "提交修正结论"}</button></div>}
      </div> : <div className="calibration-readonly"><div><span>审核人</span><strong>{detail.reviewed_by || "未记录"}</strong></div><div><span>人工结论</span><strong>{detail.agreed ? "认同模型判定" : `人工判定${detail.corrected_passed ? "通过" : "不通过"}`}</strong></div>{!detail.agreed && <><div><span>分歧维度</span><strong>{calibrationDimensionLabel(detail.disagreement_dimension)}</strong></div><div><span>人工依据</span><strong>{detail.review_basis || "未记录"}</strong></div></>}{detail.include_in_regression && <p>已加入回归案例</p>}</div>}
    </section>
  </article>;
}

function SectionTitle({ number, title, description }: { number: string; title: string; description: string }) { return <div className="calibration-section-title"><span>{number} / REVIEW</span><h3>{title}</h3><small>{description}</small></div>; }

export function CalibrationWorkspacePage() {
  const [status, setStatus] = useState<CalibrationFilter>("pending");
  const [prepared, setPrepared] = useState(false);
  const [workspace, setWorkspace] = useState<CalibrationWorkspace | null>(null);
  const [detail, setDetail] = useState<CalibrationReviewDetail | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [actor, setActor] = useState("");
  const [correctedPassed, setCorrectedPassed] = useState<boolean | null>(null);
  const [disagreementDimension, setDisagreementDimension] = useState<CalibrationDimension | "">("");
  const [reviewBasis, setReviewBasis] = useState("");
  const [showDisagreeForm, setShowDisagreeForm] = useState(false);
  const [showAgreeConfirmation, setShowAgreeConfirmation] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [detailLoading, setDetailLoading] = useState(false);
  const statusRef = useRef(status);
  const selectedIdRef = useRef(selectedId);
  const workspaceGenerationRef = useRef(0);
  const detailGenerationRef = useRef(0);

  function applyDetail(value: CalibrationReviewDetail) {
    setDetail(value);
    setCorrectedPassed(null);
    setDisagreementDimension("");
    setReviewBasis("");
    setShowDisagreeForm(false);
    setShowAgreeConfirmation(false);
  }

  function clearDetail() {
    detailGenerationRef.current += 1;
    selectedIdRef.current = "";
    setSelectedId("");
    setDetail(null);
    setDetailLoading(false);
    setShowAgreeConfirmation(false);
    setShowDisagreeForm(false);
  }

  async function loadDetail(reviewId: string) {
    const generation = ++detailGenerationRef.current;
    selectedIdRef.current = reviewId;
    setSelectedId(reviewId);
    setDetail(null);
    setDetailLoading(true);
    setShowAgreeConfirmation(false);
    setShowDisagreeForm(false);
    setError("");
    try {
      const response = await getCalibrationReview(reviewId);
      if (generation !== detailGenerationRef.current || reviewId !== selectedIdRef.current) return;
      applyDetail(response);
    } catch (reason) {
      if (generation !== detailGenerationRef.current || reviewId !== selectedIdRef.current) return;
      setDetail(null);
      setError(reason instanceof Error ? reason.message : "校准详情加载失败");
    } finally {
      if (generation === detailGenerationRef.current && reviewId === selectedIdRef.current) setDetailLoading(false);
    }
  }

  async function loadWorkspace(requestedStatus: CalibrationFilter, preferredId = "") {
    const generation = ++workspaceGenerationRef.current;
    const response = await getCalibrationWorkspace(requestedStatus);
    if (generation !== workspaceGenerationRef.current || requestedStatus !== statusRef.current) return;
    setWorkspace(response);
    const retainedId = preferredId || selectedIdRef.current;
    const nextId = response.items.find((item) => item.review_id === retainedId)?.review_id ?? response.items[0]?.review_id ?? "";
    if (nextId) await loadDetail(nextId);
    else clearDetail();
  }

  useEffect(() => { void prepareTodayBatch().then(() => setPrepared(true)).catch((reason) => setError(reason instanceof Error ? reason.message : "今日校准批次准备失败")); }, []);
  useEffect(() => { if (prepared) void loadWorkspace(status).catch((reason) => setError(reason instanceof Error ? reason.message : "校准工作台加载失败")); }, [prepared, status]);

  function changeStatus(nextStatus: CalibrationFilter) {
    if (nextStatus === statusRef.current) return;
    statusRef.current = nextStatus;
    clearDetail();
    setStatus(nextStatus);
  }

  function select(item: CalibrationWorkspaceItem) { void loadDetail(item.review_id); }

  async function submit(kind: "agree" | "disagree") {
    if (!detail) return;
    setBusy(kind); setError("");
    try {
      if (kind === "agree") await agreeCalibration(detail.review_id, actor.trim());
      else if (correctedPassed !== null && disagreementDimension) await disagreeCalibration(detail.review_id, { actor: actor.trim(), corrected_passed: correctedPassed, disagreement_dimension: disagreementDimension, review_basis: reviewBasis.trim() });
      await loadWorkspace(statusRef.current, detail.review_id);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "复核提交失败"); }
    finally { setBusy(""); }
  }

  if (!workspace && error) return <div className="placeholder-page"><span className="eyebrow">LOAD FAILED</span><h1>评测校准暂时无法加载</h1><p>{error}</p><a className="text-link" href="/calibration">重新加载</a></div>;
  if (!workspace) return <div className="page-state"><span className="loader" />正在准备今日校准案例…</div>;
  return <CalibrationWorkspaceView workspace={workspace} status={status} detail={detail} selectedId={selectedId} busy={busy} error={error} actor={actor} correctedPassed={correctedPassed} disagreementDimension={disagreementDimension} reviewBasis={reviewBasis} showDisagreeForm={showDisagreeForm} showAgreeConfirmation={showAgreeConfirmation} detailLoading={detailLoading} onSelect={select} onStatusChange={changeStatus} onActorChange={setActor} onCorrectedPassedChange={setCorrectedPassed} onDisagreementDimensionChange={setDisagreementDimension} onReviewBasisChange={setReviewBasis} onShowDisagreeFormChange={setShowDisagreeForm} onRequestAgree={() => setShowAgreeConfirmation(true)} onCancelAgree={() => setShowAgreeConfirmation(false)} onAgree={() => void submit("agree")} onDisagree={() => void submit("disagree")} />;
}
