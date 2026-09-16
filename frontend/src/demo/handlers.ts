import { http, HttpResponse } from "msw";

import type { IssueDetail, IssueListResponse, RootCause } from "../app/issueApi";
import type { QADetail, QAListResponse } from "../app/qaApi";
import type { EvaluationDetail } from "../app/evaluationApi";
import type { RetestItem, RetestWorkspace } from "../app/retestApi";
import { DEMO_TIME, demoResults, demoWorkbench, initialIssue, initialQA, initialRun, retestTemplate } from "./demoData";
import { createReferenceHandlers, resetReferenceState } from "./referenceHandlers";

type DemoState = { issue: IssueDetail; qa: QADetail; retest: RetestItem | null; run: EvaluationDetail };

function initialState(): DemoState {
  return { issue: structuredClone(initialIssue), qa: structuredClone(initialQA), retest: null, run: structuredClone(initialRun) };
}

let state = initialState();

export function resetDemoState() {
  state = initialState();
  resetReferenceState();
}

function issueList(status: string): IssueListResponse {
  const item = state.issue;
  return {
    summary: {
      pending_count: item.status === "pending" ? 1 : 0,
      confirmed_count: item.status === "confirmed" ? 1 : 0,
      impacted_count: item.impact_count,
      missing_knowledge_count: item.confirmed_root_cause === "missing_knowledge" ? 1 : 0,
    },
    items: status === "all" || item.status === status ? [{ ...item, suggestion: item.suggestion && { root_cause: item.suggestion.root_cause, confidence: item.suggestion.confidence } }] : [],
  };
}

function qaList(status: string): QAListResponse {
  const item = state.qa;
  return {
    summary: {
      awaiting_generation_count: item.state === "awaiting_generation" ? 1 : 0,
      pending_review_count: item.state === "pending_review" ? 1 : 0,
      approved_count: item.state === "approved" ? 1 : 0,
      rejected_count: item.state === "rejected" ? 1 : 0,
    },
    items: status === "all" || (status === "pending" && ["awaiting_generation", "pending_review"].includes(item.state)) || item.state === status ? [item] : [],
  };
}

function workbenchSummary() {
  const pendingQA = ["awaiting_generation", "pending_review"].includes(state.qa.state);
  const pendingRetest = state.qa.state === "approved" && state.retest?.workspace_state !== "recovered";
  return {
    ...demoWorkbench,
    counts: {
      new_alerts: state.issue.status === "pending" ? 1 : 0,
      pending_attributions: state.issue.status === "pending" ? 1 : 0,
      pending_qa: pendingQA ? 1 : 0,
      pending_retests: pendingRetest ? 1 : 0,
    },
    priority_items: demoWorkbench.priority_items.filter((_, index) =>
      index === 0 ? state.issue.status === "pending" : index === 1 ? pendingQA : true),
  };
}

function retestWorkspace(): RetestWorkspace {
  const draft = state.qa.draft;
  const pending = state.qa.state === "approved" && !state.retest && draft;
  return {
    summary: {
      pending_publish_count: pending ? 1 : 0, waiting_samples_count: 0,
      ready_count: state.retest?.workspace_state === "ready" ? 1 : 0, running_count: 0,
      recovered_count: state.retest?.workspace_state === "recovered" ? 1 : 0,
      not_recovered_count: state.retest?.workspace_state === "not_recovered" ? 1 : 0,
    },
    pending_publish: pending ? [{
      qa_version_id: "qa-logistics-v1", version_number: draft.version_number, scenario: state.qa.scenario || "物流异常催单",
      question: draft.content.question, answer: draft.content.answer, approved_by: draft.approved_by,
      approved_at: draft.approved_at, priority: state.qa.priority, impact_count: state.qa.impact_count,
    }] : [],
    items: state.retest ? [state.retest] : [],
  };
}

function csvField(value: string) {
  return `"${value.replaceAll('"', '""')}"`;
}

const respond = <T,>(value: T) => HttpResponse.json(structuredClone(value) as Parameters<typeof HttpResponse.json>[0]);

export function createDemoHandlers() {
  return [
    ...createReferenceHandlers(),
    http.get("*/api/workbench", () => respond(workbenchSummary())),
    http.get("*/api/evaluation/provider-status", () => respond({ configured: true, base_url: null, model: "演示 · 预生成结果" })),
    http.get("*/api/issues", ({ request }) => respond(issueList(new URL(request.url).searchParams.get("status") || "pending"))),
    http.get("*/api/issues/:id", ({ params }) => params.id === state.issue.id ? respond(state.issue) : HttpResponse.json({ detail: "演示案例不存在" }, { status: 404 })),
    http.post("*/api/badcases/:id/attribution", ({ params }) => params.id === state.issue.id ? respond(state.issue.suggestion) : HttpResponse.json({ detail: "演示案例不存在" }, { status: 404 })),
    http.post("*/api/badcases/:id/confirm-attribution", async ({ request, params }) => {
      if (params.id !== state.issue.id) return HttpResponse.json({ detail: "演示案例不存在" }, { status: 404 });
      const input = await request.json() as { actor: string; root_cause: RootCause };
      state.issue.status = "confirmed";
      state.issue.confirmed_root_cause = input.root_cause;
      state.issue.confirmation = { root_cause: input.root_cause, confirmed_by: input.actor, confirmed_at: DEMO_TIME };
      state.issue.task = { id: state.qa.task_id, type: input.root_cause === "missing_knowledge" ? "qa_review" : "evaluation_calibration", status: "open", title: state.issue.problem_summary };
      return respond({ id: state.issue.task.id, type: state.issue.task.type });
    }),
    http.get("*/api/qa-workspace", ({ request }) => respond(qaList(new URL(request.url).searchParams.get("status") || "pending"))),
    http.get("*/api/qa-workspace/:id", ({ params }) => params.id === state.qa.task_id ? respond(state.qa) : HttpResponse.json({ detail: "演示 QA 不存在" }, { status: 404 })),
    http.post("*/api/qa-workspace/:id/generate", ({ params }) => params.id === state.qa.task_id ? respond({ id: state.qa.draft?.id, status: state.qa.state }) : HttpResponse.json({ detail: "演示 QA 不存在" }, { status: 404 })),
    http.post("*/api/qa-drafts/:id/approve", async ({ request, params }) => {
      const draft = state.qa.draft;
      if (!draft || params.id !== draft.id) return HttpResponse.json({ detail: "演示草稿不存在" }, { status: 404 });
      const input = await request.json() as { actor: string; edits: Partial<NonNullable<QADetail["draft"]>["content"]> & { business_evidence: Array<{ source_ref: string; excerpt: string }> } };
      state.qa.state = "approved";
      draft.status = "approved";
      draft.content = { ...draft.content, ...input.edits };
      draft.approved_by = input.actor;
      draft.approved_at = DEMO_TIME;
      draft.evidence = input.edits.business_evidence.map((item) => ({ source_type: "business_reference", ...item }));
      return respond({ id: draft.id, version_number: draft.version_number });
    }),
    http.post("*/api/qa-drafts/:id/reject", async ({ request, params }) => {
      const draft = state.qa.draft;
      if (!draft || params.id !== draft.id) return HttpResponse.json({ detail: "演示草稿不存在" }, { status: 404 });
      const input = await request.json() as { reason: string };
      state.qa.state = "rejected"; draft.status = "rejected"; draft.rejection_reason = input.reason;
      return respond({ id: draft.id, status: "rejected" });
    }),
    http.post("*/api/qa-exports/download", async ({ request }) => {
      const input = await request.json() as { draft_ids: string[]; format: "json" | "csv" };
      const draft = state.qa.draft;
      if (!draft || state.qa.state !== "approved" || !input.draft_ids.includes(draft.id)) {
        return HttpResponse.json({ detail: "请先审核演示 QA 草稿。" }, { status: 422 });
      }
      if (input.format === "json") {
        return new HttpResponse(JSON.stringify([{ scenario: state.qa.scenario, ...draft.content }], null, 2), {
          headers: { "Content-Type": "application/json; charset=utf-8", "Content-Disposition": 'attachment; filename="qa-demo.json"' },
        });
      }
      if (input.format === "csv") {
        const row = [state.qa.scenario || "", draft.content.question, draft.content.answer].map(csvField).join(",");
        return new HttpResponse(`scenario,question,answer\n${row}\n`, {
          headers: { "Content-Type": "text/csv; charset=utf-8", "Content-Disposition": 'attachment; filename="qa-demo.csv"' },
        });
      }
      return HttpResponse.json({ detail: "不支持此导出格式。" }, { status: 422 });
    }),
    http.get("*/api/retest-workspace", () => respond(retestWorkspace())),
    http.get("*/api/retest-workspace/:id", ({ params }) => {
      const item = state.retest;
      if (!item || params.id !== item.id) return HttpResponse.json({ detail: "演示复测不存在" }, { status: 404 });
      const completed = item.workspace_state === "recovered";
      return respond({
        ...item,
        method: {
          sample_selection: { replay: "原问题簇历史失败对话回放", new: "发布后同场景新对话" },
          quality_standard: { name: "客服质量标准示例", version: "V1", rules: { threshold: 75, weights: { correctness: 0.3, completeness: 0.25, relevance: 0.2, service_experience: 0.1, compliance: 0.15 } } },
          prompt: { name: "客服质量评测", version: "V1", content: "基于公司标准逐维度评分，引用对话证据，说明失败原因；不得编造事实。" },
          model: "演示 · 预生成结果", template: null, single_score_threshold: 75, cohort_pass_rate_threshold: 0.8,
          retest_rule: { version: "V1", config: { replay_required: 2, new_required: 2 } },
        },
        explanation: {
          verdict: completed ? "改善有效" : "等待复测", formula: "历史回放与新对话两组均达到 80% 方可关闭",
          replay: { passed: completed ? 2 : 0, completed: completed ? 2 : 0, total: 2, pass_rate: item.replay_pass_rate },
          new: { passed: completed ? 2 : 0, completed: completed ? 2 : 0, total: 2, pass_rate: item.new_sample_pass_rate },
        },
        samples: ["replay", "new"].flatMap((cohort) => [1, 2].map((index) => ({
          id: `${cohort}-${index}`, cohort, status: completed ? "completed" : "pending", external_id: `DEMO-${cohort.toUpperCase()}-${index}`,
          scenario: "物流异常催单", occurred_at: DEMO_TIME,
          conversation: { messages: [{ role: "user", content: "物流超过预计时间没更新，怎么办？" }, { role: "assistant", content: completed ? "请提供订单尾号，我来核查物流；确认异常后可转人工催办并告知反馈时效。" : "请耐心等待。" }] },
          evaluation: completed ? { total_score: 88, dimension_scores: { correctness: 90, completeness: 85, relevance: 90, service_experience: 85, compliance: 95 }, passed: true, reason: "回答包含核查动作、催办条件与后续反馈。", evidence: ["请提供订单尾号，我来核查物流"], confidence: "high", severe_factual_error: false, severe_compliance_error: false } : null,
        }))),
      });
    }),
    http.post("*/api/qa-versions/:id/publish", async ({ request, params }) => {
      if (params.id !== "qa-logistics-v1" || state.qa.state !== "approved") return HttpResponse.json({ detail: "演示 QA 尚未审核" }, { status: 422 });
      const input = await request.json() as { actor: string; release_note: string };
      state.retest = structuredClone(retestTemplate);
      state.retest.published_by = input.actor;
      state.retest.release_note = input.release_note;
      state.retest.answer = state.qa.draft?.content.answer || state.retest.answer;
      return respond({ retest_run_id: state.retest.id, workspace_state: "ready" });
    }),
    http.post("*/api/retests/:id/refresh-samples", ({ params }) => params.id === state.retest?.id ? respond(state.retest) : HttpResponse.json({ detail: "演示复测不存在" }, { status: 404 })),
    http.post("*/api/retests/:id/execute", ({ params }) => {
      const item = state.retest;
      if (!item || params.id !== item.id) return HttpResponse.json({ detail: "演示复测不存在" }, { status: 404 });
      item.workspace_state = "recovered"; item.status = "completed"; item.replay_pass_rate = 1; item.new_sample_pass_rate = 1;
      return respond({ id: item.id, status: item.status, replay_pass_rate: 1, new_sample_pass_rate: 1 });
    }),
    http.post("*/api/operations/evaluations", async ({ request }) => {
      const input = await request.json() as { sample_size: number };
      state.run = { ...structuredClone(initialRun), run_id: "demo-run-2", sample_count: Math.min(2, input.sample_size || 2), completed_count: Math.min(2, input.sample_size || 2) };
      return respond({ run_id: state.run.run_id, status: "queued" });
    }),
    http.get("*/api/operations/evaluations/:id/results", ({ params }) => params.id === state.run.run_id || params.id === initialRun.run_id ? respond({ total: 2, items: demoResults }) : HttpResponse.json({ detail: "演示运行不存在" }, { status: 404 })),
    http.get("*/api/operations/evaluations/:id", ({ params }) => params.id === state.run.run_id ? respond(state.run) : params.id === initialRun.run_id ? respond(initialRun) : HttpResponse.json({ detail: "演示运行不存在" }, { status: 404 })),
    http.all("*/api/*", () => HttpResponse.json({ detail: "此操作未纳入作品演示模式，不会调用真实服务。" }, { status: 501 })),
  ];
}
