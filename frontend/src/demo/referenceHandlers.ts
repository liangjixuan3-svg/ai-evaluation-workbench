import { http, HttpResponse } from "msw";

import type { CalibrationReviewDetail, CalibrationWorkspace, CalibrationDimension } from "../app/calibrationApi";
import type { EvaluationPromptVersion } from "../app/evaluationPromptApi";
import type { UploadedImport, ImportPreview, ImportMapping, ConfirmedImport } from "../app/importApi";
import { DEMO_TIME } from "./demoData";
import { calibrationDetail, confirmedImport, initialPrompt, standard, standardRules, standardVersion } from "./referenceData";

let promptVersions: EvaluationPromptVersion[] = [structuredClone(initialPrompt)];
let calibration: CalibrationReviewDetail = structuredClone(calibrationDetail);
let imports: ConfirmedImport[] = [structuredClone(confirmedImport)];
let uploaded: UploadedImport | null = null;

export function resetReferenceState() {
  promptVersions = [structuredClone(initialPrompt)];
  calibration = structuredClone(calibrationDetail);
  imports = [structuredClone(confirmedImport)];
  uploaded = null;
}

const json = <T,>(value: T) => HttpResponse.json(structuredClone(value) as Parameters<typeof HttpResponse.json>[0]);

function calibrationWorkspace(status: string): CalibrationWorkspace {
  const item = {
    ...calibration,
    data_source: calibration.data_source,
    scenario: calibration.conversation.scenario,
    total_score: calibration.evaluation.total_score,
    passed: calibration.evaluation.passed,
    confidence: calibration.evaluation.confidence,
  };
  const reviewed = calibration.status !== "pending" ? 1 : 0;
  return {
    batch: calibration.batch,
    summary: { reviewed, total: 1, pending: 1 - reviewed, agreement_rate: reviewed ? Number(calibration.agreed) : null, top_disagreement_dimension: calibration.disagreement_dimension },
    items: status === "all" || (status === "pending" && !reviewed) || (status === "reviewed" && reviewed) ? [item] : [],
  };
}

function getRecords(document: unknown): Record<string, unknown>[] {
  if (Array.isArray(document)) return document.filter((item): item is Record<string, unknown> => !!item && typeof item === "object");
  if (document && typeof document === "object") {
    const payload = document as Record<string, unknown>;
    for (const key of ["conversations", "records", "items"]) {
      if (Array.isArray(payload[key])) return (payload[key] as unknown[]).filter((item): item is Record<string, unknown> => !!item && typeof item === "object");
    }
    if (payload.payload && typeof payload.payload === "object") return getRecords(payload.payload);
  }
  return [];
}

export function createReferenceHandlers() {
  return [
    http.get("*/api/quality-standards", () => json([{ id: standard.id, name: standard.name, status: "published", latest_version: 1, published_version_id: standardVersion.version_id, published_rules: standardRules, updated_at: DEMO_TIME }])),
    http.get("*/api/quality-standards/versions/:id", ({ params }) => params.id === standardVersion.version_id ? json(standardVersion) : HttpResponse.json({ detail: "演示版本不存在" }, { status: 404 })),
    http.get("*/api/quality-standards/:id", ({ params }) => params.id === standard.id ? json(standard) : HttpResponse.json({ detail: "演示标准不存在" }, { status: 404 })),
    http.post("*/api/quality-standards", () => HttpResponse.json({ detail: "公开演示站不解析 Word/PDF；请查看内置示例标准或在本地真实模式上传。" }, { status: 422 })),
    http.get("*/api/evaluation-prompts", () => json(promptVersions)),
    http.post("*/api/evaluation-prompts/drafts", () => {
      const next: EvaluationPromptVersion = { ...structuredClone(promptVersions.at(-1) || initialPrompt), id: `demo-prompt-v${promptVersions.length + 1}`, version: `v${promptVersions.length + 1}`, active: false, published_at: null, created_at: DEMO_TIME };
      promptVersions.push(next); return json(next);
    }),
    http.put("*/api/evaluation-prompts/:id", async ({ request, params }) => {
      const item = promptVersions.find((value) => value.id === params.id && !value.published_at);
      if (!item) return HttpResponse.json({ detail: "只能编辑演示草稿" }, { status: 422 });
      const input = await request.json() as { content: string }; item.content = input.content; return json(item);
    }),
    http.post("*/api/evaluation-prompts/:id/publish", ({ params }) => {
      const item = promptVersions.find((value) => value.id === params.id && !value.published_at);
      if (!item) return HttpResponse.json({ detail: "演示草稿不存在" }, { status: 422 });
      promptVersions.forEach((value) => { value.active = false; }); item.active = true; item.published_at = DEMO_TIME; return json(item);
    }),
    http.delete("*/api/evaluation-prompts/:id", ({ params }) => {
      const index = promptVersions.findIndex((value) => value.id === params.id && !value.published_at);
      if (index < 0) return HttpResponse.json({ detail: "演示草稿不存在" }, { status: 422 });
      promptVersions.splice(index, 1); return new HttpResponse(null, { status: 204 });
    }),
    http.get("*/api/imports", () => json(imports)),
    http.post("*/api/imports/json", async ({ request }) => {
      const input = await request.json() as { filename: string; document: unknown };
      const records = getRecords(input.document);
      if (!records.length) return HttpResponse.json({ detail: "演示模式只识别顶层或 payload 中的 conversations/records/items 数组；真实模式支持更复杂字段。" }, { status: 422 });
      const mapping: ImportMapping = { record_path: "conversations", occurred_at_path: "created_at", message_mode: "messages", id_path: "conversation_id", scenario_path: "scene", status_path: "status", messages_path: "messages", role_path: "role", content_path: "content" };
      uploaded = { id: "demo-upload-1", filename: input.filename, status: "uploaded", record_count: records.length, candidates: [{ path: "conversations", length: records.length, object_ratio: 1, sample: records.slice(0, 2), suggested_mapping: mapping }] };
      return json(uploaded);
    }),
    http.post("*/api/imports/:id/preview", ({ params }) => {
      if (!uploaded || params.id !== uploaded.id) return HttpResponse.json({ detail: "演示上传不存在" }, { status: 404 });
      const records = uploaded.candidates[0].sample;
      const preview: ImportPreview = { valid_count: uploaded.record_count, error_count: 0, errors: [], items: records.map((item, index) => ({ external_id: String(item.conversation_id || `DEMO-${index + 1}`), scenario: String(item.scene || "客服场景"), status: String(item.status || "closed"), occurred_at: String(item.created_at || DEMO_TIME), redacted_messages: Array.isArray(item.messages) ? item.messages.map((message) => ({ role: String(message.role || "user"), content: String(message.content || "") })) : [] })) };
      return json(preview);
    }),
    http.post("*/api/imports/:id/confirm", async ({ request, params }) => {
      if (!uploaded || params.id !== uploaded.id) return HttpResponse.json({ detail: "演示上传不存在" }, { status: 404 });
      const input = await request.json() as { source_name: string };
      imports.push({ id: uploaded.id, filename: uploaded.filename, source_id: input.source_name, available_count: uploaded.record_count, confirmed_at: DEMO_TIME });
      return json({ inserted: uploaded.record_count, available_count: uploaded.record_count });
    }),
    http.post("*/api/calibration/batches/today/ensure", () => json(calibration.batch)),
    http.get("*/api/calibration/workspace", ({ request }) => json(calibrationWorkspace(new URL(request.url).searchParams.get("status") || "pending"))),
    http.get("*/api/calibration/reviews/:id", ({ params }) => params.id === calibration.review_id ? json(calibration) : HttpResponse.json({ detail: "演示校准不存在" }, { status: 404 })),
    http.post("*/api/calibration/reviews/:id/agree", async ({ params, request }) => {
      if (params.id !== calibration.review_id) return HttpResponse.json({ detail: "演示校准不存在" }, { status: 404 });
      const input = await request.json() as { actor: string };
      calibration.status = "agreed"; calibration.agreed = true; calibration.reviewed_by = input.actor; calibration.reviewed_at = DEMO_TIME;
      return json(calibration);
    }),
    http.post("*/api/calibration/reviews/:id/disagree", async ({ params, request }) => {
      if (params.id !== calibration.review_id) return HttpResponse.json({ detail: "演示校准不存在" }, { status: 404 });
      const input = await request.json() as { actor: string; corrected_passed: boolean; disagreement_dimension: CalibrationDimension; review_basis: string };
      calibration.status = "corrected"; calibration.agreed = false; calibration.corrected_passed = input.corrected_passed;
      calibration.disagreement_dimension = input.disagreement_dimension; calibration.review_basis = input.review_basis;
      calibration.reviewed_by = input.actor; calibration.reviewed_at = DEMO_TIME; calibration.include_in_regression = true;
      return json(calibration);
    }),
  ];
}
