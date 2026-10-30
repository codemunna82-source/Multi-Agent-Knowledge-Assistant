export type Role = "viewer" | "editor" | "admin";
export interface User { id: string; tenant_id: string; email: string; role: Role; is_active?: boolean }
export interface TokenResponse { access_token: string; expires_in: number; user: User }
export interface Health { status: string; version: string; embedder: string; llm: string; vector_store: string; auth_enabled: boolean }

export interface SourceInfo {
  id: string; name: string; kind: string; status: string; created_at: string; size_bytes?: number | null; title?: string | null;
  units?: number | null; chunks?: number | null; pages?: number | null; tabular: boolean; warnings: string[]; needs_reindex: boolean;
  owner_id?: string | null; visibility: "tenant" | "private"; url?: string | null;
}
export interface IngestResult { status: string; name: string; source?: SourceInfo | null; error?: string | null }
export interface QueuedItem { name: string; job_id: string | null; status: string; error: string | null }
export interface Job { id: string; name: string; kind: string; status: "queued" | "running" | "ready" | "failed"; stage?: string | null; progress: number; attempts: number; error?: string | null; source_id?: string | null }

export interface Citation { source_id: string; source: string; location: string; excerpt: string; score?: number | null }
export interface AskResponse {
  answer: string; route: string; confidence: "high" | "medium" | "low" | "none"; verified: boolean; citations: Citation[]; limitations: string[];
  needs_input: boolean; details: Record<string, unknown>; request_id?: string; conversation_id?: string; followups: string[]; language?: string;
  usage: { llm_calls?: number; prompt_tokens?: number; completion_tokens?: number; embed_tokens?: number; cost_usd?: number }; latency_ms?: number;
}
export interface RetrievalOptions {
  mode?: "semantic" | "keyword" | "hybrid"; top_k?: number; rewrite?: boolean; multi_query?: boolean; hyde?: boolean; parent_child?: boolean; compression?: boolean;
  reranker?: "none" | "lexical" | "llm" | "cross_encoder"; corrective?: boolean; graph?: boolean;
  filters?: { kinds?: string[]; name_contains?: string; page_min?: number; page_max?: number; sheet?: string; section_contains?: string };
}
export interface AskBody { question: string; source_ids?: string[]; conversation_id?: string; case_sensitive?: boolean; whole_word?: boolean; retrieval?: RetrievalOptions }
export interface Conversation { id: string; workspace: string; title: string; updated_at: string }
export interface Message { id: number; role: "user" | "assistant"; content: string; meta?: Partial<AskResponse> | null; created_at: string }
export type StreamEvent =
  | { type: "step"; node: string; detail: string }
  | { type: "token"; text: string }
  | { type: "final"; response: AskResponse }
  | { type: "error"; detail: string };

export interface AuditEvent { id: number; ts: string; user_id: string | null; action: string; resource: string | null; outcome: string; ip: string | null; request_id: string | null; detail: Record<string, unknown> | null }
export interface EvalSummary { id: string; name: string; created_at: string; embedder?: string; llm?: string; cases?: number; "recall@5"?: number | null; mrr?: number | null; latency_p50?: number | null; cost_per_query?: number | null }
export interface EvalMetrics {
  cases: number;
  retrieval: Record<string, number | null>;
  answers: Record<string, number | null>;
  latency_ms: Record<string, number | null>;
  tokens: { prompt: number; completion: number; embedding: number; per_query: number; estimated: boolean };
  cost_usd: { total: number; per_query: number };
  by_type: Record<string, { cases: number; correct: number | null; "recall@5": number | null; mrr: number | null; route_accuracy: number | null; latency_p50_ms: number | null }>;
}
export interface EvalReport {
  id: string; name: string; dataset: string; created: string; duration_s: number; config: { embedder: string; llm: string; vector_store: string };
  metrics: EvalMetrics; failures: { id: string; question: string; why: string[] }[]; notes: string[];
  comparison?: { strategy: string; "recall@5": number | null; "precision@5": number | null; mrr: number | null; "ndcg@5": number | null; p50_ms: number | null; p95_ms: number | null; cost_per_query: number }[];
  cases: { id: string; type: string; question: string; route: string; verified: boolean; latency_ms: number; "recall@5"?: number | null; mrr?: number | null }[];
}
