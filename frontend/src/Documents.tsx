import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { Job, QueuedItem, SourceInfo } from "./types";
import { Badge, Modal, useLoad } from "./ui";

interface Upload { key: string; name: string; jobId: string | null; job?: Job; error?: string | null }

export function Documents({ workspace, canIngest, onAsk }: { workspace: string; canIngest: boolean; onAsk: (q: string) => void }) {
  const sources = useLoad(() => api.sources(workspace), [workspace]);
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [visibility, setVisibility] = useState("tenant");
  const [url, setUrl] = useState("");
  const [over, setOver] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [modal, setModal] = useState<{ title: string; body: React.ReactNode } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // poll running jobs
  useEffect(() => {
    const pending = uploads.filter((u) => u.jobId && u.job?.status !== "ready" && u.job?.status !== "failed");
    if (!pending.length) return;
    const t = setTimeout(async () => {
      const updated = await Promise.all(uploads.map(async (u) => {
        if (!u.jobId || u.job?.status === "ready" || u.job?.status === "failed") return u;
        try { return { ...u, job: await api.job(workspace, u.jobId) }; } catch (e) { return { ...u, error: e instanceof Error ? e.message : "lost job" }; }
      }));
      setUploads(updated);
      if (updated.some((u) => u.job?.status === "ready")) void sources.reload();
    }, 500);
    return () => clearTimeout(t);
  }, [uploads, workspace, sources]);

  function track(items: QueuedItem[]) {
    setUploads((prev) => [...items.map((i, n) => ({ key: `${Date.now()}-${n}`, name: i.name, jobId: i.job_id, error: i.error })), ...prev].slice(0, 30));
  }

  async function upload(files: File[]) {
    if (!files.length) return;
    setMsg(null);
    try { track(await api.uploadFiles(workspace, files, visibility)); } catch (e) { setMsg(e instanceof Error ? e.message : "Upload failed"); }
  }
  async function addUrl() {
    if (!url.trim()) return;
    try { track(await api.addUrl(workspace, url.trim(), visibility)); setUrl(""); } catch (e) { setMsg(e instanceof Error ? e.message : "Failed"); }
  }
  async function act(fn: () => Promise<unknown>) {
    try { await fn(); setMsg(null); } catch (e) { setMsg(e instanceof Error ? e.message : "Failed"); }
    void sources.reload();
  }
  async function showEntities(s: SourceInfo) {
    const r = await api.entities(workspace, s.id);
    setModal({ title: `Entities — ${s.name}`, body: (
      <div>
        <p className="muted small">Method: {r.method}</p>
        {Object.entries(r.entities).map(([t, es]) => (
          <div key={t}><h3>{t}</h3><div className="chips">{es.slice(0, 15).map((e) => <Badge key={e.value}>{e.value} ×{e.count}</Badge>)}</div></div>
        ))}
        {!Object.keys(r.entities).length && <p>No entities found.</p>}
      </div>
    ) });
  }
  async function showQuestions(s: SourceInfo) {
    const r = await api.questions(workspace, s.id);
    setModal({ title: `Suggested questions — ${s.name}`, body: (
      <ul>{r.questions.map((q) => <li key={q}><button className="small" onClick={() => { setModal(null); onAsk(q); }}>{q}</button></li>)}</ul>
    ) });
  }

  return (
    <div>
      {canIngest && (
        <div className="card">
          <div className="row">
            <div className={`drop grow ${over ? "over" : ""}`} role="button" tabIndex={0} aria-label="Upload documents"
              onClick={() => fileRef.current?.click()} onKeyDown={(e) => e.key === "Enter" && fileRef.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
              onDrop={(e) => { e.preventDefault(); setOver(false); void upload([...e.dataTransfer.files]); }}>
              Drop files here or click to choose<br /><span className="small">PDF, DOCX, XLSX, CSV, TXT, MD, JSON, PNG/JPG (OCR)</span>
              <input ref={fileRef} data-testid="file-input" type="file" multiple hidden onChange={(e) => { void upload([...(e.target.files ?? [])]); e.target.value = ""; }} />
            </div>
            <div className="col" style={{ minWidth: 260 }}>
              <div className="row">
                <input type="text" placeholder="https://… public web page" value={url} onChange={(e) => setUrl(e.target.value)} aria-label="URL" style={{ flex: 1 }} />
                <button onClick={addUrl}>Add URL</button>
              </div>
              <div><label htmlFor="vis">Visibility</label>
                <select id="vis" value={visibility} onChange={(e) => setVisibility(e.target.value)}>
                  <option value="tenant">Everyone in my organisation</option><option value="private">Only me (and admins)</option>
                </select></div>
            </div>
          </div>
          {msg && <div className="error" role="alert">{msg}</div>}
          {uploads.length > 0 && (
            <div className="col" style={{ marginTop: 10 }} aria-label="Ingestion progress">
              {uploads.map((u) => {
                const st = u.error ? "failed" : u.job?.status ?? "queued";
                return (
                  <div key={u.key}>
                    <div className="row small"><span>{u.name}</span><span className="grow" />
                      <span className={st === "failed" ? "bad" : st === "ready" ? "ok" : "muted"}>{st === "failed" ? u.error ?? u.job?.error : st === "ready" ? "indexed" : `${u.job?.stage ?? "queued"} ${u.job?.progress ?? 0}%`}</span></div>
                    <div className={`progress ${st === "failed" ? "failed" : ""}`}><i style={{ width: `${st === "failed" ? 100 : u.job?.progress ?? 0}%` }} /></div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
      <div className="card">
        <div className="row"><h2 style={{ margin: 0 }}>Documents in “{workspace}”</h2><span className="grow" /><button className="small" onClick={() => void sources.reload()}>Refresh</button></div>
        {sources.error && <div className="error" role="alert">{sources.error}</div>}
        <table>
          <thead><tr><th>Name</th><th>Type</th><th>Size</th><th>Access</th><th>Notes</th><th /></tr></thead>
          <tbody>
            {(sources.data ?? []).map((s) => (
              <tr key={s.id}>
                <td>{s.name}{s.title && s.title !== s.name ? <div className="muted small">{s.title}</div> : null}</td>
                <td><Badge>{s.kind}</Badge></td>
                <td className="small">{s.pages ? `${s.pages} pages · ` : ""}{s.chunks ?? "?"} chunks</td>
                <td><Badge>{s.visibility === "private" ? "private" : "organisation"}</Badge></td>
                <td className="small">{s.needs_reindex && <div className="warn">needs re-index</div>}{s.warnings.map((w) => <div key={w} className="muted">⚠ {w}</div>)}</td>
                <td>
                  <div className="row">
                    {!s.tabular && <button className="small" onClick={() => void showEntities(s)}>Entities</button>}
                    <button className="small" onClick={() => void showQuestions(s)}>Questions</button>
                    {canIngest && <button className="small" onClick={() => void act(() => api.reindex(workspace, s.id))}>Re-index</button>}
                    {canIngest && <button className="small danger" onClick={() => { if (confirm(`Delete ${s.name}? This removes its text and vectors.`)) void act(() => api.deleteSource(workspace, s.id)); }}>Delete</button>}
                  </div>
                </td>
              </tr>
            ))}
            {!sources.loading && !sources.data?.length && <tr><td colSpan={6} className="muted">Nothing indexed in this workspace yet.</td></tr>}
          </tbody>
        </table>
      </div>
      {modal && <Modal title={modal.title} onClose={() => setModal(null)}>{modal.body}</Modal>}
    </div>
  );
}
