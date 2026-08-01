import { useEffect, useState } from "react";

import { copyEvaluationPrompt, deleteEvaluationPrompt, listEvaluationPrompts, publishEvaluationPrompt, saveEvaluationPrompt, type EvaluationPromptVersion } from "../../app/evaluationPromptApi";
import { RuleSettingsNav } from "./RuleSettingsNav";

export function EvaluationPromptPage() {
  const [items, setItems] = useState<EvaluationPromptVersion[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [content, setContent] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const selected = items.find((item) => item.id === selectedId) || items[0];

  async function refresh(preferredId?: string) {
    const versions = await listEvaluationPrompts();
    setItems(versions);
    const next = versions.find((item) => item.id === (preferredId || selectedId)) || versions[0];
    setSelectedId(next?.id || "");
    setContent(next?.content || "");
  }

  useEffect(() => { void refresh().catch((reason) => setError(reason instanceof Error ? reason.message : "Prompt 列表加载失败")); }, []);

  function choose(item: EvaluationPromptVersion) {
    setSelectedId(item.id); setContent(item.content); setError("");
  }

  async function run(label: string, action: () => Promise<EvaluationPromptVersion>) {
    setBusy(label); setError("");
    try { const result = await action(); await refresh(result.id); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "操作失败"); }
    finally { setBusy(""); }
  }

  async function removeDraft(item: EvaluationPromptVersion) {
    if (!window.confirm(`确定删除 ${item.version.toUpperCase()} 草稿吗？删除后无法恢复。`)) return;
    setBusy("delete"); setError("");
    try { await deleteEvaluationPrompt(item.id); await refresh(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "删除失败"); }
    finally { setBusy(""); }
  }

  return <section className="operation-page prompt-page">
    <header className="operation-hero"><div><span className="eyebrow">EVALUATION PROMPT</span><h1>告诉模型<br />怎样执行评测</h1></div><p>Prompt 决定模型如何判断和解释；公司质量标准决定具体评什么。发布后版本锁定，确保结果可以复现。</p></header>
    <RuleSettingsNav />
    <div className="prompt-layout">
      <aside className="prompt-library"><div className="library-head"><span>版本记录</span><strong>{items.length}</strong></div>{items.map((item) => <button type="button" className={selected?.id === item.id ? "active" : ""} key={item.id} onClick={() => choose(item)}><strong>{item.version.toUpperCase()}</strong><span>{item.published_at ? item.active ? "当前默认" : "历史版本" : "编辑草稿"}</span><small>{item.published_at ? new Date(item.published_at).toLocaleString("zh-CN") : "尚未发布"}</small></button>)}</aside>
      <main className="prompt-workspace">{selected ? <><header><div><span>{selected.published_at ? "已发布版本" : "未发布草稿"}</span><h2>客服质量评测 · {selected.version.toUpperCase()}</h2></div><b className={selected.active ? "active" : ""}>{selected.active ? "当前默认" : selected.published_at ? "已锁定" : "草稿"}</b></header><div className="fixed-contract-note"><strong>系统固定输出协议</strong><p>五维分数、理由、原文证据、置信度和严重错误标记由系统强制校验，不会被下面的内容覆盖。</p></div><label className="prompt-editor"><span>可版本化评测指令</span><textarea value={content} readOnly={Boolean(selected.published_at)} maxLength={20000} onChange={(event) => setContent(event.target.value)} /></label><footer>{selected.published_at ? <button className="primary-button" disabled={Boolean(busy)} onClick={() => void run("copy", () => copyEvaluationPrompt(selected.id))}>{busy === "copy" ? "正在创建…" : "复制为新版本 →"}</button> : <><button className="danger-button" disabled={Boolean(busy)} onClick={() => void removeDraft(selected)}>{busy === "delete" ? "正在删除…" : "删除草稿"}</button><button className="secondary-button" disabled={Boolean(busy)} onClick={() => void run("save", () => saveEvaluationPrompt(selected.id, content))}>{busy === "save" ? "正在保存…" : "保存草稿"}</button><button className="primary-button" disabled={Boolean(busy) || !content.trim()} onClick={() => void run("publish", async () => { await saveEvaluationPrompt(selected.id, content); return publishEvaluationPrompt(selected.id); })}>{busy === "publish" ? "正在发布…" : "发布并锁定 →"}</button></>}</footer></> : <div className="empty-standard"><strong>正在准备内置 Prompt</strong></div>}</main>
    </div>
    {error && <div className="operation-error" role="alert">{error}</div>}
  </section>;
}
