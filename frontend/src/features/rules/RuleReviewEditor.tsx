import type { Dimension, StandardRule, StandardRules } from "../../app/qualityStandardApi";

const dimensions: Array<[Dimension, string]> = [
  ["correctness", "准确性"], ["completeness", "完整性"], ["relevance", "相关性"],
  ["service_experience", "服务体验"], ["compliance", "合规性"],
];

export function RuleReviewEditor({ value, onChange }: { value: StandardRules; onChange: (value: StandardRules) => void }) {
  const rules = [...value.common_rules, ...value.scenarios.flatMap((scenario) => scenario.rules)];
  const setRule = (id: string, patch: Partial<StandardRule>) => onChange({
    ...value,
    common_rules: value.common_rules.map((rule) => rule.id === id ? { ...rule, ...patch } : rule),
    scenarios: value.scenarios.map((scenario) => ({ ...scenario, rules: scenario.rules.map((rule) => rule.id === id ? { ...rule, ...patch } : rule) })),
  });

  return <div className="rules-editor">
    <div className="rules-basics">
      <label className="field"><span>通过阈值（0-100）</span><input type="number" min="0" max="100" value={value.threshold} onChange={(event) => onChange({ ...value, threshold: Number(event.target.value) })} /></label>
      {dimensions.map(([key, label]) => <label className="field" key={key}><span>{label}权重（%）</span><input type="number" min="0" max="100" value={Math.round(value.weights[key] * 100)} onChange={(event) => onChange({ ...value, weights: { ...value.weights, [key]: Number(event.target.value) / 100 } })} /></label>)}
    </div>
    <div className="rules-total">当前权重合计 <strong>{Math.round(Object.values(value.weights).reduce((sum, item) => sum + item, 0) * 100)}%</strong>，发布时必须为 100%</div>
    <div className="review-actions"><button type="button" className="secondary-button" onClick={() => onChange({ ...value, common_rules: value.common_rules.map((rule) => ({ ...rule, confirmed: true })), scenarios: value.scenarios.map((scenario) => ({ ...scenario, rules: scenario.rules.map((rule) => ({ ...rule, confirmed: true })) })) })}>确认全部规则</button><span>{rules.filter((rule) => !rule.confirmed).length} 条待确认</span></div>
    <div className="standard-rule-list">{rules.map((rule) => <article className={rule.confirmed ? "confirmed" : "pending"} key={rule.id}>
      <header><input value={rule.title} onChange={(event) => setRule(rule.id, { title: event.target.value })} /><label><input type="checkbox" checked={rule.confirmed} onChange={(event) => setRule(rule.id, { confirmed: event.target.checked })} /> 人工确认</label></header>
      <textarea value={rule.requirement} onChange={(event) => setRule(rule.id, { requirement: event.target.value })} />
      <footer><span>{dimensions.find(([key]) => key === rule.dimension)?.[1]}</span><span>置信度 {Math.round(rule.confidence * 100)}%</span><span>{rule.source_locator}</span></footer>
      <blockquote>{rule.source_quote}</blockquote>
    </article>)}</div>
  </div>;
}
