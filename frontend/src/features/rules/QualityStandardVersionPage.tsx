import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { getQualityStandardVersion, type StandardRule } from "../../app/qualityStandardApi";

const dimensionLabels: Record<string, string> = {
  correctness: "准确性",
  completeness: "完整性",
  relevance: "相关性",
  service_experience: "服务体验",
  compliance: "合规性",
};
const anchorLabels: Record<string, string> = {
  excellent: "优秀",
  good: "良好",
  acceptable: "可接受",
  poor: "较差",
  unacceptable: "不可接受",
};

function effectLabel(rule: StandardRule) {
  if (rule.effect.kind === "veto") return "一票否决";
  if (rule.effect.kind === "dimension_cap") return `维度上限 ${rule.effect.dimension_cap}`;
  return "普通规则";
}

function RuleList({ rules }: { rules: StandardRule[] }) {
  if (!rules.length) return <p className="empty-rule-group">该分组没有配置规则</p>;
  return <div className="readonly-rule-list">{rules.map((rule) => <article key={rule.id}>
    <header><strong>{rule.title}</strong><span>{dimensionLabels[rule.dimension]} · {effectLabel(rule)}</span></header>
    <p>{rule.requirement}</p>
    <blockquote><b>制度原文</b>{rule.source_quote}<small>{rule.source_locator}</small></blockquote>
  </article>)}</div>;
}

export function QualityStandardVersionPage() {
  const { versionId = "" } = useParams();
  const query = useQuery({
    queryKey: ["quality-standard-version", versionId],
    queryFn: () => getQualityStandardVersion(versionId),
    enabled: Boolean(versionId),
    retry: false,
  });
  if (query.isLoading) return <div className="page-state"><span className="loader" />正在读取规则版本</div>;
  if (!query.data) return <div className="placeholder-page"><h1>规则版本不可用</h1><p>{query.error?.message}</p><Link className="text-link" to="/">返回工作台</Link></div>;
  const version = query.data;
  const rules = version.rules;

  return <section className="operation-page rule-version-page">
    <header className="rule-version-hero"><div><span className="eyebrow">READ-ONLY STANDARD</span><h1>{version.standard_name}</h1><p>版本 V{version.version_number} · {version.source_filename} · 发布于 {new Date(version.published_at).toLocaleString("zh-CN")}</p></div><span className="locked-version">只读版本</span></header>
    <div className="rule-version-summary"><div><span>通过阈值</span><strong>{rules.threshold}</strong></div>{Object.entries(rules.weights).map(([dimension, weight]) => <div key={dimension}><span>{dimensionLabels[dimension]}</span><strong>{Math.round(weight * 100)}%</strong><i><b style={{ width: `${weight * 100}%` }} /></i></div>)}</div>
    <section className="anchor-sheet"><div className="section-heading compact"><div><span className="eyebrow">SCORE ANCHORS</span><h2>五档评分说明</h2></div></div><div>{rules.anchors.map((anchor) => <article key={anchor.level}><strong>{anchorLabels[anchor.level]}</strong><p>{anchor.description}</p></article>)}</div></section>
    <section className="rule-sheet"><div className="section-heading compact"><div><span className="eyebrow">COMMON RULES</span><h2>通用规则</h2></div><small>{rules.common_rules.length} 条</small></div><RuleList rules={rules.common_rules} /></section>
    {rules.scenarios.map((scenario) => <section className="rule-sheet" key={scenario.name}><div className="section-heading compact"><div><span className="eyebrow">SCENARIO RULES</span><h2>{scenario.name}</h2></div><small>{scenario.rules.length} 条</small></div><RuleList rules={scenario.rules} /></section>)}
    <div className="readonly-footnote">此页面展示评测运行绑定的历史版本快照，不会随最新公司标准变化。</div>
  </section>;
}
