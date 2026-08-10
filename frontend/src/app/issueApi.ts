export type IssueStatus = "pending" | "confirmed" | "all";
export type RootCause = "missing_knowledge" | "misunderstanding" | "process_failure" | "service_tone" | "other";

export interface IssueSuggestionSummary {
  root_cause: RootCause;
  confidence: "high" | "medium" | "low";
}

export interface IssueItem {
  id: string;
  run_id: string;
  scenario: string | null;
  weakest_dimension: string;
  problem_summary: string;
  impact_count: number;
  priority: string;
  status: "pending" | "confirmed";
  confirmed_root_cause: RootCause | "mixed" | null;
  suggestion: IssueSuggestionSummary | null;
  created_at: string;
}

export interface IssueListResponse {
  summary: {
    pending_count: number;
    confirmed_count: number;
    impacted_count: number;
    missing_knowledge_count: number;
  };
  items: IssueItem[];
}

export interface AttributionSuggestion extends IssueSuggestionSummary {
  id: string;
  reason: string;
  evidence: string[];
  provider: string;
  model: string;
}

export interface IssueDetail extends Omit<IssueItem, "suggestion"> {
  alert: {
    id: string;
    kind: string;
    priority: string;
    status: string;
    baseline_value: number;
    current_value: number;
    impact_count: number;
  } | null;
  suggestion: AttributionSuggestion | null;
  confirmation: {
    root_cause: RootCause | "mixed";
    confirmed_by: string;
    confirmed_at: string | null;
  } | null;
  task: { id: string; type: string; status: string; title: string } | null;
  samples: Array<{
    result_id: string;
    conversation_id: string;
    external_id: string;
    score: number;
    dimensions: Record<string, number>;
    reason: string;
    evidence: string[];
    confidence: string;
    messages: Array<{ role: string; content: string }>;
  }>;
}

export interface ConfirmAttributionInput {
  actor: string;
  root_cause: RootCause;
  evidence: string[];
  confirm_cluster: boolean;
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

export const listIssues = (status: IssueStatus) => request<IssueListResponse>(`/api/issues?status=${status}`);
export const getIssueDetail = (id: string) => request<IssueDetail>(`/api/issues/${id}`);
export const generateIssueAttribution = (id: string) => request<AttributionSuggestion>(`/api/badcases/${id}/attribution`, { method: "POST" });
export const confirmIssueAttribution = (id: string, input: ConfirmAttributionInput) => request<{ id: string | null; type: string | null }>(`/api/badcases/${id}/confirm-attribution`, { method: "POST", body: JSON.stringify(input) });
