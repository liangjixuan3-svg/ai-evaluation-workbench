import { StrictMode, act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CalibrationReviewDetail, CalibrationWorkspace } from "../../app/calibrationApi";
import { CalibrationWorkspacePage, CalibrationWorkspaceView, calibrationDimensionLabel } from "./CalibrationWorkspacePage";

const api = vi.hoisted(() => ({
  ensureTodayCalibrationBatch: vi.fn(),
  getCalibrationWorkspace: vi.fn(),
  getCalibrationReview: vi.fn(),
  agreeCalibration: vi.fn(),
  disagreeCalibration: vi.fn(),
}));

vi.mock("../../app/calibrationApi", async (importOriginal) => ({ ...await importOriginal<typeof import("../../app/calibrationApi")>(), ...api }));

const workspace: CalibrationWorkspace = {
  batch: { id: "batch-1", batch_date: "2026-08-10", target_count: 20, status: "open" },
  summary: { reviewed: 4, total: 12, pending: 8, agreement_rate: 0.75, top_disagreement_dimension: "completeness" },
  items: [{
    id: "review-1", review_id: "review-1", evaluation_result_id: "result-1", selection_reason: "low_confidence", status: "pending",
    agreed: null, corrected_passed: null, disagreement_dimension: null, review_basis: null, reviewed_by: null, reviewed_at: null,
    include_in_regression: false, scenario: "退款进度查询", total_score: 62, passed: false, confidence: "low",
  }],
};

const detail: CalibrationReviewDetail = {
  ...workspace.items[0],
  batch: workspace.batch,
  conversation: {
    id: "conversation-1", external_id: "case-001", scenario: "退款进度查询", status: "completed",
    messages: [{ role: "user", content: "退款什么时候到账？" }, { role: "assistant", content: "请耐心等待。" }],
  },
  evaluation: {
    total_score: 62, dimension_scores: { correctness: 72, completeness: 45, compliance: 84, tone: 88 }, passed: false,
    confidence: "low", reason: "未说明退款到账时效。", evidence: ["回复只要求用户等待。"],
    severe_factual_error: false, severe_compliance_error: false,
  },
  locked_rule: {
    quality_standard: { id: "standard-1", version_number: 3, rules: { completeness: "说明预计到账时效" } },
    prompt: { id: "prompt-1", name: "客服质量评测", version: "V5", content: "请按公司标准评分" },
    model: { provider: "openai-compatible", model: "deepseek-chat", parameters: { temperature: 0 } },
  },
};

class MiniNode {
  parentNode: MiniNode | null = null;
  childNodes: MiniNode[] = [];
  ownerDocument!: MiniDocument;
  nodeType: number;
  nodeName: string;
  private listeners = new Map<string, Array<(event: MiniEvent) => void>>();
  private text = "";

  constructor(nodeType: number, nodeName: string) { this.nodeType = nodeType; this.nodeName = nodeName; }
  appendChild(child: MiniNode) { child.parentNode = this; this.childNodes.push(child); return child; }
  insertBefore(child: MiniNode, before: MiniNode | null) { child.parentNode = this; const index = before ? this.childNodes.indexOf(before) : -1; if (index < 0) this.childNodes.push(child); else this.childNodes.splice(index, 0, child); return child; }
  removeChild(child: MiniNode) { const index = this.childNodes.indexOf(child); if (index >= 0) this.childNodes.splice(index, 1); child.parentNode = null; return child; }
  get firstChild() { return this.childNodes[0] ?? null; }
  get textContent(): string { return this.nodeType === 3 ? this.text : this.childNodes.map((child) => child.textContent).join(""); }
  set textContent(value: string) { this.childNodes = []; this.text = value; }
  addEventListener(type: string, listener: (event: MiniEvent) => void) { this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]); }
  removeEventListener(type: string, listener: (event: MiniEvent) => void) { this.listeners.set(type, (this.listeners.get(type) ?? []).filter((item) => item !== listener)); }
  dispatchEvent(event: MiniEvent) { event.target ??= this; for (let node: MiniNode | null = this; node; node = event.bubbles ? node.parentNode : null) node.listeners.get(event.type)?.forEach((listener) => listener(event)); return true; }
  contains(node: MiniNode | null): boolean { return node === this || this.childNodes.some((child) => child.contains(node)); }
}

class MiniElement extends MiniNode {
  tagName: string;
  namespaceURI = "http://www.w3.org/1999/xhtml";
  style: Record<string, string> = {};
  className = "";
  id = "";
  value = "";
  checked = false;
  disabled = false;
  type = "";
  private attributes = new Map<string, string>();

  constructor(tagName: string) { super(1, tagName.toUpperCase()); this.tagName = tagName.toUpperCase(); }
  setAttribute(name: string, value: string) { this.attributes.set(name, value); if (name === "class") this.className = value; if (name === "id") this.id = value; }
  getAttribute(name: string) { return this.attributes.get(name) ?? null; }
  removeAttribute(name: string) { this.attributes.delete(name); }
  focus() { this.ownerDocument.activeElement = this; }
}

class MiniText extends MiniNode { constructor(value: string) { super(3, "#text"); this.textContent = value; } }
class MiniEvent { target: MiniNode | null = null; bubbles = true; defaultPrevented = false; constructor(readonly type: string) {} preventDefault() { this.defaultPrevented = true; } stopPropagation() { this.bubbles = false; } }
class MiniDocument extends MiniNode {
  body: MiniElement;
  documentElement: MiniElement;
  activeElement: MiniElement | null = null;
  defaultView: unknown;
  constructor() { super(9, "#document"); this.ownerDocument = this; this.documentElement = this.createElement("html"); this.body = this.createElement("body"); this.documentElement.appendChild(this.body); this.appendChild(this.documentElement); this.defaultView = globalThis; }
  createElement(tag: string) { const element = new MiniElement(tag); element.ownerDocument = this; return element; }
  createElementNS(_namespace: string, tag: string) { return this.createElement(tag); }
  createTextNode(value: string) { const text = new MiniText(value); text.ownerDocument = this; return text; }
  getElementById(id: string) { return findNode(this, (node) => node instanceof MiniElement && node.id === id) as MiniElement | null; }
}

function findNode(root: MiniNode, predicate: (node: MiniNode) => boolean): MiniNode | null { if (predicate(root)) return root; for (const child of root.childNodes) { const found = findNode(child, predicate); if (found) return found; } return null; }
function findButton(root: MiniNode, text: string) { return findNode(root, (node) => node instanceof MiniElement && node.tagName === "BUTTON" && node.textContent.includes(text)) as MiniElement | null; }
function findInput(root: MiniNode, label: string) { return findNode(root, (node) => node instanceof MiniElement && node.getAttribute("aria-label") === label) as MiniElement | null; }
function deferred<T>() { let resolve!: (value: T) => void; let reject!: (reason?: unknown) => void; const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; }); return { promise, resolve, reject }; }

let mountedRoot: Root | null = null;
let mountedContainer: MiniElement | null = null;

async function mountCalibration(strict = false) {
  const document = new MiniDocument();
  Object.assign(globalThis, { document, window: globalThis, Node: MiniNode, HTMLElement: MiniElement, HTMLIFrameElement: MiniElement, Event: MiniEvent, IS_REACT_ACT_ENVIRONMENT: true });
  mountedContainer = document.createElement("div"); document.body.appendChild(mountedContainer);
  mountedRoot = createRoot(mountedContainer as unknown as Element);
  await act(async () => { mountedRoot!.render(strict ? <StrictMode><CalibrationWorkspacePage /></StrictMode> : <CalibrationWorkspacePage />); });
  return mountedContainer;
}

async function flush() { await act(async () => { for (let index = 0; index < 10; index += 1) await Promise.resolve(); }); }
async function click(root: MiniNode, text: string) { const button = findButton(root, text); expect(button).not.toBeNull(); await act(async () => { button!.dispatchEvent(new MiniEvent("click")); }); }

afterEach(async () => {
  if (mountedRoot) await act(async () => { mountedRoot!.unmount(); });
  mountedRoot = null; mountedContainer = null; vi.resetAllMocks();
});

function render(props: Partial<Parameters<typeof CalibrationWorkspaceView>[0]> = {}) {
  return renderToStaticMarkup(<CalibrationWorkspaceView
    workspace={workspace}
    status="pending"
    detail={detail}
    selectedId="review-1"
    busy=""
    error=""
    actor="审核人"
    correctedPassed={false}
    disagreementDimension="completeness"
    reviewBasis=""
    showDisagreeForm={false}
    onSelect={() => undefined}
    onStatusChange={() => undefined}
    onActorChange={() => undefined}
    onCorrectedPassedChange={() => undefined}
    onDisagreementDimensionChange={() => undefined}
    onReviewBasisChange={() => undefined}
    onShowDisagreeFormChange={() => undefined}
    onAgree={() => undefined}
    onDisagree={() => undefined}
    {...props}
  />);
}

describe("评测校准工作台", () => {
  it("在 StrictMode 中只准备一次今日批次，并在准备完成后加载待复核队列", async () => {
    const batch = deferred<CalibrationWorkspace["batch"]>();
    api.ensureTodayCalibrationBatch.mockReturnValue(batch.promise);
    api.getCalibrationWorkspace.mockResolvedValue({ ...workspace, items: [] });

    await mountCalibration(true);

    expect(api.ensureTodayCalibrationBatch).toHaveBeenCalledTimes(1);
    expect(api.getCalibrationWorkspace).not.toHaveBeenCalled();
    batch.resolve(workspace.batch);
    await flush();
    expect(api.getCalibrationWorkspace).toHaveBeenCalledWith("pending");
  });

  it("展示进度、待复核详情与双向复核入口", () => {
    const html = render();

    expect(html).toContain("评测校准");
    expect(html).toContain("今日进度");
    expect(html).toContain("人机一致率");
    expect(html).toContain("为什么进入复核");
    expect(html).toContain("认同模型判定");
    expect(html).toContain("不认同");
    expect(html).toContain("模型评测理由");
    expect(html).toContain("用户");
    expect(html).toContain("AI");
    expect(html).toContain("客服质量评测");
    expect(html).toContain("deepseek-chat");
    expect(html).toContain("aria-pressed=\"true\"");
    expect(html).toContain("aria-current=\"true\"");
    expect(html).toContain("maxLength=\"128\"");
    expect(html).not.toContain("<main class=\"calibration-detail\"");
  });

  it("在没有待复核任务时提示今日完成", () => {
    const html = render({ workspace: { ...workspace, summary: { ...workspace.summary, pending: 0 }, items: [] }, detail: null, selectedId: "" });

    expect(html).toContain("今日复核已完成");
  });

  it("将已复核结果展示为只读并标记回归案例", () => {
    const reviewed: CalibrationReviewDetail = {
      ...detail, status: "corrected", agreed: false, corrected_passed: true, disagreement_dimension: "completeness",
      review_basis: "人工确认已完整说明到账时效。", reviewed_by: "审核人", reviewed_at: "2026-08-10T09:00:00Z", include_in_regression: true,
    };
    const html = render({ detail: reviewed, workspace: { ...workspace, items: [reviewed] } });

    expect(html).toContain("人工复核结论");
    expect(html).toContain("人工判定通过");
    expect(html).toContain("已加入回归案例");
    expect(html).not.toContain("认同模型判定");
  });

  it("使用中文展示分歧维度", () => {
    expect(calibrationDimensionLabel("completeness")).toBe("完整性");
  });
});
