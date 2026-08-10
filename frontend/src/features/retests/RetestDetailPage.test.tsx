import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { RetestDetail } from "../../app/retestApi";
import { RetestDetailView } from "./RetestDetailPage";

const detail: RetestDetail = {
  id: "retest-1",
  workspace_state: "recovered",
  status: "recovered",
  scenario: "退款进度查询",
  priority: "P1",
  impact_count: 18,
  qa_version_id: "qa-v1",
  qa_version_number: 1,
  question: "退款什么时候到账？",
  answer: "1 至 3 个工作日到账。",
  published_by: "林乔",
  published_at: "2026-08-10T10:00:00Z",
  release_note: "知识库已上线",
  replay_samples: { available: 1, required: 1 },
  new_samples: { available: 1, required: 1 },
  before_pass_rate: 0.3,
  replay_pass_rate: 1,
  new_sample_pass_rate: 1,
  locked_rule: { rule_version: "V1", prompt_version: "V3", model: "deepseek-chat", threshold: 75, pass_rate_threshold: 0.8 },
  method: {
    sample_selection: { replay: "关联问题中的历史失败对话", new: "QA 发布后的同场景新对话" },
    quality_standard: { name: "客服质量标准", version: "V2", rules: {} },
    prompt: { name: "客服评测", version: "V3", content: "请依据公司标准逐项评测。" },
    model: "deepseek-chat",
    template: { name: "客服评测", version: "V1", weights: { correctness: 0.2 } },
    single_score_threshold: 75,
    cohort_pass_rate_threshold: 0.8,
    retest_rule: { version: "V1", config: {} },
  },
  explanation: {
    verdict: "两组通过率均达标，改善有效",
    formula: "历史回放和新对话两组通过率都达标",
    replay: { passed: 1, completed: 1, total: 1, pass_rate: 1 },
    new: { passed: 1, completed: 1, total: 1, pass_rate: 1 },
  },
  samples: [{
    id: "sample-1",
    cohort: "replay",
    status: "completed",
    external_id: "conversation-1",
    scenario: "退款进度查询",
    occurred_at: "2026-08-09T10:00:00Z",
    conversation: { messages: [{ role: "system", content: "遵循退款制度。" }, { role: "user", content: "退款什么时候到账？" }, { role: "assistant", content: "1 至 3 个工作日到账。" }] },
    evaluation: {
      total_score: 90,
      dimension_scores: { correctness: 90, completeness: 88, relevance: 92, service_experience: 86, compliance: 95 },
      passed: true,
      reason: "回答包含到账时效，信息准确完整。",
      evidence: ["1 至 3 个工作日到账。"],
      confidence: "high",
      severe_factual_error: false,
      severe_compliance_error: false,
    },
  }],
};

describe("复测详情页", () => {
  it("解释复测方法、最终结论和逐条判定", () => {
    const html = renderToStaticMarkup(
      <RetestDetailView detail={detail} filter="all" onFilterChange={() => undefined} />,
    );

    expect(html).toContain("为什么得到这个结论");
    expect(html).toContain("历史回放");
    expect(html).toContain("1/1 通过");
    expect(html).toContain("两组通过率均达标");
    expect(html).toContain("请依据公司标准逐项评测");
    expect(html).toContain("退款什么时候到账");
    expect(html).toContain("评测理由");
    expect(html).toContain("回答包含到账时效");
    expect(html).toContain("准确性");
    expect(html).toContain("引用证据");
    expect(html).toContain("系统指令");
  });

  it("对没有可展示消息的样本显示明确提示", () => {
    const emptyDetail: RetestDetail = {
      ...detail,
      samples: [{ ...detail.samples[0], conversation: { messages: [] } }],
    };

    const html = renderToStaticMarkup(
      <RetestDetailView detail={emptyDetail} filter="all" onFilterChange={() => undefined} />,
    );

    expect(html).toContain("该样本没有可展示的对话消息");
  });
});
