import { afterEach, describe, expect, it, vi } from "vitest";

import { approveQA, downloadQA, generateQA, getQADetail, listQA, rejectQA } from "./qaApi";

afterEach(() => vi.unstubAllGlobals());

describe("QA 审核 API", () => {
  it("调用列表、详情、生成、审批和驳回接口", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({}))));
    vi.stubGlobal("fetch", fetchMock);

    await listQA("pending");
    await getQADetail("task-1");
    await generateQA("task-1");
    await approveQA("draft-1", { actor: "林乔", edits: { business_evidence: [{ source_ref: "退款规则", excerpt: "1 至 3 个工作日到账" }] } });
    await rejectQA("draft-1", { actor: "林乔", reason: "规则不适用" });

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "/api/qa-workspace?status=pending",
      "/api/qa-workspace/task-1",
      "/api/qa-workspace/task-1/generate",
      "/api/qa-drafts/draft-1/approve",
      "/api/qa-drafts/draft-1/reject",
    ]);
    expect(fetchMock.mock.calls[2][1]).toEqual(expect.objectContaining({ method: "POST" }));
    expect(fetchMock.mock.calls[4][1]).toEqual(expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ actor: "林乔", reason: "规则不适用" }),
    }));
  });

  it("下载已通过的 QA 文件", async () => {
    const response = new Response("{}", { headers: { "Content-Type": "application/json" } });
    const fetchMock = vi.fn().mockResolvedValue(response);
    vi.stubGlobal("fetch", fetchMock);

    const result = await downloadQA(["draft-1"], "json", "林乔");

    expect(result).toBe(response);
    expect(fetchMock).toHaveBeenCalledWith("/api/qa-exports/download", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ actor: "林乔", draft_ids: ["draft-1"], format: "json" }),
    }));
  });
});
