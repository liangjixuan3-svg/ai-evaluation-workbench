export interface EvaluationPromptVersion {
  id: string;
  name: string;
  version: string;
  content: string;
  active: boolean;
  published_at: string | null;
  created_at: string;
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
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const listEvaluationPrompts = () => request<EvaluationPromptVersion[]>("/api/evaluation-prompts");
export const copyEvaluationPrompt = (sourceId: string) => request<EvaluationPromptVersion>("/api/evaluation-prompts/drafts", { method: "POST", body: JSON.stringify({ source_id: sourceId }) });
export const saveEvaluationPrompt = (id: string, content: string) => request<EvaluationPromptVersion>(`/api/evaluation-prompts/${id}`, { method: "PUT", body: JSON.stringify({ content }) });
export const publishEvaluationPrompt = (id: string) => request<EvaluationPromptVersion>(`/api/evaluation-prompts/${id}/publish`, { method: "POST" });
export const deleteEvaluationPrompt = (id: string) => request<void>(`/api/evaluation-prompts/${id}`, { method: "DELETE" });
