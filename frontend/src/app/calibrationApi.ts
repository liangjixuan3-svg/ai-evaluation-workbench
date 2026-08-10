export type CalibrationFilter = "pending" | "reviewed" | "all";
export type CalibrationReviewStatus = "pending" | "agreed" | "corrected";
export type CalibrationDimension = "correctness" | "completeness" | "relevance" | "service_experience" | "compliance" | "other";

export interface CalibrationDataSource {
  name: string;
  kind: string;
}

export interface CalibrationBatchSummary {
  id: string;
  batch_date: string;
  target_count: number;
  status: "open" | "completed";
}

export interface CalibrationReviewResult {
  id: string;
  review_id: string;
  evaluation_result_id: string;
  selection_reason: "low_confidence" | "score_boundary" | "severe_error" | "random_sample";
  status: CalibrationReviewStatus;
  agreed: boolean | null;
  corrected_passed: boolean | null;
  disagreement_dimension: CalibrationDimension | null;
  review_basis: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  include_in_regression: boolean;
}

export interface CalibrationWorkspaceItem extends CalibrationReviewResult {
  data_source: CalibrationDataSource;
  scenario: string | null;
  total_score: number;
  passed: boolean;
  confidence: "high" | "medium" | "low";
}

export interface CalibrationWorkspace {
  batch: CalibrationBatchSummary | null;
  summary: {
    reviewed: number;
    total: number;
    pending: number;
    agreement_rate: number | null;
    top_disagreement_dimension: CalibrationDimension | null;
  };
  items: CalibrationWorkspaceItem[];
}

export interface CalibrationReviewDetail extends CalibrationReviewResult {
  batch: CalibrationBatchSummary | null;
  data_source: CalibrationDataSource;
  conversation: {
    id: string;
    external_id: string;
    scenario: string | null;
    status: string;
    messages: Array<{ role: string; content: string }>;
  };
  evaluation: {
    total_score: number;
    dimension_scores: Record<string, number>;
    passed: boolean;
    confidence: "high" | "medium" | "low";
    reason: string;
    evidence: unknown[];
    severe_factual_error: boolean;
    severe_compliance_error: boolean;
  };
  locked_rule: {
    quality_standard: { id: string; version_number: number; rules: Record<string, unknown> } | null;
    prompt: { id: string; name: string; version: string; content: string };
    model: { provider: string; model: string; parameters: Record<string, unknown> };
  };
}

export interface DisagreeInput {
  actor: string;
  corrected_passed: boolean;
  disagreement_dimension: CalibrationDimension;
  review_basis: string;
}

function errorDetail(detail: unknown): string | null {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const messages = detail.map((item) => {
      if (typeof item === "string") return item;
      if (item && typeof item === "object" && "msg" in item && typeof item.msg === "string") return validationMessage(item.msg);
      return "";
    }).filter(Boolean);
    return messages.length ? messages.join("；") : null;
  }
  return null;
}

function validationMessage(message: string): string {
  if (message.includes("actor is required")) return "审核人不能为空";
  if (message.includes("at most 128 characters") || message.includes("max_length")) return "审核人不能超过 128 个字符";
  if (message.includes("review_basis is required")) return "人工依据不能为空";
  if (message.includes("review_basis must be at most 1000")) return "人工依据不能超过 1000 字";
  return message;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { Accept: "application/json", "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({})) as { detail?: unknown };
    throw new Error(errorDetail(payload.detail) || `请求失败（${response.status}）`);
  }
  return response.json() as Promise<T>;
}

export function ensureTodayCalibrationBatch(): Promise<CalibrationBatchSummary> {
  return request("/api/calibration/batches/today/ensure", { method: "POST" });
}

export function getCalibrationWorkspace(status: CalibrationFilter): Promise<CalibrationWorkspace> {
  return request(`/api/calibration/workspace?status=${status}`);
}

export function getCalibrationReview(reviewId: string): Promise<CalibrationReviewDetail> {
  return request(`/api/calibration/reviews/${reviewId}`);
}

export function agreeCalibration(reviewId: string, actor: string): Promise<CalibrationReviewResult> {
  return request(`/api/calibration/reviews/${reviewId}/agree`, { method: "POST", body: JSON.stringify({ actor }) });
}

export function disagreeCalibration(reviewId: string, input: DisagreeInput): Promise<CalibrationReviewResult> {
  return request(`/api/calibration/reviews/${reviewId}/disagree`, { method: "POST", body: JSON.stringify(input) });
}
