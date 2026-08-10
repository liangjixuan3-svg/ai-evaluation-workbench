import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { CalibrationReviewDetail, CalibrationWorkspace } from "../../app/calibrationApi";
import { CalibrationWorkspaceView, calibrationDimensionLabel } from "./CalibrationWorkspacePage";

const workspace: CalibrationWorkspace = {
  batch: { id: "batch-1", batch_date: "2026-08-10", target_count: 20, status: "open" },
  summary: { reviewed: 4, total: 12, pending: 8, agreement_rate: 0.75, top_disagreement_dimension: "completeness" },
  items: [{
    id: "review-1", review_id: "review-1", evaluation_result_id: "result-1", selection_reason: "low_confidence", status: "pending",
    agreed: null, corrected_passed: null, disagreement_dimension: null, review_basis: null, reviewed_by: null, reviewed_at: null,
    include_in_regression: false, scenario: "退款进度查询", total_score: 62, passed: false, confidence: "low",
  }],
};

const detail: CalibrationReviewDetail = {
  ...workspace.items[0],
  batch: workspace.batch,
  conversation: {
    id: "conversation-1", external_id: "case-001", scenario: "退款进度查询", status: "completed",
    messages: [{ role: "user", content: "退款什么时候到账？" }, { role: "assistant", content: "请耐心等待。" }],
  },
  evaluation: {
    total_score: 62, dimension_scores: { correctness: 72, completeness: 45, compliance: 84, tone: 88 }, passed: false,
    confidence: "low", reason: "未说明退款到账时效。", evidence: ["回复只要求用户等待。"],
    severe_factual_error: false, severe_compliance_error: false,
  },
  locked_rule: {
    quality_standard: { id: "standard-1", version_number: 3, rules: { completeness: "说明预计到账时效" } },
    prompt: { id: "prompt-1", name: "客服质量评测", version: "V5", content: "请按公司标准评分" },
    model: { provider: "openai-compatible", model: "deepseek-chat", parameters: { temperature: 0 } },
  },
};

function render(props: Partial<Parameters<typeof CalibrationWorkspaceView>[0]> = {}) {
  return renderToStaticMarkup(<CalibrationWorkspaceView
    workspace={workspace}
    status="pending"
    detail={detail}
    selectedId="review-1"
    busy=""
    error=""
    actor="审核人"
    correctedPassed={false}
    disagreementDimension="completeness"
    reviewBasis=""
    showDisagreeForm={false}
    onSelect={() => undefined}
    onStatusChange={() => undefined}
    onActorChange={() => undefined}
    onCorrectedPassedChange={() => undefined}
    onDisagreementDimensionChange={() => undefined}
    onReviewBasisChange={() => undefined}
    onShowDisagreeFormChange={() => undefined}
    onAgree={() => undefined}
    onDisagree={() => undefined}
    {...props}
  />);
}

describe("评测校准工作台", () => {
  it("展示进度、待复核详情与双向复核入口", () => {
    const html = render();

    expect(html).toContain("评测校准");
    expect(html).toContain("今日进度");
    expect(html).toContain("人机一致率");
    expect(html).toContain("为什么进入复核");
    expect(html).toContain("认同模型判定");
    expect(html).toContain("不认同");
    expect(html).toContain("模型评测理由");
    expect(html).toContain("用户");
    expect(html).toContain("AI");
    expect(html).toContain("客服质量评测");
    expect(html).toContain("deepseek-chat");
  });

  it("在没有待复核任务时提示今日完成", () => {
    const html = render({ workspace: { ...workspace, summary: { ...workspace.summary, pending: 0 }, items: [] }, detail: null, selectedId: "" });

    expect(html).toContain("今日复核已完成");
  });

  it("将已复核结果展示为只读并标记回归案例", () => {
    const reviewed: CalibrationReviewDetail = {
      ...detail, status: "corrected", agreed: false, corrected_passed: true, disagreement_dimension: "completeness",
      review_basis: "人工确认已完整说明到账时效。", reviewed_by: "审核人", reviewed_at: "2026-08-10T09:00:00Z", include_in_regression: true,
    };
    const html = render({ detail: reviewed, workspace: { ...workspace, items: [reviewed] } });

    expect(html).toContain("人工复核结论");
    expect(html).toContain("人工判定通过");
    expect(html).toContain("已加入回归案例");
    expect(html).not.toContain("认同模型判定");
  });

  it("使用中文展示分歧维度", () => {
    expect(calibrationDimensionLabel("completeness")).toBe("完整性");
  });
});
