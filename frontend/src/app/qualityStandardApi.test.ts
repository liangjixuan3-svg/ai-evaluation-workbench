import { afterEach, describe, expect, it, vi } from "vitest";

import { getQualityStandardVersion, parseQualityStandard, publishQualityStandard, uploadQualityStandard } from "./qualityStandardApi";

afterEach(() => vi.unstubAllGlobals());

describe("公司质量标准 API", () => {
  it("使用 multipart 上传 Word 文件", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: "standard-1" }), { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["document"], "客服标准.docx");

    await uploadQualityStandard(file);

    const options = fetchMock.mock.calls[0][1] as RequestInit;
    expect(fetchMock.mock.calls[0][0]).toBe("/api/quality-standards");
    expect(options.method).toBe("POST");
    expect(options.body).toBeInstanceOf(FormData);
    expect((options.headers as Record<string, string>)["Content-Type"]).toBeUndefined();
  });

  it("调用解析与发布操作", async () => {
    const fetchMock = vi.fn().mockImplementation(
      () => Promise.resolve(new Response(JSON.stringify({ id: "standard-1" }))),
    );
    vi.stubGlobal("fetch", fetchMock);

    await parseQualityStandard("standard-1");
    await publishQualityStandard("standard-1");

    expect(fetchMock.mock.calls[0][0]).toBe("/api/quality-standards/standard-1/parse");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/quality-standards/standard-1/publish");
  });

  it("按评测绑定的版本 ID 读取完整规则", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ version_id: "version-2", rules: {} })),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getQualityStandardVersion("version-2");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/quality-standards/versions/version-2",
      expect.objectContaining({ headers: expect.objectContaining({ Accept: "application/json" }) }),
    );
  });
});
