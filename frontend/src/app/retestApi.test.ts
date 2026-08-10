import { afterEach, describe, expect, it, vi } from "vitest";

import { executeRetest, getRetestWorkspace, publishQA, refreshRetestSamples } from "./retestApi";

afterEach(() => vi.unstubAllGlobals());

describe("发布与复测 API", () => {
  it("调用列表、发布、刷新样本和执行接口", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({}))));
    vi.stubGlobal("fetch", fetchMock);

    await getRetestWorkspace();
    await publishQA("qa-v1", { actor: "林乔", release_note: "知识库已上线" });
    await refreshRetestSamples("retest-1");
    await executeRetest("retest-1", "林乔");

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "/api/retest-workspace",
      "/api/qa-versions/qa-v1/publish",
      "/api/retests/retest-1/refresh-samples",
      "/api/retests/retest-1/execute",
    ]);
    expect(fetchMock.mock.calls[1][1]).toEqual(expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ actor: "林乔", release_note: "知识库已上线" }),
    }));
  });
});
