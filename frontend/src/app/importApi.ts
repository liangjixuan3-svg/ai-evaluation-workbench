export type MessageMode = "messages" | "qa_pair";

export interface ImportMapping {
  record_path: string;
  occurred_at_path: string;
  message_mode: MessageMode;
  id_path?: string | null;
  scenario_path?: string | null;
  status_path?: string | null;
  messages_path?: string | null;
  role_path?: string | null;
  content_path?: string | null;
  question_path?: string | null;
  answer_path?: string | null;
}

export interface ImportCandidate {
  path: string;
  length: number;
  object_ratio: number;
  sample: Record<string, unknown>[];
  suggested_mapping: ImportMapping;
}

export interface UploadedImport {
  id: string;
  filename: string;
  status: string;
  record_count: number;
  candidates: ImportCandidate[];
}

export interface ImportPreview {
  valid_count: number;
  error_count: number;
  errors: Array<{ row_index: number; message: string }>;
  items: Array<{
    external_id: string;
    scenario: string | null;
    status: string | null;
    occurred_at: string;
    redacted_messages: Array<{ role: string; content: string }>;
  }>;
}

export interface ConfirmedImport {
  id: string;
  filename: string;
  source_id: string;
  available_count: number;
  confirmed_at: string;
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

export function uploadJson(filename: string, document: unknown) {
  return request<UploadedImport>("/api/imports/json", {
    method: "POST",
    body: JSON.stringify({ filename, document }),
  });
}

export function previewImport(importId: string, mapping: ImportMapping) {
  return request<ImportPreview>(`/api/imports/${importId}/preview`, {
    method: "POST",
    body: JSON.stringify({ mapping, timezone_name: "Asia/Shanghai", error_policy: "block" }),
  });
}

export function confirmImport(importId: string, sourceName: string) {
  return request<{ imported_count?: number; inserted: number; available_count: number }>(
    `/api/imports/${importId}/confirm`,
    { method: "POST", body: JSON.stringify({ source_name: sourceName, actor: "operator" }) },
  );
}

export function getConfirmedImports() {
  return request<ConfirmedImport[]>("/api/imports?status=confirmed");
}
