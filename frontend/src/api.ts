import type { AskBody, AskResponse, AuditEvent, Conversation, EvalReport, EvalSummary, Health, IngestResult, Job, Message, QueuedItem, SourceInfo, StreamEvent, TokenResponse, User } from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

const TOKEN_KEY = "mka_token";
let token: string | null = null;
try { token = sessionStorage.getItem(TOKEN_KEY); } catch { /* storage may be unavailable */ }

export function setToken(t: string | null) {
  token = t;
  try { t ? sessionStorage.setItem(TOKEN_KEY, t) : sessionStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ }
}
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

type Opts = { method?: string; body?: unknown; form?: FormData; workspace?: string };
async function req<T>(path: string, o: Opts = {}): Promise<T> {
  const ws = o.workspace ?? "default";
  const init: RequestInit = { method: o.method ?? "GET", headers: headers(ws, o.body !== undefined ? { "Content-Type": "application/json" } : {}) };
  if (o.body !== undefined) init.body = JSON.stringify(o.body);
  if (o.form) init.body = o.form;
  const r = await fetch(path, init);
  const body = await parse(r);
  if (!r.ok) {
    if (r.status === 401) setToken(null);
    throw new ApiError(r.status, errMessage(body, r.status));
  }
  return body as T;
}

export const api = {
  health: () => req<Health>("/health"),
  signup: (tenant_name: string, email: string, password: string) => req<TokenResponse>("/auth/signup", { method: "POST", body: { tenant_name, email, password } }),
  login: (email: string, password: string) => req<TokenResponse>("/auth/login", { method: "POST", body: { email, password } }),
  me: () => req<User>("/auth/me"),
  logout: () => req<{ logged_out: boolean }>("/auth/logout", { method: "POST" }),

  sources: (ws: string) => req<SourceInfo[]>("/sources", { workspace: ws }),
  uploadFiles: (ws: string, files: File[], visibility: string) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    form.append("visibility", visibility);
    return req<QueuedItem[]>("/sources/upload?async=true", { method: "POST", form, workspace: ws });
  },
  addUrl: (ws: string, url: string, visibility: string) => req<QueuedItem[]>(`/sources/url?async=true&visibility=${visibility}`, { method: "POST", body: { url }, workspace: ws }),
  job: (ws: string, id: string) => req<Job>(`/jobs/${id}`, { workspace: ws }),
  deleteSource: (ws: string, id: string) => req<{ deleted: string }>(`/sources/${id}`, { method: "DELETE", workspace: ws }),
  reindex: (ws: string, id: string) => req<IngestResult>(`/sources/${id}/reindex`, { method: "POST", workspace: ws }),
  entities: (ws: string, id: string) => req<{ method: string; entities: Record<string, { value: string; count: number }[]> }>(`/sources/${id}/entities`, { workspace: ws }),
  questions: (ws: string, id: string) => req<{ method: string; questions: string[] }>(`/sources/${id}/questions`, { workspace: ws }),

  ask: (ws: string, body: AskBody) => req<AskResponse>("/ask", { method: "POST", body, workspace: ws }),
  conversations: (ws: string) => req<Conversation[]>("/conversations", { workspace: ws }),
  newConversation: (ws: string) => req<Conversation>("/conversations", { method: "POST", workspace: ws }),
  messages: (ws: string, id: string) => req<Message[]>(`/conversations/${id}/messages`, { workspace: ws }),
  deleteConversation: (ws: string, id: string) => req<{ deleted: string }>(`/conversations/${id}`, { method: "DELETE", workspace: ws }),
  transcribe: (ws: string, blob: Blob) => {
    const form = new FormData();
    form.append("audio", blob, "voice.webm");
    return req<{ text: string }>("/transcribe", { method: "POST", form, workspace: ws });
  },

  evalRuns: () => req<EvalSummary[]>("/eval/runs"),
  evalRun: (id: string) => req<EvalReport>(`/eval/runs/${id}`),
  runEval: (body: { sample: boolean; name?: string; compare_strategies?: boolean }) => req<EvalReport>("/eval/run", { method: "POST", body }),

  users: () => req<User[]>("/admin/users"),
  createUser: (email: string, password: string, role: string) => req<User>("/admin/users", { method: "POST", body: { email, password, role } }),
  updateUser: (id: string, patch: { role?: string; is_active?: boolean }) => req<User>(`/admin/users/${id}`, { method: "PATCH", body: patch }),
  deleteUser: (id: string) => req<{ deleted: string }>(`/admin/users/${id}`, { method: "DELETE" }),
  audit: (action?: string) => req<AuditEvent[]>(`/admin/audit?limit=200${action ? `&action=${encodeURIComponent(action)}` : ""}`),
  settings: () => req<Record<string, unknown>>("/admin/settings"),
  purge: () => req<{ purged: boolean; sources_removed: number }>("/admin/data", { method: "DELETE", body: { confirm: "DELETE-ALL-TENANT-DATA" } }),
};

/** Server-Sent Events over fetch (EventSource cannot send Authorization headers). */
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
