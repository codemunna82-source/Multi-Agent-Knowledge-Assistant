export type Role = "user" | "manager" | "admin";
export interface User { id: string; tenant_id: string; email: string; role: Role; is_active?: boolean }
export interface TokenResponse { access_token: string; expires_in: number; user: User; refresh_token?: string }
export interface Health { status: string; version: string; embedder: string; llm: string; vector_store: string; auth_enabled: boolean; usage?: { ingested: number; failed: number; questions: number; llm_calls: number } }

export interface Classification { label: string; confidence: number; method: string; runner_up?: string | null }
export interface SourceInfo {
  id: string; name: string; kind: string; status: string; created_at: string; size_bytes?: number | null; title?: string | null;
  units?: number | null; chunks?: number | null; pages?: number | null; tabular: boolean; warnings: string[]; needs_reindex: boolean;
  owner_id?: string | null; visibility: "tenant" | "private" | "restricted"; url?: string | null;
  doc_key?: string; version?: number; is_current?: boolean; classification?: Classification | null; language?: string | null; content_hash?: string | null;
  tables?: { sheet: string | null; columns: string[]; rows: number }[];
}
export interface Paged<T> { items: T[]; total: number }
export interface IngestResult { status: string; name: string; source?: SourceInfo | null; error?: string | null; duplicate_of?: string | null }
export interface QueuedItem { name: string; job_id: string | null; status: string; error: string | null; duplicate_of?: string | null }
export interface Job { id: string; name: string; kind: string; status: "queued" | "running" | "ready" | "failed" | "duplicate"; stage?: string | null; progress: number; attempts: number; error?: string | null; source_id?: string | null }
export interface Sharing { visibility: string; users: string[]; roles: string[] }
export interface TimelineEvent { date: string; event: string; location: string; precision?: string; ambiguous?: boolean }

export interface Citation { source_id: string; source: string; location: string; excerpt: string; score?: number | null; loc?: Record<string, unknown> | null; version?: number | null; origin?: "document" | "web" }
export interface ChartSpec { type: "bar" | "line"; title: string; x_label: string; y_label: string; labels: string[]; series: { name: string; values: (number | null)[] }[]; truncated?: boolean }
export interface AskResponse {
  answer: string; route: string; confidence: "high" | "medium" | "low" | "none"; verified: boolean; citations: Citation[]; limitations: string[];
  needs_input: boolean; details: Record<string, unknown> & { chart?: ChartSpec; branches?: { route: string; question: string; answer: string }[]; citation_check?: { accuracy: number | null; invalid: unknown[] } };
  request_id?: string; conversation_id?: string | null; followups: string[]; language?: string;
  usage: { llm_calls?: number; prompt_tokens?: number; completion_tokens?: number; embed_tokens?: number; cost_usd?: number }; latency_ms?: number;
}
export interface RetrievalOptions {
  mode?: "semantic" | "keyword" | "hybrid"; top_k?: number; rewrite?: boolean; multi_query?: boolean; hyde?: boolean; parent_child?: boolean; compression?: boolean;
  reranker?: "none" | "lexical" | "llm" | "cross_encoder"; corrective?: boolean; graph?: boolean; self_rag?: boolean; auto?: boolean;
  filters?: { kinds?: string[]; name_contains?: string; page_min?: number; page_max?: number; sheet?: string; section_contains?: string };
}
export interface AskBody { question: string; source_ids?: string[]; conversation_id?: string; case_sensitive?: boolean; whole_word?: boolean; retrieval?: RetrievalOptions; incognito?: boolean }
export interface Conversation { id: string; workspace: string; title: string; updated_at: string; memory_enabled?: boolean }
export interface Message { id: number; role: "user" | "assistant"; content: string; meta?: Partial<AskResponse> | null; created_at: string }
export type StreamEvent =
  | { type: "step"; node: string; detail: string }
  | { type: "token"; text: string }
  | { type: "draft"; text: string }
  | { type: "draft_reset" }
  | { type: "final"; response: AskResponse }
  | { type: "error"; detail: string };

export interface ExactMatch { source_id: string; source: string; location: string; loc: Record<string, unknown>; excerpt: string }
export interface ExactResult {
  term: string; count: number; locations_with_match: number; by_source: { name: string; count: number }[]; pages: Record<string, number[]>; matches: ExactMatch[];
  limit: number; offset: number; rules: string; sources_searched: number;
}
export interface DiffItem { text: string; loc: Record<string, unknown> }
export interface DiffResult {
  summary: { segments_a: number; segments_b: number; unchanged: number; changed: number; added: number; removed: number; similarity: number };
  changed: { before: DiffItem; after: DiffItem; similarity: number; number_changes: { from: string; to: string }[] }[]; added: DiffItem[]; removed: DiffItem[]; truncated: boolean;
}
export interface Contradiction { type: string; overlap: number; verdict: string; reason?: string; a: { source: string; text: string; location?: string }; b: { source: string; text: string; location?: string } }
export interface ContradictionResult { method: string; contradictions: Contradiction[]; candidates_examined: number; note: string }
export interface SummarySection { title: string; pages: number[] | null; location: string; summary: string }
export interface SummaryOut { source_id: string; source: string; style: string; summary: string; sections: SummarySection[]; method: string }

export interface SqlTable { table: string; source: string; sheet: string | null; rows: number; columns: { name: string; original: string; type: string }[] }
export interface ColumnProfile { name: string; type: string; missing: number; missing_pct: number; unique: number; min?: number; max?: number; mean?: number; median?: number; top_values?: { value: string; count: number }[] }
export interface Profile { rows: number; columns: ColumnProfile[]; duplicate_rows: number; duplicate_row_numbers: number[] }
export interface Anomalies { column: string; method: string; count: number; rows: { row: number; value: number; score: number; values?: Record<string, unknown> }[]; bounds: { low: number; high: number } | null; note?: string }
export interface Trend {
  periods: { period: string; value: number; change_pct: number | null }[]; yoy: { period: string; vs: string; change: number; change_pct: number | null }[]; direction: string;
  best: { period: string; value: number }; worst: { period: string; value: number }; total_change_pct: number | null; chart: ChartSpec;
}
export interface SqlResult { sql: string; columns: string[]; rows: unknown[][]; row_count: number; truncated: boolean }

export interface ReportItem { id: string; kind: string; format: "pdf" | "docx" | "xlsx"; title: string; status: string; size_bytes: number | null; created_at: string; workspace: string; owner_id: string; download_url: string }
export interface MemoryPrefs { memory_enabled: boolean; long_term_memory: boolean }
export interface MemoryFact { id: number; text: string; created_at: string }
export interface TenantSettings {
  retention_days_documents: number | null; retention_days_conversations: number | null; retention_days_audit: number | null; retention_days_reports: number | null;
  web_allowed: boolean; web_allowed_domains: string[]; redact_stored_messages: boolean;
}

export interface AuditEvent { id: number; ts: string; user_id: string | null; action: string; resource: string | null; outcome: string; ip: string | null; request_id: string | null; detail: Record<string, unknown> | null }
export interface EvalSummary { id: string; name: string; created_at: string; embedder?: string; llm?: string; cases?: number; "recall@5"?: number | null; mrr?: number | null; latency_p50?: number | null; cost_per_query?: number | null }
export interface EvalMetrics {
  cases: number;
  retrieval: Record<string, number | null>;
  answers: Record<string, number | null>;
  latency_ms: Record<string, number | null>;
  tokens: { prompt: number; completion: number; embedding: number; per_query: number; estimated: boolean };
  cost_usd: { total: number; per_query: number };
  agents?: { execution_success_rate: number | null; cases_with_agent_failure: number; verified_rate: number | null; tool_calls: number; failed_tool_calls: number; failed_tool_call_rate: number | null; cases_with_invalid_citations: number };
  by_type: Record<string, { cases: number; correct: number | null; "recall@5": number | null; mrr: number | null; route_accuracy: number | null; latency_p50_ms: number | null }>;
}
export interface EvalReport {
  id: string; name: string; dataset: string; created: string; duration_s: number; config: { embedder: string; llm: string; vector_store: string };
  metrics: EvalMetrics; failures: { id: string; question: string; why: string[] }[]; notes: string[];
  comparison?: { strategy: string; "recall@5": number | null; "precision@5": number | null; mrr: number | null; "ndcg@5": number | null; p50_ms: number | null; p95_ms: number | null; cost_per_query: number }[];
  cases: { id: string; type: string; question: string; route: string; verified: boolean; latency_ms: number; "recall@5"?: number | null; mrr?: number | null }[];
}

export interface Lesson { id: string; group: "RAG" | "LangGraph" | "LangChain"; title: string; what: string; why: string; code: string; try: { lab: string; preset?: string }; needs_llm?: boolean }
export interface DemoQuestion { q: string; teaches: string }
export interface LessonsOut { lessons: Lesson[]; presets: string[]; ablation: string[]; llm_available: boolean; embedder: string; demo_questions: DemoQuestion[]; note: string }
export interface LabHit { rank: number; chunk_id: string; source: string; location: string; score: number; lexical: number; fused: number; rerank: number | null; chars_matched: number; chars_to_model: number; compressed: boolean; excerpt: string }
export interface LabRow {
  name: string; overrides: Record<string, unknown>; grade: "correct" | "ambiguous" | "incorrect"; abstained: boolean; query_used: string; attempts: number; ms: number; hits: LabHit[]; trace: Record<string, unknown>[]; notes: string[];
  delta: null | { vs: string; overlap: number; new: string[]; dropped: string[]; same_top1: boolean; grade_changed: string | null; ms_change: number; chars_to_model_change: number };
}
export interface GraphInfo { nodes: { id: string; description: string }[]; edges: { source: string; target: string; conditional: boolean }[]; mermaid: string }
export interface GraphStep { node: string; ms: number; writes: string[]; summary: Record<string, unknown> }
export interface GraphRun { steps: GraphStep[]; checkpoints: { step: number | null; next: string[]; writes: string[] }[]; response: AskResponse | null }
export interface LcDemo {
  llm_used: boolean; code: Record<string, string>;
  retriever: { documents: { source: string; location: string; score: number; text: string }[] };
  chain: { answer: string; prompt: string; steps: { kind: string; name: string; input: string; output: string; ms: number }[] };
  tool: { term: string; schema: Record<string, unknown>; result: string; invalid_call_rejected: string };
  parser: { format_instructions: string; parsed: Record<string, unknown>; malformed_output_error: string };
  memory: { messages: { type: string; content: string }[]; kept_by_window: { type: string; content: string }[] };
}
