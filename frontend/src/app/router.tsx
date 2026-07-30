import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "../components/AppShell";
import { NewEvaluationPage } from "../features/evaluations/NewEvaluationPage";
import { RunDetailPage } from "../features/evaluations/RunDetailPage";
import { ImportPage } from "../features/imports/ImportPage";
import { WorkbenchPage } from "../features/workbench/WorkbenchPage";

function ComingSoon({ title }: { title: string }) {
  return (
    <section className="placeholder-page">
      <span className="eyebrow">MVP NEXT</span>
      <h1>{title}</h1>
      <p>首版先从工作台进入具体任务。这里将在下一迭代补充批量管理能力。</p>
      <a className="text-link" href="/">返回今日工作台</a>
    </section>
  );
}

export function AppRouter() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<WorkbenchPage />} />
        <Route path="alerts/*" element={<ComingSoon title="问题与归因" />} />
        <Route path="qa/*" element={<ComingSoon title="QA 审核" />} />
        <Route path="retests/*" element={<ComingSoon title="发布与复测" />} />
        <Route path="runs/import" element={<ImportPage />} />
        <Route path="runs/new" element={<NewEvaluationPage />} />
        <Route path="runs/:runId" element={<RunDetailPage />} />
        <Route path="runs" element={<Navigate to="/runs/new" replace />} />
        <Route path="rules/*" element={<ComingSoon title="评测规则" />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
