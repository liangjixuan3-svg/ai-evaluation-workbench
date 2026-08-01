import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { getQualityStandard, listQualityStandards, parseQualityStandard, publishQualityStandard, saveQualityStandard, uploadQualityStandard, type QualityStandard, type QualityStandardSummary, type StandardRules } from "../../app/qualityStandardApi";
import { RuleReviewEditor } from "./RuleReviewEditor";

export function PublishedStandardNote({ versionId, versionNumber }: { versionId: string; versionNumber: number }) {
  return <div className="published-note"><strong>这个版本已经锁定</strong><p>已发布标准不可修改，保证后续每次评测都能追溯到当时使用的规则。</p><Link className="secondary-button published-version-button" to={`/rules/versions/${versionId}`}>查看 V{versionNumber} 完整规则 →</Link></div>;
}

export function QualityStandardPage() {
  const [items, setItems] = useState<QualityStandardSummary[]>([]);
  const [selected, setSelected] = useState<QualityStandard | null>(null);
  const [rules, setRules] = useState<StandardRules | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  async function refresh(preferredId?: string) {
    const list = await listQualityStandards();
    setItems(list);
    const id = preferredId || selected?.id || list[0]?.id;
    if (id) {
      const detail = await getQualityStandard(id);
      setSelected(detail);
      setRules(detail.draft?.rules ?? null);
    }
  }
  useEffect(() => { void refresh().catch((reason) => setError(reason instanceof Error ? reason.message : "标准列表加载失败")); }, []);

  async function run(label: string, action: () => Promise<QualityStandard>) {
    setBusy(label); setError("");
    try { const detail = await action(); setSelected(detail); setRules(detail.draft?.rules ?? null); await refresh(detail.id); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "操作失败"); }
    finally { setBusy(""); }
  }

  const pending = rules ? [...rules.common_rules, ...rules.scenarios.flatMap((item) => item.rules)].filter((rule) => !rule.confirmed).length : 0;
  const weightTotal = rules ? Object.values(rules.weights).reduce((sum, item) => sum + item, 0) : 0;
  const publishedVersion = selected ? [...selected.versions].reverse().find((version) => Boolean(version.published_at)) : undefined;

  return <section className="operation-page standards-page">
    <header className="operation-hero"><div><span className="eyebrow">QUALITY STANDARD</span><h1>把公司制度<br />变成评测尺子</h1></div><p>上传 Word 或文本 PDF，由 AI 提取规则。你确认后发布，未经审核的草稿不会参与线上评测。</p></header>
    <div className="standards-layout">
      <aside className="standards-library"><div className="library-head"><span>标准库</span><strong>{items.length}</strong></div>
        <label className="standard-upload"><input type="file" accept=".docx,.pdf" disabled={Boolean(busy)} onChange={(event) => { const file = event.target.files?.[0]; if (file) void run("upload", () => uploadQualityStandard(file)); }} /><span>{busy === "upload" ? "正在上传…" : "+ 上传公司标准"}</span></label>
        {items.map((item) => <button type="button" className={selected?.id === item.id ? "active" : ""} key={item.id} onClick={() => void getQualityStandard(item.id).then((detail) => { setSelected(detail); setRules(detail.draft?.rules ?? null); })}><strong>{item.name}</strong><small>V{item.latest_version} · {item.status === "published" ? "已发布" : "草稿"}</small></button>)}
        {!items.length && <p>还没有标准，先上传一份公司制度。</p>}
      </aside>
      <main className="standard-workspace">{!selected ? <div className="empty-standard"><strong>从一份真实制度开始</strong><p>支持 .docx 和可复制文字的 .pdf，最大 20 MB。</p></div> : <>
        <div className="standard-title"><div><span>{selected.status === "published" ? "已发布标准" : "审核草稿"}</span><h2>{selected.name}</h2><p>{selected.versions.at(-1)?.source_filename}</p></div><div className={`standard-state ${selected.status}`}>{selected.status === "published" ? "已发布" : selected.parse_jobs.at(-1)?.status === "completed" ? "待审核" : "待解析"}</div></div>
        {selected.draft && selected.parse_jobs.at(-1)?.status !== "completed" && <div className="parse-panel"><span>01</span><div><strong>让 AI 读取制度并生成规则草稿</strong><p>解析通常需要数十秒。AI 只生成草稿，不会自动发布。</p></div><button className="primary-button" disabled={Boolean(busy)} onClick={() => void run("parse", () => parseQualityStandard(selected.id))}>{busy === "parse" ? "正在解析…" : "开始 AI 解析 →"}</button></div>}
        {rules && selected.draft && <><RuleReviewEditor value={rules} onChange={setRules} /><div className="publish-bar"><div><strong>{pending ? `${pending} 条规则待确认` : "规则已全部确认"}</strong><small>权重合计 {Math.round(weightTotal * 100)}%</small></div><button className="secondary-button" disabled={Boolean(busy)} onClick={() => void run("save", () => saveQualityStandard(selected.id, rules))}>保存草稿</button><button className="primary-button" disabled={Boolean(busy) || pending > 0 || Math.abs(weightTotal - 1) > 0.0001} onClick={() => void run("publish", async () => { await saveQualityStandard(selected.id, rules); return publishQualityStandard(selected.id); })}>{busy === "publish" ? "正在发布…" : "发布为公司标准 →"}</button></div></>}
        {selected.status === "published" && publishedVersion && <PublishedStandardNote versionId={publishedVersion.id} versionNumber={publishedVersion.version_number} />}
      </>}</main>
    </div>
    {error && <div className="operation-error" role="alert">{error}</div>}
  </section>;
}
