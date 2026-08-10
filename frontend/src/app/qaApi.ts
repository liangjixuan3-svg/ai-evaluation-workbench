export type QAFilter = "pending" | "approved" | "rejected" | "all";
export type QAState = "awaiting_generation" | "pending_review" | "approved" | "rejected";

export interface QAItem {
  task_id: string;
  cluster_id: string;
  scenario: string | null;
  problem_summary: string;
  impact_count: number;
  priority: string;
  task_status: string;
  state: QAState;
  confidence: "high" | "medium" | "low" | null;
  updated_at: string;
}

export interface QAListResponse {
  summary: {
    awaiting_generation_count: number;
    pending_review_count: number;
    approved_count: number;
    rejected_count: number;
  };
  items: QAItem[];
}

export interface QAContent {
  question: string;
  answer: string;
  applicability: string;
  handling_steps: string[];
  estimated_time: string;
  escalation: string;
}

export interface QADetail extends QAItem {
  weakest_dimension: string;
  confirmation: { root_cause: string; confirmed_by: string; confirmed_at: string | null } | null;
  samples: Array<{
    result_id: string;
    external_id: string;
    score: number;
    reason: string;
    messages: Array<{ role: string; content: string }>;
  }>;
  draft: {
    id: string;
    status: string;
    confidence: string;
    version_number: number;
    content: QAContent;
    approved_by: string | null;
    approved_at: string | null;
    rejection_reason: string | null;
    evidence: Array<{ source_type: string; source_ref: string; excerpt: string }>;
  } | null;
}

export interface QAApprovalInput {
  actor: string;
  edits: Partial<QAContent> & {
    business_evidence: Array<{ source_ref: string; excerpt: string }>;
  };
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

export const listQA = (status: QAFilter) => request<QAListResponse>(`/api/qa-workspace?status=${status}`);
export const getQADetail = (taskId: string) => request<QADetail>(`/api/qa-workspace/${taskId}`);
export const generateQA = (taskId: string) => request<{ id: string; status: string }>(`/api/qa-workspace/${taskId}/generate`, { method: "POST" });
export const approveQA = (draftId: string, input: QAApprovalInput) => request<{ id: string; version_number: number }>(`/api/qa-drafts/${draftId}/approve`, { method: "POST", body: JSON.stringify(input) });
export const rejectQA = (draftId: string, input: { actor: string; reason: string }) => request<{ id: string; status: string }>(`/api/qa-drafts/${draftId}/reject`, { method: "POST", body: JSON.stringify(input) });

export async function downloadQA(draftIds: string[], format: "json" | "csv", actor: string) {
  const response = await fetch("/api/qa-exports/download", {
    method: "POST",
    headers: { Accept: "*/*", "Content-Type": "application/json" },
    body: JSON.stringify({ actor, draft_ids: draftIds, format }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `下载失败 (${response.status})`);
  }
  return response;
}
