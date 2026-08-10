import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "../components/AppShell";
import { NewEvaluationPage } from "../features/evaluations/NewEvaluationPage";
import { RunDetailPage } from "../features/evaluations/RunDetailPage";
import { ImportPage } from "../features/imports/ImportPage";
import { IssueWorkspacePage } from "../features/issues/IssueWorkspacePage";
import { QAWorkspacePage } from "../features/qa/QAWorkspacePage";
import { RetestWorkspacePage } from "../features/retests/RetestWorkspacePage";
import { RetestDetailPage } from "../features/retests/RetestDetailPage";
import { WorkbenchPage } from "../features/workbench/WorkbenchPage";
import { CalibrationWorkspacePage } from "../features/calibration/CalibrationWorkspacePage";
import { QualityStandardPage } from "../features/rules/QualityStandardPage";
import { QualityStandardVersionPage } from "../features/rules/QualityStandardVersionPage";
import { EvaluationPromptPage } from "../features/rules/EvaluationPromptPage";

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
        <Route path="alerts/*" element={<IssueWorkspacePage />} />
        <Route path="qa/*" element={<QAWorkspacePage />} />
        <Route path="calibration/*" element={<CalibrationWorkspacePage />} />
        <Route path="retests/:runId" element={<RetestDetailPage />} />
        <Route path="retests/*" element={<RetestWorkspacePage />} />
        <Route path="runs/import" element={<ImportPage />} />
        <Route path="runs/new" element={<NewEvaluationPage />} />
        <Route path="runs/:runId" element={<RunDetailPage />} />
        <Route path="runs" element={<Navigate to="/runs/new" replace />} />
        <Route path="rules/versions/:versionId" element={<QualityStandardVersionPage />} />
        <Route path="rules/prompts" element={<EvaluationPromptPage />} />
        <Route path="rules/*" element={<QualityStandardPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
