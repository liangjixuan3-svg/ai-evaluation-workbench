import { NavLink, Outlet } from "react-router-dom";

const navigation = [
  ["/", "今日工作台", "01"],
  ["/alerts", "问题与归因", "02"],
  ["/qa", "QA 审核", "03"],
  ["/retests", "发布与复测", "04"],
  ["/runs", "评测运行", "05"],
  ["/rules", "评测规则", "06"],
] as const;

export function AppShell() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="/" aria-label="迭代台首页">
          <span className="brand-mark">迭</span>
          <span><strong>迭代台</strong><small>AI QUALITY LOOP</small></span>
        </a>
        <nav aria-label="主导航">
          {navigation.map(([path, label, index]) => (
            <NavLink key={path} to={path} end={path === "/"}>
              <span>{index}</span>{label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <span className="pulse" />
          <div><strong>自动评测运行中</strong><small>下一批次 14:00</small></div>
        </div>
      </aside>
      <main className="main-stage">
        <header className="topbar">
          <div className="mobile-brand"><span className="brand-mark">迭</span> 迭代台</div>
          <div className="system-state"><span className="pulse" /> 今日已评测 2,238 条</div>
          <button className="operator" type="button"><span>林</span> 林乔</button>
        </header>
        <Outlet />
      </main>
    </div>
  );
}
