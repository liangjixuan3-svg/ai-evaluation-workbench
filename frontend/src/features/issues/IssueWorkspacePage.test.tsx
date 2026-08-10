import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { IssueDetail } from "../../app/issueApi";
import { IssueDetailView, issueCauseDisplay, rootCauseLabel } from "./IssueWorkspacePage";

const detail: IssueDetail = {
  id: "cluster-1",
  run_id: "run-1",
  scenario: "退款进度查询",
  weakest_dimension: "completeness",
  problem_summary: "没有说明退款到账时间",
  impact_count: 2,
  priority: "P1",
  status: "pending",
  confirmed_root_cause: null,
  created_at: "2026-08-02T01:00:00Z",
  alert: {
    id: "alert-1",
    kind: "issue_spike",
    priority: "P1",
    status: "open",
    baseline_value: 0.1,
    current_value: 1,
    impact_count: 2,
  },
  suggestion: {
    id: "suggestion-1",
    root_cause: "missing_knowledge",
    reason: "知识库没有退款时效说明",
    evidence: ["请稍后。"],
    confidence: "medium",
    provider: "openai-compatible",
    model: "deepseek-chat",
  },
  confirmation: null,
  task: null,
  samples: [{
    result_id: "result-1",
    conversation_id: "conversation-1",
    external_id: "refund-1",
    score: 42,
    dimensions: { completeness: 42 },
    reason: "没有说明退款到账时间",
    evidence: ["请稍后。"],
    confidence: "high",
    messages: [
      { role: "user", content: "退款什么时候到账？" },
      { role: "assistant", content: "请稍后。" },
    ],
  }],
};

describe("问题详情", () => {
  it("展示真实样本、AI 建议和人工确认入口", () => {
    const html = renderToStaticMarkup(
      <IssueDetailView
        detail={detail}
        providerConfigured
        busy=""
        rootCause="missing_knowledge"
        evidence=""
        clusterConfirmed={false}
        onGenerate={() => undefined}
        onRootCauseChange={() => undefined}
        onEvidenceChange={() => undefined}
        onClusterConfirmedChange={() => undefined}
        onConfirm={() => undefined}
      />,
    );

    expect(html).toContain("退款什么时候到账？");
    expect(html).toContain("知识库没有退款时效说明");
    expect(html).toContain("知识缺失");
    expect(html).toContain("确认归因并创建任务");
    expect(html).toContain("我已检查代表样本");
  });

  it("使用中文根因名称", () => {
    expect(rootCauseLabel("process_failure")).toBe("流程执行错误");
    expect(rootCauseLabel("service_tone")).toBe("服务态度");
  });

  it("问题列表优先展示人工确认的根因", () => {
    expect(issueCauseDisplay({
      confirmed_root_cause: "misunderstanding",
      suggestion: { root_cause: "missing_knowledge", confidence: "medium" },
    })).toBe("人工：理解错误");
    expect(issueCauseDisplay({
      confirmed_root_cause: null,
      suggestion: { root_cause: "missing_knowledge", confidence: "medium" },
    })).toBe("AI：知识缺失");
  });
});
