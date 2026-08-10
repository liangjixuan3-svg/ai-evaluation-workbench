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
  get textContent(): string { return this.text + this.childNodes.map((child) => child.textContent).join(""); }
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
  selected = false;
  defaultSelected = false;
  multiple = false;
  type = "";
  selectionStart = 0;
  selectionEnd = 0;
  private attributes = new Map<string, string>();

  constructor(tagName: string) { super(1, tagName.toUpperCase()); this.tagName = tagName.toUpperCase(); if (this.tagName === "INPUT") this.type = "text"; }
  get options() { return this.childNodes.filter((node): node is MiniElement => node instanceof MiniElement && node.tagName === "OPTION"); }
  setAttribute(name: string, value: string) { this.attributes.set(name, value); if (name === "class") this.className = value; if (name === "id") this.id = value; }
  getAttribute(name: string) { return this.attributes.get(name) ?? null; }
  removeAttribute(name: string) { this.attributes.delete(name); }
  attachEvent(type: string, listener: (event: MiniEvent) => void) { this.addEventListener(type.replace(/^on/, ""), listener); }
  detachEvent(type: string, listener: (event: MiniEvent) => void) { this.removeEventListener(type.replace(/^on/, ""), listener); }
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
function findButton(root: MiniNode, text: string) { return findNode(root, (node) => node instanceof MiniElement && node.tagName === "BUTTON" && node.textContent === text) as MiniElement | null; }
function findButtonContaining(root: MiniNode, text: string) { return findNode(root, (node) => node instanceof MiniElement && node.tagName === "BUTTON" && node.textContent.includes(text)) as MiniElement | null; }
function findInput(root: MiniNode, label: string) { return findNode(root, (node) => node instanceof MiniElement && node.getAttribute("aria-label") === label) as MiniElement | null; }
function findTextarea(root: MiniNode) { return findNode(root, (node) => node instanceof MiniElement && node.tagName === "TEXTAREA") as MiniElement | null; }
function findByRole(root: MiniNode, role: string) { return findNode(root, (node) => node instanceof MiniElement && node.getAttribute("role") === role) as MiniElement | null; }
function deferred<T>() { let resolve!: (value: T) => void; let reject!: (reason?: unknown) => void; const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; }); return { promise, resolve, reject }; }

function workspaceItem(reviewId: string, scenario: string): CalibrationWorkspace["items"][number] {
  return { ...workspace.items[0], id: reviewId, review_id: reviewId, evaluation_result_id: `result-${reviewId}`, scenario };
}

function reviewDetail(item: CalibrationWorkspace["items"][number], externalId: string): CalibrationReviewDetail {
  return { ...detail, ...item, conversation: { ...detail.conversation, id: `conversation-${item.review_id}`, external_id: externalId, scenario: item.scenario } };
}

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
async function inputValue(input: MiniElement, value: string) {
  await act(async () => {
    input.focus();
    input.dispatchEvent(new MiniEvent("focusin"));
    input.value = value;
    input.dispatchEvent(new MiniEvent("keyup"));
  });
}
async function selectValue(select: MiniElement, value: string) { select.value = value; await act(async () => { select.dispatchEvent(new MiniEvent("change")); }); }

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

  it("点击已复核筛选会查询 reviewed 且不重复准备批次", async () => {
    const batch = deferred<CalibrationWorkspace["batch"]>();
    const pendingWorkspace = deferred<CalibrationWorkspace>();
    const pendingDetail = deferred<CalibrationReviewDetail>();
    const reviewedWorkspace = deferred<CalibrationWorkspace>();
    api.ensureTodayCalibrationBatch.mockReturnValue(batch.promise);
    api.getCalibrationWorkspace
      .mockReturnValueOnce(pendingWorkspace.promise)
      .mockReturnValueOnce(reviewedWorkspace.promise);
    api.getCalibrationReview.mockReturnValueOnce(pendingDetail.promise);

    const container = await mountCalibration();
    batch.resolve(workspace.batch);
    await flush();
    pendingWorkspace.resolve(workspace);
    await flush();
    pendingDetail.resolve(detail);
    await flush();

    expect(container.textContent).toContain("已复核");
    await click(container, "已复核");

    expect(api.getCalibrationWorkspace).toHaveBeenNthCalledWith(2, "reviewed");
    expect(api.ensureTodayCalibrationBatch).toHaveBeenCalledTimes(1);
  });

  it("选择 B 后丢弃 A 迟到的详情成功响应", async () => {
    const itemA = workspaceItem("review-A", "场景 A");
    const itemB = workspaceItem("review-B", "场景 B");
    const workspaceRequest = deferred<CalibrationWorkspace>();
    const detailA = deferred<CalibrationReviewDetail>();
    const detailB = deferred<CalibrationReviewDetail>();
    api.ensureTodayCalibrationBatch.mockResolvedValue(workspace.batch);
    api.getCalibrationWorkspace.mockReturnValueOnce(workspaceRequest.promise);
    api.getCalibrationReview.mockReturnValueOnce(detailA.promise).mockReturnValueOnce(detailB.promise);

    const container = await mountCalibration();
    await flush();
    workspaceRequest.resolve({ ...workspace, items: [itemA, itemB] });
    await flush();
    const buttonB = findButtonContaining(container, "场景 B");
    expect(buttonB).not.toBeNull();
    await act(async () => { buttonB!.dispatchEvent(new MiniEvent("click")); });
    expect(api.getCalibrationReview).toHaveBeenNthCalledWith(2, "review-B");

    detailB.resolve(reviewDetail(itemB, "case-B"));
    await flush();
    expect(container.textContent).toContain("case-B");
    expect(buttonB!.getAttribute("aria-current")).toBe("true");
    detailA.resolve(reviewDetail(itemA, "case-A"));
    await flush();
    expect(container.textContent).toContain("case-B");
    expect(container.textContent).not.toContain("case-A");
  });

  it("丢弃 A 迟到的详情失败且当前详情失败时不显示提交按钮", async () => {
    const itemA = workspaceItem("review-A", "场景 A");
    const itemB = workspaceItem("review-B", "场景 B");
    const workspaceRequest = deferred<CalibrationWorkspace>();
    const staleA = deferred<CalibrationReviewDetail>();
    const detailB = deferred<CalibrationReviewDetail>();
    const latestA = deferred<CalibrationReviewDetail>();
    api.ensureTodayCalibrationBatch.mockResolvedValue(workspace.batch);
    api.getCalibrationWorkspace.mockReturnValueOnce(workspaceRequest.promise);
    api.getCalibrationReview
      .mockReturnValueOnce(staleA.promise)
      .mockReturnValueOnce(detailB.promise)
      .mockReturnValueOnce(latestA.promise);

    const container = await mountCalibration();
    await flush();
    workspaceRequest.resolve({ ...workspace, items: [itemA, itemB] });
    await flush();
    const buttonA = findButtonContaining(container, "场景 A");
    const buttonB = findButtonContaining(container, "场景 B");
    expect(buttonA).not.toBeNull();
    expect(buttonB).not.toBeNull();
    await act(async () => { buttonB!.dispatchEvent(new MiniEvent("click")); });
    detailB.resolve(reviewDetail(itemB, "case-B"));
    await flush();

    staleA.reject(new Error("stale A detail failure"));
    await flush();
    expect(container.textContent).toContain("case-B");
    expect(container.textContent).not.toContain("stale A detail failure");

    await act(async () => { buttonA!.dispatchEvent(new MiniEvent("click")); });
    latestA.reject(new Error("current A detail failure"));
    await flush();
    expect(container.textContent).toContain("校准详情暂时无法加载");
    expect(container.textContent).toContain("current A detail failure");
    expect(findButton(container, "认同模型判定")).toBeNull();
    expect(findButton(container, "提交修正结论")).toBeNull();
    expect(buttonA!.getAttribute("aria-current")).toBe("true");
  });

  it("同意提交期间跟随 latest status 且旧 workspace 成功不污染 all", async () => {
    const batch = deferred<CalibrationWorkspace["batch"]>();
    const pendingWorkspace = deferred<CalibrationWorkspace>();
    const pendingDetail = deferred<CalibrationReviewDetail>();
    const submission = deferred<CalibrationReviewDetail>();
    const reviewedFromFilter = deferred<CalibrationWorkspace>();
    const reviewedAfterSubmit = deferred<CalibrationWorkspace>();
    const reviewedDetail = deferred<CalibrationReviewDetail>();
    const allWorkspace = deferred<CalibrationWorkspace>();
    const allDetail = deferred<CalibrationReviewDetail>();
    const reviewedItem = { ...workspaceItem("review-reviewed", "latest reviewed"), status: "agreed" as const, agreed: true, reviewed_by: "林乔" };
    const allItem = workspaceItem("review-all", "latest all");
    const staleItem = { ...workspaceItem("review-stale", "stale reviewed"), status: "agreed" as const, agreed: true };
    api.ensureTodayCalibrationBatch.mockReturnValue(batch.promise);
    api.getCalibrationWorkspace
      .mockReturnValueOnce(pendingWorkspace.promise)
      .mockReturnValueOnce(reviewedFromFilter.promise)
      .mockReturnValueOnce(reviewedAfterSubmit.promise)
      .mockReturnValueOnce(allWorkspace.promise);
    api.getCalibrationReview
      .mockReturnValueOnce(pendingDetail.promise)
      .mockReturnValueOnce(reviewedDetail.promise)
      .mockReturnValueOnce(allDetail.promise);
    api.agreeCalibration.mockReturnValueOnce(submission.promise);

    const container = await mountCalibration();
    batch.resolve(workspace.batch);
    await flush();
    pendingWorkspace.resolve(workspace);
    await flush();
    pendingDetail.resolve(detail);
    await flush();

    const actorInput = findInput(container, "审核人");
    expect(actorInput).not.toBeNull();
    await inputValue(actorInput!, "  林乔  ");
    await click(container, "认同模型判定");
    expect(findByRole(container, "alertdialog")).not.toBeNull();
    const confirmButton = findButton(container, "确认提交");
    expect(confirmButton).not.toBeNull();
    expect(confirmButton!.ownerDocument.activeElement).toBe(confirmButton);
    await click(container, "确认提交");
    expect(api.agreeCalibration).toHaveBeenCalledWith("review-1", "林乔");

    await click(container, "已复核");
    expect(api.getCalibrationWorkspace).toHaveBeenNthCalledWith(2, "reviewed");
    submission.resolve({ ...detail, status: "agreed", agreed: true, reviewed_by: "林乔" });
    await flush();

    expect(api.getCalibrationWorkspace).toHaveBeenNthCalledWith(3, "reviewed");
    expect(api.getCalibrationWorkspace).toHaveBeenCalledTimes(3);
    expect(api.ensureTodayCalibrationBatch).toHaveBeenCalledTimes(1);

    reviewedAfterSubmit.resolve({ ...workspace, items: [reviewedItem] });
    await flush();
    reviewedDetail.resolve(reviewDetail(reviewedItem, "case-reviewed"));
    await flush();
    await click(container, "全部");
    expect(api.getCalibrationWorkspace).toHaveBeenNthCalledWith(4, "all");
    expect(container.textContent).not.toContain("latest reviewed");

    reviewedFromFilter.resolve({ ...workspace, items: [staleItem] });
    await flush();
    expect(container.textContent).not.toContain("stale reviewed");
    allWorkspace.resolve({ ...workspace, items: [allItem] });
    await flush();
    allDetail.resolve(reviewDetail(allItem, "case-all"));
    await flush();
    expect(container.textContent).toContain("latest all");
    expect(container.textContent).not.toContain("stale reviewed");
    expect(api.getCalibrationWorkspace.mock.calls.map(([requestedStatus]) => requestedStatus)).toEqual(["pending", "reviewed", "reviewed", "all"]);
    expect(api.ensureTodayCalibrationBatch).toHaveBeenCalledTimes(1);
  });

  it("通过真实表单提交不认同并丢弃旧 workspace 失败", async () => {
    const initialWorkspace = deferred<CalibrationWorkspace>();
    const initialDetail = deferred<CalibrationReviewDetail>();
    const submission = deferred<CalibrationReviewDetail>();
    const staleReviewed = deferred<CalibrationWorkspace>();
    const latestReviewed = deferred<CalibrationWorkspace>();
    const latestReviewedDetail = deferred<CalibrationReviewDetail>();
    const latestAll = deferred<CalibrationWorkspace>();
    const latestAllDetail = deferred<CalibrationReviewDetail>();
    const correctedItem = { ...workspaceItem("review-corrected", "latest corrected"), status: "corrected" as const, agreed: false, corrected_passed: true, disagreement_dimension: "completeness" as const, review_basis: "符合退款时效规则", reviewed_by: "陈宁" };
    const allItem = workspaceItem("review-all-after-reject", "latest all after reject");
    api.ensureTodayCalibrationBatch.mockResolvedValue(workspace.batch);
    api.getCalibrationWorkspace
      .mockReturnValueOnce(initialWorkspace.promise)
      .mockReturnValueOnce(staleReviewed.promise)
      .mockReturnValueOnce(latestReviewed.promise)
      .mockReturnValueOnce(latestAll.promise);
    api.getCalibrationReview
      .mockReturnValueOnce(initialDetail.promise)
      .mockReturnValueOnce(latestReviewedDetail.promise)
      .mockReturnValueOnce(latestAllDetail.promise);
    api.disagreeCalibration.mockReturnValueOnce(submission.promise);

    const container = await mountCalibration();
    await flush();
    initialWorkspace.resolve(workspace);
    await flush();
    initialDetail.resolve(detail);
    await flush();

    await inputValue(findInput(container, "审核人")!, "  陈宁  ");
    await click(container, "不认同");
    await selectValue(findInput(container, "正确结论")!, "true");
    await selectValue(findInput(container, "主要分歧维度")!, "completeness");
    await inputValue(findTextarea(container)!, "  符合退款时效规则  ");
    await click(container, "提交修正结论");

    expect(api.disagreeCalibration).toHaveBeenCalledWith("review-1", {
      actor: "陈宁",
      corrected_passed: true,
      disagreement_dimension: "completeness",
      review_basis: "符合退款时效规则",
    });
    await click(container, "已复核");
    submission.resolve({ ...detail, ...correctedItem });
    await flush();
    expect(api.getCalibrationWorkspace).toHaveBeenNthCalledWith(3, "reviewed");

    latestReviewed.resolve({ ...workspace, items: [correctedItem] });
    await flush();
    latestReviewedDetail.resolve(reviewDetail(correctedItem, "case-corrected"));
    await flush();
    await click(container, "全部");
    expect(container.textContent).not.toContain("latest corrected");
    staleReviewed.reject(new Error("stale reviewed failure"));
    await flush();
    expect(container.textContent).not.toContain("stale reviewed failure");

    latestAll.resolve({ ...workspace, items: [allItem] });
    await flush();
    latestAllDetail.resolve(reviewDetail(allItem, "case-all-after-reject"));
    await flush();
    expect(container.textContent).toContain("latest all after reject");
    expect(container.textContent).not.toContain("stale reviewed failure");
    expect(api.getCalibrationWorkspace.mock.calls.map(([requestedStatus]) => requestedStatus)).toEqual(["pending", "reviewed", "reviewed", "all"]);
    expect(api.ensureTodayCalibrationBatch).toHaveBeenCalledTimes(1);
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
