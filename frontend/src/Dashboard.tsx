import { api } from "./api";
import type { Health, User } from "./types";
import { Badge, useLoad } from "./ui";

export function Dashboard({ workspace, user, health, go }: { workspace: string; user: User; health: Health | null; go: (page: string) => void }) {
  const docs = useLoad(() => api.sources(workspace), [workspace]);
  const canSeeJobs = user.role !== "user";  // /jobs is a manager permission; plain users would only get a 403
  const jobs = useLoad(() => (canSeeJobs ? api.jobs(workspace) : Promise.resolve({ items: [], total: 0 })), [workspace, canSeeJobs]);
  const convs = useLoad(() => api.conversations(workspace), [workspace]);
  const reports = useLoad(() => api.reports(workspace), [workspace]);
  const items = docs.data?.items ?? [];
  const byKind: Record<string, number> = {}, byClass: Record<string, number> = {};
  items.forEach((s) => { byKind[s.kind] = (byKind[s.kind] ?? 0) + 1; const c = s.classification?.label ?? "unclassified"; byClass[c] = (byClass[c] ?? 0) + 1; });
  const running = (jobs.data?.items ?? []).filter((j) => j.status === "queued" || j.status === "running");
  const failed = (jobs.data?.items ?? []).filter((j) => j.status === "failed");
  const attention = items.filter((s) => s.needs_reindex || s.warnings.length);
  const errs = [docs.error, jobs.error, convs.error, reports.error].filter(Boolean);
  return (
    <div>
      <h1>Welcome, {user.email}</h1>
      {errs.length > 0 && <div className="error" role="alert">{errs[0]}</div>}
      <div className="tiles" aria-label="Key figures">
        <div className="tile"><b>{docs.data?.total ?? "…"}</b><span>documents in “{workspace}”</span></div>
        <div className="tile"><b>{running.length}</b><span>ingestion jobs running</span></div>
        <div className="tile"><b>{convs.data?.total ?? "…"}</b><span>conversations</span></div>
        <div className="tile"><b>{reports.data?.total ?? "…"}</b><span>reports generated</span></div>
        {health?.usage && <div className="tile"><b>{health.usage.questions}</b><span>questions answered (since start)</span></div>}
      </div>
      <div className="grid2">
        <div className="card"><h2 style={{ marginTop: 0 }}>Library mix</h2>
          <div className="chips" aria-label="By type">{Object.entries(byKind).map(([k, n]) => <Badge key={k}>{k}: {n}</Badge>)}{!items.length && <span className="muted small">Nothing indexed yet.</span>}</div>
          <h3>By document class</h3>
          <div className="chips" aria-label="By class">{Object.entries(byClass).map(([k, n]) => <Badge key={k}>{k}: {n}</Badge>)}</div>
        </div>
        <div className="card"><h2 style={{ marginTop: 0 }}>Needs attention</h2>
          {failed.length === 0 && attention.length === 0 && <span className="ok">All good — no failed jobs or warnings.</span>}
          {failed.slice(0, 5).map((j) => <div key={j.id} className="bad small">✖ {j.name}: {j.error}</div>)}
          {attention.slice(0, 5).map((s) => <div key={s.id} className="warn small">⚠ {s.name}: {s.needs_reindex ? "needs re-index" : s.warnings[0]}</div>)}
        </div>
      </div>
      <div className="card"><h2 style={{ marginTop: 0 }}>Recent conversations</h2>
        {(convs.data?.items ?? []).slice(0, 5).map((c) => <div key={c.id} className="small">{c.title || "Untitled"} <span className="muted">· {c.updated_at.slice(0, 16).replace("T", " ")}</span></div>)}
        {!convs.data?.items.length && <span className="muted small">No conversations yet.</span>}
      </div>
      <div className="card"><h2 style={{ marginTop: 0 }}>Quick actions</h2>
        <div className="row">
          <button className="primary" onClick={() => go("documents")}>Upload documents</button><button onClick={() => go("chat")}>Ask a question</button>
          <button onClick={() => go("search")}>Find a name or phrase</button><button onClick={() => go("analyst")}>Analyse data</button><button onClick={() => go("reports")}>Create a report</button>
        </div>
        {health && <p className="muted small">Server {health.version} · model: {health.llm} · embeddings: {health.embedder} · vector store: {health.vector_store}</p>}
      </div>
    </div>
  );
}
