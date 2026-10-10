import type { AppSettings, ChatResult, ConversationSummary, MemoryList, Mode, Msg } from "./types";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status = 0) { super(message); this.status = status; }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch {
    throw new ApiError("Can't reach the AI Memory Agent server. Is it running?");
  }
  let body: Record<string, unknown> = {};
  try { body = await res.json(); } catch { /* non-JSON error body */ }
  if (!res.ok) {
    throw new ApiError(String(body.error ?? body.message ?? res.statusText ?? "Request failed"), res.status);
  }
  return body as T;
}

const json = (method: string, data: unknown): RequestInit => ({
  method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(data),
});

export const api = {
  conversations: () => request<{ conversations: ConversationSummary[] }>("/api/conversations").then((r) => r.conversations),
  history: (id: string) =>
    request<{ messages: Msg[] }>(`/api/history?conversation_id=${encodeURIComponent(id)}`).then((r) => r.messages),
  /** Existing /api/chat contract; `conversationId` "new" starts a fresh chat. */
  chat: (message: string, conversationId: string, mode: Mode) =>
    request<ChatResult>("/api/chat", json("POST", { message, mode, conversation_id: conversationId })),
  memories: () => request<MemoryList>("/api/memories"),
  updateMemory: (id: string, text: string) =>
    request<{ message: string }>(`/api/memories/${encodeURIComponent(id)}`, json("PUT", { text })),
  deleteMemory: (id: string) =>
    request<{ message: string }>(`/api/memories/${encodeURIComponent(id)}?confirm=yes`, { method: "DELETE" }),
  settings: () => request<AppSettings>("/api/settings"),
};
