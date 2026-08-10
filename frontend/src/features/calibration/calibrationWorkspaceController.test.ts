import { describe, expect, it } from "vitest";
import { CalibrationWorkspaceController, ensureTodayOnce } from "./calibrationWorkspaceController";

function deferred<T>() { let resolve!: (value: T) => void; let reject!: (error: unknown) => void; const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; }); return { promise, resolve, reject }; }

describe("校准工作台请求协调器", () => {
  it("使旧 workspace 的成功和失败响应失效", () => { const c = new CalibrationWorkspaceController(); const old = c.beginWorkspace("pending"); const fresh = c.beginWorkspace("reviewed"); expect(c.isCurrentWorkspace(old, "pending")).toBe(false); expect(c.isCurrentWorkspace(fresh, "reviewed")).toBe(true); });
  it("状态切换使旧详情失效", () => { const c = new CalibrationWorkspaceController(); const a = c.beginDetail("A"); c.beginWorkspace("all"); expect(c.isCurrentDetail(a, "A")).toBe(false); expect(c.selectedReviewId()).toBe(""); });
  it("A/B 详情乱序只接受 B", () => { const c = new CalibrationWorkspaceController(); const a = c.beginDetail("A"); const b = c.beginDetail("B"); expect(c.isCurrentDetail(a, "A")).toBe(false); expect(c.isCurrentDetail(b, "B")).toBe(true); });
  it("提交期间切换后读取最新筛选", () => { const c = new CalibrationWorkspaceController(); c.beginWorkspace("pending"); c.beginWorkspace("reviewed"); expect(c.currentStatus()).toBe("reviewed"); });
  it("合并同日 ensure 并在 reject 后允许重试", async () => { const first = deferred<string>(); let calls = 0; const request = () => { calls += 1; return first.promise; }; expect(ensureTodayOnce(request)).toBe(ensureTodayOnce(request)); first.reject(new Error("失败")); await expect(ensureTodayOnce(request)).rejects.toThrow("失败"); const next = ensureTodayOnce(async () => "ok"); await expect(next).resolves.toBe("ok"); expect(calls).toBe(1); });
});
