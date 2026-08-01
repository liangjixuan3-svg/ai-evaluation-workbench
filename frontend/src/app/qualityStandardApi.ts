export type Dimension = "correctness" | "completeness" | "relevance" | "service_experience" | "compliance";

export interface StandardRule {
  id: string;
  title: string;
  requirement: string;
  dimension: Dimension;
  effect: { kind: "normal" | "dimension_cap" | "veto"; dimension_cap: number | null };
  source_quote: string;
  source_locator: string;
  confidence: number;
  confirmed: boolean;
}

export interface StandardRules {
  threshold: number;
  weights: Record<Dimension, number>;
  anchors: Array<{ level: "excellent" | "good" | "acceptable" | "poor" | "unacceptable"; description: string }>;
  common_rules: StandardRule[];
  scenarios: Array<{ name: string; rules: StandardRule[] }>;
}

export interface QualityStandardSummary {
  id: string;
  name: string;
  status: "draft" | "published";
  latest_version: number;
  published_version_id: string | null;
  published_rules: StandardRules | null;
  updated_at: string;
}

export interface QualityStandard {
  id: string;
  name: string;
  status: "draft" | "published";
  updated_at: string;
  draft: { id: string; version_number: number; source_filename: string; rules: StandardRules; published_at: null } | null;
  versions: Array<{ id: string; version_number: number; source_filename: string; rules: StandardRules; published_at: string | null }>;
  parse_jobs: Array<{ id: string; status: string; error_summary: string | null; attempts: number }>;
}

export interface PublishedQualityStandardVersion {
  standard_id: string;
  standard_name: string;
  version_id: string;
  version_number: number;
  source_filename: string;
  published_at: string;
  rules: StandardRules;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { ...init, headers: { Accept: "application/json", ...init?.headers } });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `请求失败 (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export const listQualityStandards = () => request<QualityStandardSummary[]>("/api/quality-standards");
export const getQualityStandard = (id: string) => request<QualityStandard>(`/api/quality-standards/${id}`);
export const getQualityStandardVersion = (versionId: string) => request<PublishedQualityStandardVersion>(`/api/quality-standards/versions/${versionId}`);
export function uploadQualityStandard(file: File) {
  const body = new FormData();
  body.append("file", file);
  return request<QualityStandard>("/api/quality-standards", { method: "POST", body });
}
export const parseQualityStandard = (id: string) => request<QualityStandard>(`/api/quality-standards/${id}/parse`, { method: "POST" });
export const saveQualityStandard = (id: string, rules: StandardRules) => request<QualityStandard>(`/api/quality-standards/${id}/draft`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(rules) });
export const publishQualityStandard = (id: string) => request<QualityStandard>(`/api/quality-standards/${id}/publish`, { method: "POST" });
