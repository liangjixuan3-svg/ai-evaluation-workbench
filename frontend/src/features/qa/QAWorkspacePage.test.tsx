import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { QADetail } from "../../app/qaApi";
import { QADetailView, qaStateLabel } from "./QAWorkspacePage";

const detail: QADetail = {
  task_id: "task-1",
  cluster_id: "cluster-1",
  scenario: "退款进度查询",
  problem_summary: "没有说明退款到账时间",
  impact_count: 2,
  priority: "P1",
  task_status: "in_progress",
  state: "pending_review",
  confidence: "high",
  updated_at: "2026-08-10T01:00:00Z",
  weakest_dimension: "completeness",
  confirmation: { root_cause: "missing_knowledge", confirmed_by: "林乔", confirmed_at: "2026-08-10T01:00:00Z" },
  samples: [{
    result_id: "result-1",
    external_id: "refund-1",
    score: 42,
    reason: "回答缺少到账时间",
    messages: [
      { role: "user", content: "退款什么时候到账？" },
      { role: "assistant", content: "请稍后。" },
    ],
  }],
  draft: {
    id: "draft-1",
    status: "pending_review",
    confidence: "high",
    version_number: 1,
    content: {
      question: "退款什么时候到账？",
      answer: "通常 1 至 3 个工作日到账。",
      applicability: "退款审核通过",
      handling_steps: ["查询退款状态", "告知到账时间"],
      estimated_time: "1 至 3 个工作日",
      escalation: "超时转人工",
    },
    approved_by: null,
    approved_at: null,
    rejection_reason: null,
    evidence: [],
  },
};

describe("QA 审核详情", () => {
  it("展示失败样本、六个 QA 字段和业务依据门槛", () => {
    const html = renderToStaticMarkup(
      <QADetailView
        detail={detail}
        providerConfigured
        busy=""
        content={detail.draft!.content}
        evidence={{ source_ref: "", excerpt: "" }}
        rejectionReason=""
        onContentChange={() => undefined}
        onEvidenceChange={() => undefined}
        onRejectionReasonChange={() => undefined}
        onGenerate={() => undefined}
        onApprove={() => undefined}
        onReject={() => undefined}
        onDownload={() => undefined}
      />,
    );

    expect(html).toContain("退款什么时候到账？");
    expect(html).toContain("问题写法");
    expect(html).toContain("适用范围");
    expect(html).toContain("处理步骤");
    expect(html).toContain("业务依据");
    expect(html).toContain("审核通过并锁定");
    expect(html).toContain("disabled");
  });

  it("将状态转换成中文", () => {
    expect(qaStateLabel("awaiting_generation")).toBe("待生成");
    expect(qaStateLabel("pending_review")).toBe("待审核");
    expect(qaStateLabel("approved")).toBe("已通过");
    expect(qaStateLabel("rejected")).toBe("已驳回");
  });
});
