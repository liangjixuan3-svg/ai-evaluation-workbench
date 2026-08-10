import { useEffect, useState } from "react";

import { executeRetest, getRetestWorkspace, publishQA, refreshRetestSamples, type RetestItem, type RetestWorkspace, type RetestWorkspaceState } from "../../app/retestApi";

const STATE_LABELS: Record<RetestWorkspaceState, string> = { waiting_samples: "等待新样本", ready: "可开始复测", running: "复测中", interrupted: "执行已中断", recovered: "改善有效", not_recovered: "仍需改进", failed: "执行失败" };
const percent = (value: number | null) => value === null ? "待评测" : `${Math.round(value * 100)}%`;

interface Props {
  workspace: RetestWorkspace; busy: string; error: string; actor: string; releaseNotes: Record<string, string>;
  onActorChange: (value: string) => void; onReleaseNoteChange: (id: string, value: string) => void;
  onPublish: (id: string) => void; onRefresh: (id: string) => void; onExecute: (id: string) => void;
}

export function RetestWorkspaceView(props: Props) {
  const { workspace } = props;
  const counts = [
    [workspace.summary.pending_publish_count, "待发布"], [workspace.summary.waiting_samples_count, "等待样本"],
    [workspace.summary.ready_count, "可复测"], [workspace.summary.recovered_count, "改善有效"],
    [workspace.summary.not_recovered_count, "仍需改进"],
  ] as const;
  return <section className="operation-page retest-page">
    <header className="operation-hero"><div><span className="eyebrow">RELEASE &amp; RETEST</span><h1>让每次改进<br />都能被验证</h1></div><p>登记知识库发布后，同时检查历史失败对话与发布后新对话。两组都达到阈值，问题才真正关闭。</p></header>
    <section className="retest-summary">{counts.map(([count, label]) => <div key={label}><strong>{count}</strong><span>{label}</span></div>)}</section>
    {props.error && <div className="operation-error">{props.error}</div>}
    <section className="retest-section">
      <header><div><span className="eyebrow">01 / RELEASE</span><h2>待发布 QA</h2></div><label className="retest-actor"><span>发布操作人</span><input value={props.actor} onChange={(event) => props.onActorChange(event.target.value)} /></label></header>
      {workspace.pending_publish.length === 0 ? <Empty text="暂无待发布 QA，审核通过的新版本会出现在这里。" /> : <div className="release-list">{workspace.pending_publish.map((item) => <article key={item.qa_version_id}>
        <Title priority={item.priority} meta={`QA V${item.version_number} · 影响 ${item.impact_count} 条`} scenario={item.scenario} />
        <dl><div><dt>用户问题</dt><dd>{item.question}</dd></div><div><dt>审核答案</dt><dd>{item.answer}</dd></div></dl>
        <footer><input aria-label={`${item.scenario}发布备注`} placeholder="发布备注，例如：已同步至退款知识库" value={props.releaseNotes[item.qa_version_id] || ""} onChange={(event) => props.onReleaseNoteChange(item.qa_version_id, event.target.value)} /><button className="primary-button" disabled={!props.actor.trim() || Boolean(props.busy)} onClick={() => props.onPublish(item.qa_version_id)}>{props.busy === `publish:${item.qa_version_id}` ? "正在登记…" : "登记发布 →"}</button></footer>
      </article>)}</div>}
    </section>
    <section className="retest-section">
      <header><div><span className="eyebrow">02 / VERIFY</span><h2>复测任务</h2></div><p>样本不足时先刷新；满足两组最低数量后才能调用模型。</p></header>
      {workspace.items.length === 0 ? <Empty text="发布 QA 后，系统会自动创建复测任务。" /> : <div className="retest-list">{workspace.items.map((item) => <RetestCard key={item.id} item={item} busy={props.busy} onRefresh={props.onRefresh} onExecute={props.onExecute} />)}</div>}
    </section>
  </section>;
}

function Title({ priority, meta, scenario }: { priority: string; meta: string; scenario: string }) { return <div className="retest-card-title"><span className={`retest-priority ${priority.toLowerCase()}`}>{priority}</span><div><small>{meta}</small><h3>{scenario}</h3></div></div>; }
function Empty({ text }: { text: string }) { return <div className="retest-empty">{text}</div>; }
function Cohort({ title, description, available, required }: { title: string; description: string; available: number; required: number }) { const ready = available >= required; return <div className={ready ? "ready" : "waiting"}><header><strong>{title}</strong><b>{ready ? "已满足" : "待补充"}</b></header><p>{description}</p><span><strong>{available}</strong> / {required} 条</span></div>; }
function Rate({ label, value }: { label: string; value: number | null }) { return <div><span>{label}</span><strong>{percent(value)}</strong></div>; }

function RetestCard({ item, busy, onRefresh, onExecute }: { item: RetestItem; busy: string; onRefresh: (id: string) => void; onExecute: (id: string) => void }) {
  const terminal = item.workspace_state === "recovered" || item.workspace_state === "not_recovered";
  const passRate = item.locked_rule.pass_rate_threshold === null ? "锁定阈值" : `${Math.round(item.locked_rule.pass_rate_threshold * 100)}%`;
  return <article className={`retest-card state-${item.workspace_state}`}>
    <header><Title priority={item.priority} meta={`QA V${item.qa_version_number} · 影响 ${item.impact_count} 条`} scenario={item.scenario} /><b>{STATE_LABELS[item.workspace_state]}</b></header>
    <div className="retest-rule-strip"><span>锁定规则 {item.locked_rule.rule_version}</span><span>Prompt {item.locked_rule.prompt_version}</span><span>{item.locked_rule.model}</span><span>单条得分 {item.locked_rule.threshold ?? "-"} 分</span><span>组通过率 {item.locked_rule.pass_rate_threshold === null ? "-" : `${Math.round(item.locked_rule.pass_rate_threshold * 100)}%`}</span></div>
    <div className="cohort-grid"><Cohort title="历史回放" description="重新检查关联的历史失败问题" {...item.replay_samples} /><Cohort title="发布后新对话" description="验证真实线上回答是否改善" {...item.new_samples} /></div>
    <section className="retest-method-summary">
      <header><span className="eyebrow">METHOD</span><h4>怎么复测</h4></header>
      <dl>
        <div><dt>样本</dt><dd>历史失败对话回放 + 发布后同场景新对话</dd></div>
        <div><dt>裁判</dt><dd>{item.locked_rule.rule_version} 公司规则 · Prompt {item.locked_rule.prompt_version} · {item.locked_rule.model}</dd></div>
        <div><dt>结论</dt><dd>两组都达到 {passRate} 才算改善有效</dd></div>
      </dl>
      <a href={`/retests/${item.id}`}>查看复测明细 →</a>
    </section>
    <div className="rate-compare"><Rate label="发布前" value={item.before_pass_rate} /><Rate label="历史回放" value={item.replay_pass_rate} /><Rate label="新对话" value={item.new_sample_pass_rate} /></div>
    <footer><div><span>{item.published_by} 发布</span><small>{item.release_note || "未填写发布备注"}</small></div>{!terminal && <div className="retest-actions"><button className="secondary-button" disabled={Boolean(busy) || item.workspace_state === "running" || item.workspace_state === "interrupted"} onClick={() => onRefresh(item.id)}>{busy === `refresh:${item.id}` ? "刷新中…" : "刷新样本"}</button><button className="primary-button" disabled={(item.workspace_state !== "ready" && item.workspace_state !== "interrupted") || Boolean(busy)} onClick={() => onExecute(item.id)}>{busy === `execute:${item.id}` ? "评测中…" : item.workspace_state === "interrupted" ? "恢复并继续 →" : "开始复测 →"}</button></div>}</footer>
  </article>;
}

export function RetestWorkspacePage() {
  const [workspace, setWorkspace] = useState<RetestWorkspace | null>(null); const [actor, setActor] = useState("林乔");
  const [releaseNotes, setReleaseNotes] = useState<Record<string, string>>({}); const [busy, setBusy] = useState(""); const [error, setError] = useState("");
  const refresh = async () => setWorkspace(await getRetestWorkspace());
  useEffect(() => { void refresh().catch((reason) => setError(reason instanceof Error ? reason.message : "发布与复测任务加载失败")); }, []);
  async function action(key: string, callback: () => Promise<unknown>) { setBusy(key); setError(""); try { await callback(); await refresh(); } catch (reason) { setError(reason instanceof Error ? reason.message : "操作失败"); } finally { setBusy(""); } }
  if (!workspace && error) return <div className="placeholder-page"><span className="eyebrow">LOAD FAILED</span><h1>发布与复测暂时无法加载</h1><p>{error}</p><a className="text-link" href="/retests">重新加载</a></div>;
  if (!workspace) return <div className="page-state"><span className="loader" />正在整理发布与复测任务…</div>;
  return <RetestWorkspaceView workspace={workspace} busy={busy} error={error} actor={actor} releaseNotes={releaseNotes} onActorChange={setActor} onReleaseNoteChange={(id, value) => setReleaseNotes((current) => ({ ...current, [id]: value }))} onPublish={(id) => void action(`publish:${id}`, () => publishQA(id, { actor, release_note: releaseNotes[id] || "" }))} onRefresh={(id) => void action(`refresh:${id}`, () => refreshRetestSamples(id))} onExecute={(id) => void action(`execute:${id}`, () => executeRetest(id, actor))} />;
}
