import { afterEach, describe, expect, it, vi } from "vitest";

import { agreeCalibration, disagreeCalibration, ensureTodayCalibrationBatch, getCalibrationReview, getCalibrationWorkspace } from "./calibrationApi";

afterEach(() => vi.unstubAllGlobals());

describe("评测校准 API", () => {
  it("调用准备批次、工作台、详情与两种复核接口", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({}))));
    vi.stubGlobal("fetch", fetchMock);

    await ensureTodayCalibrationBatch();
    await getCalibrationWorkspace("pending");
    await getCalibrationReview("review-1");
    await agreeCalibration("review-1", "审核人");
    await disagreeCalibration("review-2", {
      actor: "审核人",
      corrected_passed: false,
      disagreement_dimension: "completeness",
      review_basis: "业务规则要求说明预计到账时效。",
    });

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "/api/calibration/batches/today/ensure",
      "/api/calibration/workspace?status=pending",
      "/api/calibration/reviews/review-1",
      "/api/calibration/reviews/review-1/agree",
      "/api/calibration/reviews/review-2/disagree",
    ]);
    expect(fetchMock.mock.calls[0][1]).toEqual(expect.objectContaining({ method: "POST" }));
    expect(fetchMock.mock.calls[3][1]).toEqual(expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ actor: "审核人" }),
    }));
    expect(fetchMock.mock.calls[4][1]).toEqual(expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        actor: "审核人",
        corrected_passed: false,
        disagreement_dimension: "completeness",
        review_basis: "业务规则要求说明预计到账时效。",
      }),
    }));
  });

  it("优先展示后端中文 detail，并兼容 FastAPI 校验数组", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "该复核已完成" }), { status: 422 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: [{ msg: "依据不能为空" }, { msg: "审核人不能为空" }] }), { status: 422 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: [{ msg: "Value error, actor is required" }] }), { status: 422 })));

    await expect(ensureTodayCalibrationBatch()).rejects.toThrow("该复核已完成");
    await expect(getCalibrationWorkspace("all")).rejects.toThrow("依据不能为空；审核人不能为空");
    await expect(getCalibrationReview("review-1")).rejects.toThrow("审核人不能为空");
  });
});
