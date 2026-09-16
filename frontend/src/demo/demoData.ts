import { demoWorkbench as originalWorkbench, type WorkbenchSummary } from "../app/api";
import type { IssueDetail } from "../app/issueApi";
import type { QADetail } from "../app/qaApi";
import type { EvaluationDetail, EvaluationResult } from "../app/evaluationApi";
import type { RetestItem } from "../app/retestApi";

export const DEMO_TIME = "2026-07-30T09:20:00+08:00";

export const initialIssue: IssueDetail = {
  id: "logistics", run_id: "demo-run-1", scenario: "物流异常催单", weakest_dimension: "completeness",
  problem_summary: "物流异常时只回复等待，缺少查询结果、催办动作和反馈时效。",
  impact_count: 64, priority: "P1", status: "pending", confirmed_root_cause: null,
  created_at: DEMO_TIME,
  alert: { id: "alert-logistics", kind: "pass_rate_drop", priority: "P1", status: "open", baseline_value: 0.89, current_value: 0.61, impact_count: 64 },
  suggestion: {
    id: "suggestion-logistics", root_cause: "missing_knowledge", confidence: "high", provider: "演示数据", model: "预生成评测结果",
    reason: "多条对话均未给出物流异常催办条件和后续反馈时效，优先检查知识库是否缺少对应处理规范。",
    evidence: ["已经三天没有物流更新，可以帮我催一下吗？", "请耐心等待。"],
  },
  confirmation: null, task: null,
  samples: [{
    result_id: "result-logistics-1", conversation_id: "conversation-logistics-1", external_id: "DEMO-L001",
    score: 38, dimensions: { correctness: 65, completeness: 20, relevance: 45, service_experience: 45, compliance: 85 },
    reason: "客服没有查询物流轨迹，也没有说明催办条件、动作或反馈时间，用户不知道下一步如何处理。",
    evidence: ["物流三天没更新，帮我催一下", "请耐心等待。"], confidence: "high",
    messages: [{ role: "user", content: "物流三天没更新，帮我催一下。" }, { role: "assistant", content: "请耐心等待。" }],
  }],
};

export const initialQA: QADetail = {
  task_id: "qa-logistics", cluster_id: "logistics", scenario: "物流异常催单",
  problem_summary: initialIssue.problem_summary, impact_count: 64, priority: "P1", task_status: "open",
  state: "pending_review", confidence: "high", updated_at: DEMO_TIME, weakest_dimension: "完整性",
  confirmation: { root_cause: "missing_knowledge", confirmed_by: "林乔", confirmed_at: DEMO_TIME },
  samples: initialIssue.samples.map((sample) => ({ result_id: sample.result_id, external_id: sample.external_id, score: sample.score, reason: sample.reason, messages: sample.messages })),
  draft: {
    id: "draft-logistics", status: "pending_review", confidence: "high", version_number: 1,
    content: {
      question: "物流超过预计时间仍未更新，如何催办？",
      answer: "请先核对订单或物流单号及最近轨迹；若已超过预计时效，联系承运商或转人工催办，并告知反馈时间。未实际创建催办时不要说已催办。",
      applicability: "物流异常催单（演示规则，非真实制度）",
      handling_steps: ["核对订单号及真实轨迹", "判断是否超过预计时效", "符合条件后转人工或联系承运商"],
      estimated_time: "示例：24 小时内反馈进展，实际以公司制度为准",
      escalation: "超过承诺时效仍无进展时转人工核查",
    },
    approved_by: null, approved_at: null, rejection_reason: null,
    evidence: [{ source_type: "business_reference", source_ref: "公司客服质量标准示例（虚构）", excerpt: "物流异常时必须说明下一步与反馈时效。" }],
  },
};

export const demoResults: EvaluationResult[] = [
  {
    id: "result-refund", conversation_id: "DEMO-R001", scenario: "退款进度查询", score: 91, passed: true,
    dimensions: { correctness: 95, completeness: 85, relevance: 95, service_experience: 90, compliance: 95 },
    reason: "回答了退款当前状态和预计到账时间，并给出了超时后的核查方式。",
    evidence: ["退款处理中，预计 1 至 7 个工作日原路退回。"], confidence: "high",
  },
  {
    id: "result-logistics", conversation_id: "DEMO-L001", scenario: "物流异常催单", score: 38, passed: false,
    dimensions: { correctness: 65, completeness: 20, relevance: 45, service_experience: 45, compliance: 85 },
    reason: initialIssue.samples[0].reason,
    evidence: ["请耐心等待。"], confidence: "high",
  },
];

export const initialRun: EvaluationDetail = {
  run_id: "demo-run-1", stage: "completed", sample_count: 2, completed_count: 2, passed_count: 1, failed_count: 1,
  retrying_count: 0, pass_rate: 0.5, average_score: 65,
  dimension_averages: { correctness: 80, completeness: 53, relevance: 70, service_experience: 68, compliance: 90 },
  latest_error: null, model: "演示 · 预生成结果", quality_standard: { name: "客服质量标准示例", version: 1, version_id: "demo-standard-v1" },
  prompt: { id: "demo-prompt-v1", name: "客服质量评测", version: "v1" }, status: "succeeded", created_at: DEMO_TIME,
};

export const retestTemplate: RetestItem = {
  id: "retest-logistics", workspace_state: "ready", status: "ready", scenario: "物流异常催单", priority: "P1",
  impact_count: 64, qa_version_id: "qa-logistics-v1", qa_version_number: 1,
  question: initialQA.draft!.content.question, answer: initialQA.draft!.content.answer,
  published_by: "林乔", published_at: DEMO_TIME, release_note: "演示发布",
  replay_samples: { available: 2, required: 2 }, new_samples: { available: 2, required: 2 },
  before_pass_rate: 0.46, replay_pass_rate: null, new_sample_pass_rate: null,
  locked_rule: { rule_version: "客服质量标准示例 V1", prompt_version: "V1", model: "演示 · 预生成结果", threshold: 75, pass_rate_threshold: 0.8 },
};

export const demoWorkbench: WorkbenchSummary = {
  ...originalWorkbench,
  pass_rate: 0.5,
  recent_activity: [
    { id: "demo-a1", action: "演示评测已生成两条样本结果", actor: "演示数据", created_at: DEMO_TIME },
    { id: "demo-a2", action: "演示物流异常问题已聚类", actor: "演示数据", created_at: DEMO_TIME },
  ],
  recent_runs: [{ id: "demo-run-1", status: "succeeded", succeeded_count: 2, failed_count: 1, created_at: DEMO_TIME }],
  counts: { new_alerts: 1, pending_attributions: 1, pending_qa: 1, pending_retests: 0 },
  priority_items: [
    {
      ...originalWorkbench.priority_items[0], impact_count: 64,
      title: "物流异常催单 · 待确认知识缺口",
      description: "示例失败对话只回复等待，缺少查询、催办与反馈时间。",
      next_action: { label: "查看样本并确认归因", method: "GET", path: "/alerts/logistics" },
    },
    {
      ...originalWorkbench.priority_items[1], impact_count: 64,
      title: "物流异常催单 · QA 草稿待审核",
      description: "基于同一失败案例生成演示 QA，审核时需补业务依据。",
      next_action: { label: "审核示例 QA", method: "GET", path: "/qa/qa-logistics" },
    },
    {
      ...originalWorkbench.priority_items[2], impact_count: 2,
      title: "两条客服对话 · 可启动模拟评测",
      description: "用已发布的演示规则和 Prompt 查看逐条评分与理由。",
      next_action: { label: "发起模拟评测", method: "GET", path: "/runs/new" },
    },
  ],
};
