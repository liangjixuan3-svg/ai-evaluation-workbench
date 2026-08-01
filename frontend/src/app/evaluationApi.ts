export interface StartEvaluationInput {
  import_id: string;
  quality_standard_version_id: string;
  sample_size: number;
  strategy: "random" | "risk_first" | "scenario_weighted";
  threshold: number;
  seed: number;
  actor: string;
}

export interface EvaluationDetail {
  run_id: string;
  stage: "queued" | "evaluating" | "completed" | "partial" | "manual_review";
  sample_count: number;
  completed_count: number;
  passed_count: number;
  failed_count: number;
  retrying_count: number;
  pass_rate: number | null;
  average_score: number | null;
  dimension_averages: Record<string, number>;
  latest_error: string | null;
  model: string;
  quality_standard: { name: string; version: number } | null;
  status: string;
  created_at: string;
}

export interface EvaluationResult {
  id: string;
  conversation_id: string;
  scenario: string | null;
  score: number;
  passed: boolean;
  dimensions: Record<string, number>;
  reason: string;
  evidence: string[];
  confidence: string;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: { Accept: "application/json", "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `请求失败 (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export function startEvaluation(input: StartEvaluationInput) {
  return request<{ run_id: string; status: string }>("/api/operations/evaluations", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function getEvaluation(runId: string) {
  return request<EvaluationDetail>(`/api/operations/evaluations/${runId}`);
}

export function getEvaluationResults(runId: string) {
  return request<{ total: number; items: EvaluationResult[] }>(
    `/api/operations/evaluations/${runId}/results?limit=50`,
  );
}

export function getProviderStatus() {
  return request<{ configured: boolean; base_url: string | null; model: string | null }>(
    "/api/evaluation/provider-status",
  );
}
