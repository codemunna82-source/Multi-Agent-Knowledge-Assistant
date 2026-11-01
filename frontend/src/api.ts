import type { Insights,
  Anomalies, AskBody, GraphInfo, GraphRun, LabRow, LcDemo, LessonsOut, RetrievalOptions, AskResponse, AuditEvent, ChartSpec, Conversation, ContradictionResult, DiffResult, EvalReport, EvalSummary, ExactResult, Health, IngestResult, Job, MemoryFact,
  MemoryPrefs, Message, Paged, Profile, QueuedItem, ReportItem, Sharing, SourceInfo, SqlResult, SqlTable, StreamEvent, SummaryOut, TenantSettings, TimelineEvent, TokenResponse, Trend, User,
} from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

// The access token lives in memory only (never in web storage). A page reload gets a new one from the httpOnly refresh cookie.
let token: string | null = null;
export function setToken(t: string | null) { token = t; }
export const hasToken = () => token !== null;

function headers(workspace: string, extra: Record<string, string> = {}): Record<string, string> {
  return { "X-Session-ID": workspace, ...(token ? { Authorization: `Bearer ${token}` } : {}), ...extra };
}

async function parse(r: Response): Promise<unknown> {
  const text = await r.text();
  try { return text ? JSON.parse(text) : null; } catch { return text; }
}

function errMessage(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d) && d[0] && typeof d[0] === "object" && "msg" in d[0]) return String((d[0] as { msg: unknown }).msg);
  }
  return typeof body === "string" && body ? body.slice(0, 200) : `Request failed (${status})`;
}

let refreshing: Promise<TokenResponse | null> | null = null;
async function doRefresh(optional: boolean): Promise<TokenResponse | null> {
  try {
    const r = await fetch(`/auth/refresh${optional ? "?optional=true" : ""}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    if (!r.ok) return null;
    const t = (await r.json()) as Partial<TokenResponse>;
    if (!t.access_token) return null;       // {"authenticated": false}: signed out, nothing to refresh
    setToken(t.access_token);
    return t as TokenResponse;
  } catch { return null; }
}
/** Exchange the httpOnly refresh cookie for a new access token (rotating refresh token). Concurrent callers share one request. */
export function silentRefresh(optional = false): Promise<TokenResponse | null> {
  refreshing ??= doRefresh(optional).finally(() => { refreshing = null; });
  return refreshing;
}

type Opts = { method?: string; body?: unknown; form?: FormData; workspace?: string };
async function raw(path: string, o: Opts = {}, retry = true): Promise<Response> {
  const ws = o.workspace ?? "default";
  const init: RequestInit = { method: o.method ?? "GET", headers: headers(ws, o.body !== undefined ? { "Content-Type": "application/json" } : {}) };
  if (o.body !== undefined) init.body = JSON.stringify(o.body);
  if (o.form) init.body = o.form;
  const r = await fetch(path, init);
  if (r.status === 401 && retry && token !== null && !path.startsWith("/auth/")) {
    if (await silentRefresh()) return raw(path, o, false);
    setToken(null);
  }
  if (!r.ok) throw new ApiError(r.status, errMessage(await parse(r), r.status));
  return r;
}
async function req<T>(path: string, o: Opts = {}): Promise<T> { return (await parse(await raw(path, o))) as T; }
async function reqPage<T>(path: string, o: Opts = {}): Promise<Paged<T>> {
  const r = await raw(path, o);
  const items = (await parse(r)) as T[];
  return { items, total: Number(r.headers.get("X-Total-Count") ?? items.length) };
}
async function blob(path: string, o: Opts = {}): Promise<Blob> { return (await raw(path, o)).blob(); }
const qs = (p: Record<string, string | number | boolean | undefined | null>) => {
  const e = Object.entries(p).filter(([, v]) => v !== undefined && v !== null && v !== "");
  return e.length ? "?" + e.map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join("&") : "";
};

export const api = {
  health: () => req<Health>("/health"),
  signup: (tenant_name: string, email: string, password: string) => req<TokenResponse>("/auth/signup", { method: "POST", body: { tenant_name, email, password } }),
  login: (email: string, password: string, otp?: string) => req<TokenResponse>("/auth/login", { method: "POST", body: { email, password, ...(otp ? { otp } : {}) } }),
  oidcConfig: () => req<{ enabled: boolean; login_url: string | null }>("/auth/oidc/config"),
  mfaStatus: () => req<{ enabled: boolean; recovery_codes_left: number }>("/auth/mfa"),
  mfaSetup: () => req<{ secret: string; otpauth_uri: string }>("/auth/mfa/setup", { method: "POST" }),
  mfaEnable: (code: string) => req<{ enabled: boolean; recovery_codes: string[] }>("/auth/mfa/enable", { method: "POST", body: { code } }),
  mfaDisable: (password: string, code: string) => req<{ enabled: boolean }>("/auth/mfa/disable", { method: "POST", body: { password, code } }),
  me: () => req<User>("/auth/me"),
  logout: () => req<{ logged_out: boolean }>("/auth/logout", { method: "POST" }),

  sources: (ws: string, p: { q?: string; kind?: string; include_versions?: boolean; limit?: number; offset?: number } = {}) => reqPage<SourceInfo>(`/sources${qs({ limit: 200, ...p })}`, { workspace: ws }),
  source: (ws: string, id: string) => req<SourceInfo>(`/sources/${id}`, { workspace: ws }),
  uploadFiles: (ws: string, files: File[], visibility: string, allowDuplicate = false) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    form.append("visibility", visibility);
    if (allowDuplicate) form.append("allow_duplicate", "true");
    return req<QueuedItem[]>("/sources/upload?async=true", { method: "POST", form, workspace: ws });
  },
  addUrl: (ws: string, url: string, visibility: string) => req<QueuedItem[]>(`/sources/url?async=true&visibility=${visibility}`, { method: "POST", body: { url }, workspace: ws }),
  jobs: (ws: string) => reqPage<Job>("/jobs?limit=50", { workspace: ws }),
  job: (ws: string, id: string) => req<Job>(`/jobs/${id}`, { workspace: ws }),
  deleteSource: (ws: string, id: string, allVersions = false) => req<{ deleted: string }>(`/sources/${id}${qs({ all_versions: allVersions || undefined })}`, { method: "DELETE", workspace: ws }),
  reindex: (ws: string, id: string) => req<IngestResult>(`/sources/${id}/reindex`, { method: "POST", workspace: ws }),
  versions: (ws: string, id: string) => req<SourceInfo[]>(`/sources/${id}/versions`, { workspace: ws }),
  makeCurrent: (ws: string, id: string) => req<SourceInfo>(`/sources/${id}/make-current`, { method: "POST", workspace: ws }),
  sharing: (ws: string, id: string) => req<Sharing>(`/sources/${id}/sharing`, { workspace: ws }),
  setSharing: (ws: string, id: string, body: Sharing) => req<Sharing>(`/sources/${id}/sharing`, { method: "PUT", body, workspace: ws }),
  timeline: (ws: string, id: string) => req<{ events: TimelineEvent[] }>(`/sources/${id}/timeline`, { workspace: ws }),
  entities: (ws: string, id: string) => req<{ method: string; entities: Record<string, { value: string; count: number }[]> }>(`/sources/${id}/entities`, { workspace: ws }),
  questions: (ws: string, id: string) => req<{ method: string; questions: string[] }>(`/sources/${id}/questions`, { workspace: ws }),
  passage: (ws: string, id: string, loc: Record<string, unknown>) => req<{ source: string; location: string; text: string; before?: string | null; after?: string | null; kind: string }>(`/sources/${id}/passage${qs(loc as Record<string, string | number>)}`, { workspace: ws }),
  pageImage: (ws: string, id: string, page: number, highlight?: string) => blob(`/sources/${id}/pages/${page}/image${qs({ highlight: highlight?.slice(0, 200) })}`, { workspace: ws }),
  changes: (ws: string, id: string, against?: string) => req<DiffResult & { document: string; from_version: number; to_version: number }>(`/sources/${id}/changes${qs({ against })}`, { workspace: ws }),

  ask: (ws: string, body: AskBody) => req<AskResponse>("/ask", { method: "POST", body, workspace: ws }),
  conversations: (ws: string) => reqPage<Conversation>("/conversations?limit=200", { workspace: ws }),
  newConversation: (ws: string) => req<Conversation>("/conversations", { method: "POST", workspace: ws }),
  patchConversation: (ws: string, id: string, body: { title?: string; memory_enabled?: boolean }) => req<Conversation>(`/conversations/${id}`, { method: "PATCH", body, workspace: ws }),
  messages: (ws: string, id: string) => req<Message[]>(`/conversations/${id}/messages`, { workspace: ws }),
  deleteConversation: (ws: string, id: string) => req<{ deleted: string }>(`/conversations/${id}`, { method: "DELETE", workspace: ws }),
  transcribe: (ws: string, b: Blob) => {
    const form = new FormData();
    form.append("audio", b, "voice.webm");
    return req<{ text: string }>("/transcribe", { method: "POST", form, workspace: ws });
  },

  exact: (ws: string, body: { term: string; source_ids?: string[]; case_sensitive: boolean; whole_word: boolean }, limit: number, offset: number) =>
    req<ExactResult>(`/search/exact${qs({ limit, offset })}`, { method: "POST", body, workspace: ws }),
  summaries: (ws: string, body: { source_ids: string[]; style: string; section?: string }) => req<{ summaries: SummaryOut[]; llm: boolean }>("/summaries", { method: "POST", body, workspace: ws }),
  compare: (ws: string, body: { source_ids: string[]; mode: "diff" | "contradictions" }) => req<(DiffResult & { left: { name: string }; right: { name: string } }) | ContradictionResult>("/compare", { method: "POST", body, workspace: ws }),
  webResearch: (ws: string, query: string) => req<AskResponse>("/web/research", { method: "POST", body: { query }, workspace: ws }),

  analyticsTables: (ws: string) => req<{ tables: SqlTable[] }>("/analytics/tables", { workspace: ws }),
  profile: (ws: string, id: string, sheet?: string | null) => req<Profile>(`/analytics/profile${qs({ source_id: id, sheet })}`, { workspace: ws }),
  anomalies: (ws: string, id: string, column: string, method: string, sheet?: string | null) => req<Anomalies>(`/analytics/anomalies${qs({ source_id: id, column, method, sheet })}`, { workspace: ws }),
  trend: (ws: string, id: string, p: { date_column: string; value_column?: string; freq: string; agg: string; sheet?: string | null }) => req<Trend>(`/analytics/trend${qs({ source_id: id, ...p })}`, { workspace: ws }),
  sql: (ws: string, sql: string, source_ids?: string[]) => req<SqlResult>("/analytics/sql", { method: "POST", body: { sql, source_ids, max_rows: 200 }, workspace: ws }),
  analyticsAsk: (ws: string, question: string, source_ids?: string[]) => req<AskResponse>("/analytics/ask", { method: "POST", body: { question, source_ids }, workspace: ws }),
  chartPng: (ws: string, spec: ChartSpec) => blob("/analytics/chart", { method: "POST", body: spec, workspace: ws }),

  reports: (ws: string) => reqPage<ReportItem>("/reports?limit=100", { workspace: ws }),
  createReport: (ws: string, body: { kind: string; format: string; source_ids?: string[]; params?: Record<string, unknown>; title?: string }) => req<ReportItem>("/reports", { method: "POST", body, workspace: ws }),
  downloadReport: (ws: string, id: string) => blob(`/reports/${id}/download`, { workspace: ws }),
  deleteReport: (ws: string, id: string) => req<{ deleted: string }>(`/reports/${id}`, { method: "DELETE", workspace: ws }),

  sendFeedback: (ws: string, body: { rating: 1 | -1; route?: string; question?: string; answer?: string; comment?: string; expected?: string; sources?: { source: string; location: string }[] }) =>
    req<{ id: string }>("/feedback", { method: "POST", body, workspace: ws }),
  feedbackSummary: () => req<{ by_route: Record<string, { up: number; down: number }>; up: number; down: number }>("/feedback/summary"),
  feedbackDataset: (ws: string) => req<{ name: string; cases: unknown[] }>("/feedback/eval-dataset", { workspace: ws }),
  runEvalDataset: (ws: string, dataset: unknown, name: string) => req<EvalReport>("/eval/run", { method: "POST", body: { dataset, name, use_llm_judge: false }, workspace: ws }),
  savedSearches: () => req<{ id: string; term: string; whole_word: boolean; webhook_url: string | null }[]>("/saved-searches"),
  addSavedSearch: (ws: string, body: { term: string; webhook_url?: string }) => req<{ id: string }>("/saved-searches", { method: "POST", body, workspace: ws }),
  deleteSavedSearch: (id: string) => req<{ deleted: string }>(`/saved-searches/${id}`, { method: "DELETE" }),
  alerts: (ws: string, unseen = false) => reqPage<{ id: string; term: string; source_name: string; count: number; locations: string[]; seen: boolean; created_at: string }>(`/alerts${qs({ unseen: unseen || undefined, limit: 100 })}`, { workspace: ws }),
  alertsSeen: () => req<{ marked: number }>("/alerts/seen", { method: "POST" }),
  schedules: (ws: string) => req<{ id: string; name: string; spec: { kind: string; format: string }; every_hours: number; enabled: boolean; last_run_at: string | null; last_status: string | null; webhook_url: string | null }[]>("/report-schedules", { workspace: ws }),
  addSchedule: (ws: string, body: { name: string; kind: string; format: string; every_hours: number; webhook_url?: string; params?: Record<string, unknown> }) => req<{ id: string }>("/report-schedules", { method: "POST", body, workspace: ws }),
  runSchedule: (ws: string, id: string) => req<{ status: string }>(`/report-schedules/${id}/run`, { method: "POST", workspace: ws }),
  toggleSchedule: (ws: string, id: string, enabled: boolean) => req<{ id: string }>(`/report-schedules/${id}?enabled=${enabled}`, { method: "PATCH", workspace: ws }),
  deleteSchedule: (id: string) => req<{ deleted: string }>(`/report-schedules/${id}`, { method: "DELETE" }),
  connectors: (ws: string) => req<{ id: string; name: string; kind: string; config: Record<string, unknown>; every_hours: number; last_run_at: string | null; last_result: { ready: number; duplicate: number; failed: number; errors: string[] } | null }[]>("/connectors", { workspace: ws }),
  addConnector: (ws: string, body: { name: string; kind: string; config: Record<string, unknown>; every_hours: number }) => req<{ id: string }>("/connectors", { method: "POST", body, workspace: ws }),
  syncConnector: (ws: string, id: string) => req<{ ready: number; duplicate: number; failed: number; seen: number; errors: string[] }>(`/connectors/${id}/sync`, { method: "POST", workspace: ws }),
  deleteConnector: (id: string) => req<{ deleted: string }>(`/connectors/${id}`, { method: "DELETE" }),
  annotations: (ws: string, sourceId: string) => req<{ id: string; loc: Record<string, unknown>; quote: string | null; note: string; kind: string; shared: boolean; mine: boolean }[]>(`/annotations${qs({ source_id: sourceId })}`, { workspace: ws }),
  addAnnotation: (ws: string, body: { source_id: string; loc: Record<string, unknown>; quote?: string; note: string; kind: string; shared: boolean }) => req<{ id: string }>("/annotations", { method: "POST", body, workspace: ws }),
  deleteAnnotation: (id: string) => req<{ deleted: string }>(`/annotations/${id}`, { method: "DELETE" }),
  learnChunking: (ws: string, source_id: string) => req<{ source: string; units: number; reading: string; rows: { size: number; overlap: number; structure?: boolean; chunks: number; avg_chars: number; min_chars: number; max_chars: number; tiny_chunks: number; samples: { location: string; chars: number; text: string }[] }[] }>("/learn/chunking", { method: "POST", body: { source_id }, workspace: ws }),
  learnLessons: () => req<LessonsOut>("/learn/lessons"),
  learnDemoCorpus: (ws: string) => req<{ documents: { name: string; status: string }[] }>("/learn/demo-corpus", { method: "POST", workspace: ws }),
  learnCompare: (ws: string, question: string, presets?: string[]) => req<{ rows: LabRow[] }>("/learn/retrieval/compare", { method: "POST", body: { question, presets }, workspace: ws }),
  learnAblation: (ws: string, question: string) => req<{ rows: LabRow[] }>("/learn/retrieval/ablation", { method: "POST", body: { question }, workspace: ws }),
  learnGraph: () => req<GraphInfo>("/learn/graph"),
  learnGraphRun: (ws: string, question: string, retrieval?: RetrievalOptions) => req<GraphRun>("/learn/graph/run", { method: "POST", body: { question, retrieval }, workspace: ws }),
  learnLangchain: (ws: string, question: string) => req<LcDemo>("/learn/langchain", { method: "POST", body: { question }, workspace: ws }),

  memoryPrefs: () => req<MemoryPrefs>("/memory/preferences"),
  setMemoryPrefs: (body: Partial<MemoryPrefs>) => req<MemoryPrefs>("/memory/preferences", { method: "PUT", body }),
  facts: () => reqPage<MemoryFact>("/memory/facts?limit=100"),
  addFact: (text: string) => req<MemoryFact>("/memory/facts", { method: "POST", body: { text } }),
  deleteFact: (id: number) => req<{ deleted: number }>(`/memory/facts/${id}`, { method: "DELETE" }),
  resetMemory: (conversations: boolean) => req<{ facts_deleted: number; conversations_deleted: number; summaries_cleared: number }>(`/memory${qs({ conversations: conversations || undefined })}`, { method: "DELETE" }),

  evalRuns: () => req<EvalSummary[]>("/eval/runs"),
  evalRun: (id: string) => req<EvalReport>(`/eval/runs/${id}`),
  runEval: (body: { sample: boolean; extended?: boolean; name?: string; compare_strategies?: boolean }) => req<EvalReport>("/eval/run", { method: "POST", body }),
  evalExport: (id: string, fmt: "pdf" | "docx" | "xlsx" | "html" | "md") => blob(`/eval/runs/${id}/report.${fmt}`),

  users: () => req<User[]>("/admin/users"),
  createUser: (email: string, password: string, role: string) => req<User>("/admin/users", { method: "POST", body: { email, password, role } }),
  updateUser: (id: string, patch: { role?: string; is_active?: boolean }) => req<User>(`/admin/users/${id}`, { method: "PATCH", body: patch }),
  deleteUser: (id: string) => req<{ deleted: string }>(`/admin/users/${id}`, { method: "DELETE" }),
  insights: (days = 30) => req<Insights>(`/admin/insights${qs({ days })}`),
  audit: (action?: string) => req<AuditEvent[]>(`/admin/audit${qs({ limit: 200, action })}`),
  settings: () => req<Record<string, unknown>>("/admin/settings"),
  tenantSettings: () => req<TenantSettings>("/admin/tenant-settings"),
  setTenantSettings: (body: TenantSettings) => req<TenantSettings>("/admin/tenant-settings", { method: "PUT", body }),
  maintenance: (body: { tasks?: string[]; dry_run: boolean }) => req<{ dry_run: boolean; results: Record<string, { removed?: number; error?: string }> }>("/admin/maintenance/run", { method: "POST", body }),
  purge: () => req<{ purged: boolean; sources_removed: number }>("/admin/data", { method: "DELETE", body: { confirm: "DELETE-ALL-TENANT-DATA" } }),
};

/** Server-Sent Events over fetch (EventSource cannot send Authorization headers). */
export const academy = {
  catalog: () => req<import("./academy/types").Catalog>("/academy/catalog"),
  lesson: (id: string) => req<import("./academy/types").Lesson>(`/academy/lessons/${id}`),
  glossary: () => req<Record<string, import("./academy/types").Term>>("/academy/glossary"),
  search: (q: string) => req<(import("./academy/types").LessonCard & { glossary?: string; term?: string })[]>(`/academy/search${qs({ q })}`),
  progress: () => req<import("./academy/types").Progress>("/academy/progress"),
  setProgress: (id: string, body: { status?: "in_progress" | "done"; step?: number; bookmarked?: boolean }) => req<{ lesson: string; status: string; step: number; bookmarked: boolean }>(`/academy/progress/${id}`, { method: "PUT", body }),
  submitQuiz: (answers: Record<string, number>) => req<import("./academy/types").QuizOut>("/academy/quiz/submit", { method: "POST", body: { answers } }),
  daily: () => req<{ questions: (import("./academy/types").QuizQuestion & { lesson: string })[] }>("/academy/daily"),
  interview: (category?: string) => req<import("./academy/types").InterviewItem[]>(`/academy/interview${qs({ category })}`),
  codeStatus: () => req<import("./academy/types").CodeStatus>("/academy/code/status"),
  runCode: (body: { language: string; code: string; lesson_id?: string; task?: "scratch" | "example" | "exercise" | "debug"; example?: number }) => req<import("./academy/types").RunOut>("/academy/code/run", { method: "POST", body }),
  solution: (id: string, kind: "exercise" | "debug") => req<{ solution: string; expected_output: string }>(`/academy/lessons/${id}/solution/${kind}`),
  pgCaps: () => req<import("./academy/types").PgCaps>("/academy/playground/capabilities"),
  pgLlm: (body: import("./academy/types").LlmParams) => req<import("./academy/types").LlmRun>("/academy/playground/llm", { method: "POST", body }),
  pgCompare: (body: { variants: { name: string; system: string; prompt: string }[]; temperature: number; max_tokens: number }) => req<import("./academy/types").CompareRun>("/academy/playground/prompts/compare", { method: "POST", body }),
  pgEmbed: (texts: string[]) => req<import("./academy/types").EmbedRun>("/academy/playground/embeddings", { method: "POST", body: { texts } }),
  pgRag: (form: FormData) => req<import("./academy/types").RagRun>("/academy/playground/rag", { method: "POST", form }),
  pgLangchain: (body: unknown) => req<import("./academy/types").LcRun>("/academy/playground/langchain", { method: "POST", body }),
  pgPresets: () => req<Record<string, import("./academy/types").GraphPreset>>("/academy/playground/langgraph/presets"),
  pgGraphRun: (body: { spec: unknown; input: Record<string, unknown>; max_steps: number }) => req<import("./academy/types").GraphRun>("/academy/playground/langgraph/run", { method: "POST", body }),
  pgGraphResume: (body: { thread_id: string; state_update?: Record<string, unknown>; max_steps?: number }) => req<import("./academy/types").GraphRun>("/academy/playground/langgraph/resume", { method: "POST", body }),
  pgAgentTools: () => req<Record<string, string>>("/academy/playground/agent/tools"),
  pgAgent: (body: { task: string; tools: string[]; max_steps: number }) => req<import("./academy/types").AgentRun>("/academy/playground/agent/run", { method: "POST", body }),
  projects: () => req<import("./academy/types").ProjectCard[]>("/academy/projects"),
  project: (id: string) => req<import("./academy/types").Project>(`/academy/projects/${id}`),
  setProject: (id: string, done_steps: number[]) => req<{ done_steps: number[] }>(`/academy/projects/${id}/progress`, { method: "PUT", body: { done_steps } }),
};

/** Generic Server-Sent Events over fetch (EventSource cannot send Authorization headers). */
export async function sseFetch<T>(path: string, ws: string, body: unknown, onEvent: (e: T) => void, signal?: AbortSignal): Promise<void> {
  const r = await fetch(path, { method: "POST", headers: headers(ws, { "Content-Type": "application/json" }), body: JSON.stringify(body), signal });
  if (!r.ok || !r.body) throw new ApiError(r.status, errMessage(await parse(r), r.status));
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i: number;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, i);
      buf = buf.slice(i + 2);
      const data = block.split("\n").find((l) => l.startsWith("data:"));
      if (data) onEvent(JSON.parse(data.slice(5).trim()) as T);
    }
  }
}

export async function askStream(ws: string, body: AskBody, onEvent: (e: StreamEvent) => void, signal?: AbortSignal): Promise<void> {
  const r = await fetch("/ask/stream", { method: "POST", headers: headers(ws, { "Content-Type": "application/json" }), body: JSON.stringify(body), signal });
  if (!r.ok || !r.body) throw new ApiError(r.status, errMessage(await parse(r), r.status));
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i: number;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, i);
      buf = buf.slice(i + 2);
      const data = block.split("\n").find((l) => l.startsWith("data:"));
      if (data) onEvent(JSON.parse(data.slice(5).trim()) as StreamEvent);
    }
  }
}

/** Save a Blob as a file (reports, charts). */
export function saveBlob(b: Blob, filename: string) {
  const url = URL.createObjectURL(b);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
