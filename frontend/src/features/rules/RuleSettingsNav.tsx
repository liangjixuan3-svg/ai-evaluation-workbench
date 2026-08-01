import { NavLink } from "react-router-dom";

export function RuleSettingsNav() {
  return <nav className="rule-settings-nav" aria-label="评测规则类型">
    <NavLink to="/rules" end>公司质量标准</NavLink>
    <NavLink to="/rules/prompts">评测 Prompt</NavLink>
  </nav>;
}
