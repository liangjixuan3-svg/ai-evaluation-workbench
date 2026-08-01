import { afterEach, describe, expect, it, vi } from "vitest";

import { getEvaluation, getEvaluationResults, startEvaluation } from "./evaluationApi";

afterEach(() => vi.unstubAllGlobals());

describe("evaluation API", () => {
  it("starts and reads a real evaluation operation", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ run_id: "run-1" }), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ run_id: "run-1", stage: "evaluating" })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ total: 0, items: [] })));
    vi.stubGlobal("fetch", fetchMock);

    await startEvaluation({
      import_id: "import-1",
      quality_standard_version_id: "standard-v1",
      sample_size: 100,
      strategy: "risk_first",
      threshold: 75,
      seed: 20260730,
      actor: "operator",
    });
    await getEvaluation("run-1");
    await getEvaluationResults("run-1");

    expect(fetchMock.mock.calls[0][0]).toBe("/api/operations/evaluations");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/operations/evaluations/run-1");
    expect(fetchMock.mock.calls[2][0]).toBe("/api/operations/evaluations/run-1/results?limit=50");
  });
});
