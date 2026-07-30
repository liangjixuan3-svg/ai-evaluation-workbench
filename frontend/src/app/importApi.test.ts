import { afterEach, describe, expect, it, vi } from "vitest";

import { confirmImport, previewImport, uploadJson } from "./importApi";

afterEach(() => vi.unstubAllGlobals());

describe("import API", () => {
  it("uploads parsed JSON documents", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "import-1", candidates: [] }), { status: 201 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await uploadJson("sample.json", { conversations: [] });

    expect(fetchMock).toHaveBeenCalledWith("/api/imports/json", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ filename: "sample.json", document: { conversations: [] } }),
    }));
  });

  it("previews and confirms one mapped import", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ valid_count: 2, items: [] })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ imported_count: 2 })));
    vi.stubGlobal("fetch", fetchMock);
    const mapping = {
      record_path: "$.data",
      occurred_at_path: "created_at",
      message_mode: "messages" as const,
      messages_path: "messages",
      role_path: "role",
      content_path: "content",
    };

    await previewImport("import-1", mapping);
    await confirmImport("import-1", "7 月客服对话");

    expect(fetchMock.mock.calls[0][0]).toBe("/api/imports/import-1/preview");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/imports/import-1/confirm");
  });
});
