import { afterEach, describe, expect, it, vi } from "vitest";

import { copyEvaluationPrompt, deleteEvaluationPrompt, listEvaluationPrompts, publishEvaluationPrompt, saveEvaluationPrompt } from "./evaluationPromptApi";

afterEach(() => vi.unstubAllGlobals());

describe("评测 Prompt API", () => {
  it("调用列表、复制、保存、发布和删除接口", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({}))));
    vi.stubGlobal("fetch", fetchMock);

    await listEvaluationPrompts();
    await copyEvaluationPrompt("prompt-v1");
    await saveEvaluationPrompt("prompt-v2", "新的评测指令");
    await publishEvaluationPrompt("prompt-v2");
    await deleteEvaluationPrompt("prompt-v2");

    expect(fetchMock.mock.calls[0][0]).toBe("/api/evaluation-prompts");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/evaluation-prompts/drafts");
    expect(fetchMock.mock.calls[1][1]).toEqual(expect.objectContaining({ method: "POST", body: JSON.stringify({ source_id: "prompt-v1" }) }));
    expect(fetchMock.mock.calls[2][0]).toBe("/api/evaluation-prompts/prompt-v2");
    expect(fetchMock.mock.calls[2][1]).toEqual(expect.objectContaining({ method: "PUT", body: JSON.stringify({ content: "新的评测指令" }) }));
    expect(fetchMock.mock.calls[3][0]).toBe("/api/evaluation-prompts/prompt-v2/publish");
    expect(fetchMock.mock.calls[4][0]).toBe("/api/evaluation-prompts/prompt-v2");
    expect(fetchMock.mock.calls[4][1]).toEqual(expect.objectContaining({ method: "DELETE" }));
  });
});
