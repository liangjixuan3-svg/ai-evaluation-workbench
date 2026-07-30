export type WorkbenchCountKey =
  | "new_alerts"
  | "pending_attributions"
  | "pending_qa"
  | "pending_retests";

export interface TaskItem {
  id: string;
  kind: "alert" | "task";
  title: string;
  description: string;
  priority: string;
  status: string;
  impact_count: number;
  created_at: string;
  next_action: { label: string; method: string; path: string };
}

export interface WorkbenchSummary {
  pass_rate: number;
  pass_rate_delta: number;
  counts: Record<WorkbenchCountKey, number>;
  priority_items: TaskItem[];
  recent_activity: Array<{
    id: string;
    action: string;
    actor: string;
    created_at: string;
  }>;
  recent_runs: Array<{
    id: string;
    status: string;
    succeeded_count: number;
    failed_count: number;
    created_at: string;
  }>;
}

export const demoWorkbench: WorkbenchSummary = {
  pass_rate: 0.823,
  pass_rate_delta: -0.047,
  counts: {
    new_alerts: 2,
    pending_attributions: 7,
    pending_qa: 3,
    pending_retests: 1,
  },
  priority_items: [
    {
      id: "alert:logistics",
      kind: "alert",
      title: "物流异常催单 · 知识缺失激增",
      description: "通过率从 89% 降至 61%，影响 286 条对话；AI 已聚成 3 类原因。",
      priority: "P1",
      status: "open",
      impact_count: 286,
      created_at: "2026-07-30T09:20:00+08:00",
      next_action: {
        label: "查看样本并确认归因",
        method: "GET",
        path: "/alerts/logistics",
      },
    },
    {
      id: "task:refund-qa",
      kind: "task",
      title: "退款进度查询 · QA 草稿待审核",
      description: "已基于 18 条失败对话生成退款到账时效说明，附 2 条业务依据。",
      priority: "P1",
      status: "open",
      impact_count: 132,
      created_at: "2026-07-30T08:45:00+08:00",
      next_action: { label: "审核并发布 QA", method: "GET", path: "/qa/refund" },
    },
    {
      id: "task:retest",
      kind: "task",
      title: "破损件赔付规则 · 等待复测确认",
      description: "历史失败样本通过率 92%，新对话通过率 84%，已达到恢复阈值。",
      priority: "P2",
      status: "in_progress",
      impact_count: 48,
      created_at: "2026-07-29T17:30:00+08:00",
      next_action: { label: "确认复测结论", method: "GET", path: "/retests/damage" },
    },
  ],
  recent_activity: [
    {
      id: "a1",
      action: "退款进度 QA 已由林乔审核",
      actor: "林乔",
      created_at: "2026-07-30T10:14:00+08:00",
    },
    {
      id: "a2",
      action: "物流异常告警已合并 64 条新样本",
      actor: "系统",
      created_at: "2026-07-30T09:52:00+08:00",
    },
    {
      id: "a3",
      action: "破损件赔付进入新样本复测",
      actor: "系统",
      created_at: "2026-07-30T09:06:00+08:00",
    },
  ],
  recent_runs: [
    {
      id: "RUN-0729-18",
      status: "succeeded",
      succeeded_count: 1842,
      failed_count: 396,
      created_at: "2026-07-30T08:00:00+08:00",
    },
  ],
};

export async function getWorkbench(): Promise<WorkbenchSummary> {
  const response = await fetch("/api/workbench", { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error("workbench unavailable");
  const payload = (await response.json()) as WorkbenchSummary;
  if (payload.priority_items.length === 0) return demoWorkbench;
  return payload;
}
