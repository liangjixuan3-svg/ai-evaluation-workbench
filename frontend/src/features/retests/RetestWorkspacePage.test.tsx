import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { RetestWorkspace } from "../../app/retestApi";
import { RetestWorkspaceView } from "./RetestWorkspacePage";

const workspace: RetestWorkspace = {
  summary: {
    pending_publish_count: 1,
    waiting_samples_count: 1,
    ready_count: 1,
    running_count: 0,
    recovered_count: 1,
    not_recovered_count: 0,
  },
  pending_publish: [{
    qa_version_id: "qa-v1",
    version_number: 2,
    scenario: "退款进度查询",
    question: "退款什么时候到账？",
    answer: "通常 1 至 3 个工作日到账。",
    approved_by: "林乔",
    approved_at: "2026-08-10T09:00:00Z",
    priority: "P1",
    impact_count: 18,
  }],
  items: [{
    id: "retest-1",
    workspace_state: "ready",
    status: "queued",
    scenario: "物流异常催单",
    priority: "P1",
    impact_count: 32,
    qa_version_id: "qa-v2",
    qa_version_number: 1,
    question: "物流停滞怎么办？",
    answer: "查询节点后按规则催单。",
    published_by: "林乔",
    published_at: "2026-08-10T10:00:00Z",
    release_note: "物流知识库已上线",
    replay_samples: { available: 3, required: 1 },
    new_samples: { available: 2, required: 1 },
    before_pass_rate: 0.42,
    replay_pass_rate: null,
    new_sample_pass_rate: null,
    locked_rule: { rule_version: "V1", prompt_version: "V3", model: "deepseek-chat", threshold: 75, pass_rate_threshold: 0.8 },
  }],
};

describe("发布与复测工作台", () => {
  it("展示待发布、双样本进度和执行入口", () => {
    const html = renderToStaticMarkup(
      <RetestWorkspaceView
        workspace={workspace}
        busy=""
        error=""
        actor="林乔"
        releaseNotes={{}}
        onActorChange={() => undefined}
        onReleaseNoteChange={() => undefined}
        onPublish={() => undefined}
        onRefresh={() => undefined}
        onExecute={() => undefined}
      />,
    );

    expect(html).toContain("退款进度查询");
    expect(html).toContain("登记发布");
    expect(html).toContain("历史回放");
    expect(html).toContain("发布后新对话");
    expect(html).toContain("开始复测");
    expect(html).toContain("deepseek-chat");
    expect(html).toContain("V3");
    expect(html).toContain("组通过率 80%");
  });
});
