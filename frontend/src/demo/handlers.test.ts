import { afterAll, afterEach, beforeAll, expect, test } from "vitest";
import { setupServer } from "msw/node";

import { createDemoHandlers, resetDemoState } from "./handlers";

const server = setupServer(...createDemoHandlers());

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => resetDemoState());
afterAll(() => server.close());

test("演示模式提供工作台和已配置的模拟模型", async () => {
  const workbench = await fetch("http://localhost/api/workbench").then((response) => response.json());
  const provider = await fetch("http://localhost/api/evaluation/provider-status").then((response) => response.json());
  expect(workbench.priority_items.length).toBeGreaterThan(0);
  expect(provider.configured).toBe(true);
  expect(provider.model).toContain("演示");
  expect(workbench.counts.pending_attributions).toBe(1);
  expect(workbench.priority_items.map((item: { next_action: { path: string } }) => item.next_action.path)).toEqual([
    "/alerts/logistics", "/qa/qa-logistics", "/runs/new",
  ]);
  expect(workbench.recent_activity.every((item: { action: string }) => item.action.includes("演示"))).toBe(true);
});

test("确认知识缺失归因后生成 QA 任务", async () => {
  const issue = await fetch("http://localhost/api/issues?status=pending").then((response) => response.json());
  const id = issue.items[0].id;
  await fetch(`http://localhost/api/badcases/${id}/confirm-attribution`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ actor: "林乔", root_cause: "missing_knowledge", evidence: ["样本显示缺少知识"], confirm_cluster: true }),
  });
  const detail = await fetch(`http://localhost/api/issues/${id}`).then((response) => response.json());
  const qa = await fetch("http://localhost/api/qa-workspace?status=pending").then((response) => response.json());
  expect(detail.confirmation.root_cause).toBe("missing_knowledge");
  expect(qa.items.some((item: { cluster_id: string }) => item.cluster_id === id)).toBe(true);
});

test("审核 QA 后可登记发布并完成模拟复测", async () => {
  const approved = await fetch("http://localhost/api/qa-drafts/draft-logistics/approve", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ actor: "林乔", edits: { business_evidence: [{ source_ref: "示例制度", excerpt: "异常时应说明下一步。" }] } }),
  });
  expect(approved.ok).toBe(true);
  const before = await fetch("http://localhost/api/retest-workspace").then((response) => response.json());
  expect(before.pending_publish).toHaveLength(1);
  const published = await fetch("http://localhost/api/qa-versions/qa-logistics-v1/publish", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ actor: "林乔", release_note: "演示发布" }),
  });
  expect(published.ok).toBe(true);
  const executed = await fetch("http://localhost/api/retests/retest-logistics/execute", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ actor: "林乔" }),
  }).then((response) => response.json());
  expect(executed.replay_pass_rate).toBeGreaterThan(0.8);
  const after = await fetch("http://localhost/api/retest-workspace").then((response) => response.json());
  expect(after.items[0].workspace_state).toBe("recovered");
  const workbench = await fetch("http://localhost/api/workbench").then((response) => response.json());
  expect(workbench.counts.pending_qa).toBe(0);
  expect(workbench.counts.pending_retests).toBe(0);
});

test("模拟评测运行提供分数和逐条理由", async () => {
  const started = await fetch("http://localhost/api/operations/evaluations", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sample_size: 2 }),
  }).then((response) => response.json());
  const run = await fetch(`http://localhost/api/operations/evaluations/${started.run_id}`).then((response) => response.json());
  const results = await fetch(`http://localhost/api/operations/evaluations/${started.run_id}/results?limit=50`).then((response) => response.json());
  expect(run.stage).toBe("completed");
  expect(results.items).toHaveLength(2);
  expect(results.items[0].reason).toBeTruthy();
});

test("规则、Prompt、数据批次与校准页面均可独立加载", async () => {
  const paths = ["/api/quality-standards", "/api/evaluation-prompts", "/api/imports?status=confirmed", "/api/calibration/workspace?status=pending"];
  const values = await Promise.all(paths.map((path) => fetch(`http://localhost${path}`).then((response) => response.json())));
  expect(values[0][0].published_version_id).toBeTruthy();
  expect(values[1][0].published_at).toBeTruthy();
  expect(values[2][0].available_count).toBe(2);
  expect(values[3].items).toHaveLength(1);
});

test("审核后的 QA 可以下载模拟 JSON 和 CSV", async () => {
  await fetch("http://localhost/api/qa-drafts/draft-logistics/approve", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ actor: "林乔", edits: { business_evidence: [{ source_ref: "示例制度", excerpt: "异常时应说明下一步。" }] } }),
  });
  for (const format of ["json", "csv"] as const) {
    const response = await fetch("http://localhost/api/qa-exports/download", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ actor: "林乔", draft_ids: ["draft-logistics"], format }),
    });
    expect(response.ok).toBe(true);
    expect(await response.text()).toContain("物流");
  }
});

test("未覆盖的 API 不会透传到真实网络", async () => {
  const response = await fetch("http://localhost/api/not-in-demo");
  expect(response.status).toBe(501);
  expect(await response.json()).toEqual({ detail: "此操作未纳入作品演示模式，不会调用真实服务。" });
});
