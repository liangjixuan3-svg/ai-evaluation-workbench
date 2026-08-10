export type RetestWorkspaceState = "waiting_samples" | "ready" | "running" | "interrupted" | "recovered" | "not_recovered" | "failed";

export interface PendingPublishQA {
  qa_version_id: string; version_number: number; scenario: string; question: string; answer: string;
  approved_by: string | null; approved_at: string | null; priority: string; impact_count: number;
}

export interface RetestItem {
  id: string; workspace_state: RetestWorkspaceState; status: string; scenario: string; priority: string;
  impact_count: number; qa_version_id: string | null; qa_version_number: number | null; question: string;
  answer: string; published_by: string; published_at: string; release_note: string;
  replay_samples: { available: number; required: number }; new_samples: { available: number; required: number };
  before_pass_rate: number | null; replay_pass_rate: number | null; new_sample_pass_rate: number | null;
  locked_rule: { rule_version: string; prompt_version: string; model: string; threshold: number | null; pass_rate_threshold: number | null };
}

export interface RetestWorkspace {
  summary: { pending_publish_count: number; waiting_samples_count: number; ready_count: number; running_count: number; recovered_count: number; not_recovered_count: number };
  pending_publish: PendingPublishQA[];
  items: RetestItem[];
}

export interface RetestEvaluation {
  total_score: number;
  dimension_scores: Record<string, number>;
  passed: boolean;
  reason: string;
  evidence: string[];
  confidence: string;
  severe_factual_error: boolean;
  severe_compliance_error: boolean;
}

export interface RetestSampleDetail {
  id: string;
  cohort: "replay" | "new";
  status: "pending" | "completed";
  external_id: string;
  scenario: string | null;
  occurred_at: string;
  conversation: { messages: Array<{ role: string; content: string }> };
  evaluation: RetestEvaluation | null;
}

interface CohortExplanation {
  passed: number; completed: number; total: number; pass_rate: number | null;
}

export interface RetestDetail extends RetestItem {
  method: {
    sample_selection: { replay: string; new: string };
    quality_standard: { name: string; version: string; rules: Record<string, unknown> } | null;
    prompt: { name: string; version: string; content: string } | null;
    model: string;
    template: { name: string; version: string; weights: Record<string, number> } | null;
    single_score_threshold: number | null;
    cohort_pass_rate_threshold: number | null;
    retest_rule: { version: string; config: Record<string, unknown> } | null;
  };
  explanation: {
    verdict: string; formula: string; replay: CohortExplanation; new: CohortExplanation;
  };
  samples: RetestSampleDetail[];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { ...init, headers: { Accept: "application/json", "Content-Type": "application/json", ...init?.headers } });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({})) as { detail?: string };
    throw new Error(payload.detail || `请求失败（${response.status}）`);
  }
  return response.json() as Promise<T>;
}

export function getRetestWorkspace(): Promise<RetestWorkspace> { return request("/api/retest-workspace"); }
export function getRetestDetail(runId: string): Promise<RetestDetail> { return request(`/api/retest-workspace/${runId}`); }
export function publishQA(qaVersionId: string, input: { actor: string; release_note: string }): Promise<{ retest_run_id: string; workspace_state: RetestWorkspaceState }> {
  return request(`/api/qa-versions/${qaVersionId}/publish`, { method: "POST", body: JSON.stringify(input) });
}
export function refreshRetestSamples(runId: string): Promise<RetestItem> { return request(`/api/retests/${runId}/refresh-samples`, { method: "POST" }); }
export function executeRetest(runId: string, actor: string): Promise<{ id: string; status: string; replay_pass_rate: number | null; new_sample_pass_rate: number | null }> {
  return request(`/api/retests/${runId}/execute`, { method: "POST", body: JSON.stringify({ actor }) });
}
