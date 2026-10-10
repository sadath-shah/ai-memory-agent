export type Role = "user" | "assistant";
export type Mode = "agent" | "memory" | "tools";
export type View = "chat" | "memories" | "settings";

export interface Msg { role: Role; content: string }
export interface ConversationSummary { id: string; title: string; updated_at: string; message_count: number }
export interface Memory { id: string; memory: string; created_at: string; updated_at: string }
export interface MemoryList { count: number; memories: Memory[]; user_id: string }
export interface ChatResult { reply: string; action: string; conversation_id: string | null }
export interface AppSettings { chat_model: string; embed_model: string; user_id: string; local: boolean; telemetry: boolean }
