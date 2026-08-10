import { afterEach, describe, expect, it, vi } from "vitest";

import { confirmIssueAttribution, generateIssueAttribution, getIssueDetail, listIssues } from "./issueApi";

afterEach(() => vi.unstubAllGlobals());

describe("问题与归因 API", () => {
  it("调用列表、详情、AI 归因和人工确认接口", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({}))));
    vi.stubGlobal("fetch", fetchMock);

    await listIssues("pending");
    await getIssueDetail("cluster-1");
    await generateIssueAttribution("cluster-1");
    await confirmIssueAttribution("cluster-1", {
      actor: "林乔",
      root_cause: "missing_knowledge",
      evidence: ["已核对代表样本"],
      confirm_cluster: true,
    });

    expect(fetchMock.mock.calls[0][0]).toBe("/api/issues?status=pending");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/issues/cluster-1");
    expect(fetchMock.mock.calls[2][0]).toBe("/api/badcases/cluster-1/attribution");
    expect(fetchMock.mock.calls[2][1]).toEqual(expect.objectContaining({ method: "POST" }));
    expect(fetchMock.mock.calls[3][0]).toBe("/api/badcases/cluster-1/confirm-attribution");
    expect(fetchMock.mock.calls[3][1]).toEqual(expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        actor: "林乔",
        root_cause: "missing_knowledge",
        evidence: ["已核对代表样本"],
        confirm_cluster: true,
      }),
    }));
  });
});
