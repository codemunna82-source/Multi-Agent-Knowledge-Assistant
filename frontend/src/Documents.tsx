import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { Preview } from "./Preview";
import type { Job, QueuedItem, Sharing, SourceInfo } from "./types";
import { Badge, DataTable, Modal, Pager, errText, useLoad } from "./ui";

interface Upload { key: string; name: string; file?: File; jobId: string | null; job?: Job; error?: string | null; duplicate?: boolean }
const PAGE = 25;
const KIND_OPTIONS = ["", "pdf", "docx", "xlsx", "xls", "csv", "txt", "md", "html", "json", "url", "image"];
const done = (s?: string) => s === "ready" || s === "failed" || s === "duplicate";

export function Documents({ workspace, canIngest, canShare, onAsk }: { workspace: string; canIngest: boolean; canShare: boolean; onAsk: (q: string) => void }) {
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("");
  const [withVersions, setWithVersions] = useState(false);
  const [offset, setOffset] = useState(0);
  const sources = useLoad(() => api.sources(workspace, { q: q || undefined, kind: kind || undefined, include_versions: withVersions, limit: PAGE, offset }), [workspace, q, kind, withVersions, offset]);
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [visibility, setVisibility] = useState("tenant");
  const [url, setUrl] = useState("");
  const [over, setOver] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [modal, setModal] = useState<{ title: string; body: React.ReactNode } | null>(null);
  const [preview, setPreview] = useState<SourceInfo | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // poll running jobs
  useEffect(() => {
    const pending = uploads.filter((u) => u.jobId && !done(u.job?.status));
    if (!pending.length) return;
    const t = setTimeout(async () => {
      const updated = await Promise.all(uploads.map(async (u) => {
        if (!u.jobId || done(u.job?.status)) return u;
        try { const job = await api.job(workspace, u.jobId); return { ...u, job, duplicate: job.status === "duplicate" }; } catch (e) { return { ...u, error: errText(e, "lost job") }; }
      }));
      setUploads(updated);
      if (updated.some((u) => u.job?.status === "ready")) void sources.reload();
    }, 500);
    return () => clearTimeout(t);
  }, [uploads, workspace, sources]);

  function track(items: QueuedItem[], files: File[] = []) {
    setUploads((prev) => [...items.map((i, n) => ({ key: `${Date.now()}-${n}`, name: i.name, file: files[n], jobId: i.job_id, error: i.error, duplicate: i.status === "duplicate" })), ...prev].slice(0, 30));
  }
  async function upload(files: File[], allowDuplicate = false) {
    if (!files.length) return;
    setMsg(null);
    try { track(await api.uploadFiles(workspace, files, visibility, allowDuplicate), files); } catch (e) { setMsg(errText(e, "Upload failed")); }
  }
  async function addUrl() {
    if (!url.trim()) return;
    try { track(await api.addUrl(workspace, url.trim(), visibility)); setUrl(""); } catch (e) { setMsg(errText(e)); }
  }
  async function act(fn: () => Promise<unknown>) {
    try { await fn(); setMsg(null); } catch (e) { setMsg(errText(e)); }
    void sources.reload();
  }
  async function showDetails(s: SourceInfo) {
    try {
      const [ent, tl] = await Promise.all([s.tabular ? Promise.resolve(null) : api.entities(workspace, s.id), s.tabular ? Promise.resolve(null) : api.timeline(workspace, s.id).catch(() => null)]);
      setModal({ title: `Details — ${s.name}`, body: (
        <div>
          <p className="small">Class: <Badge>{s.classification?.label ?? "unclassified"}</Badge> {s.classification && <span className="muted">({Math.round(s.classification.confidence * 100)}% · {s.classification.method})</span>} · language: {s.language ?? "?"} · version {s.version ?? 1}</p>
          {ent && Object.entries(ent.entities).map(([t, es]) => <div key={t}><h3>{t}</h3><div className="chips">{es.slice(0, 15).map((e) => <Badge key={e.value}>{e.value} ×{e.count}</Badge>)}</div></div>)}
          {tl && tl.events.length > 0 && <><h3>Timeline</h3><DataTable columns={["Date", "Event", "Where"]} rows={tl.events.slice(0, 40).map((e) => [e.date + (e.ambiguous ? " ⚠" : ""), e.event, e.location])} /></>}
          {s.tables && s.tables.length > 0 && <><h3>Sheets</h3><DataTable columns={["Sheet", "Rows", "Columns"]} rows={s.tables.map((t) => [t.sheet ?? "—", t.rows, t.columns.join(", ")])} /></>}
          {!ent && !s.tables && <p>No details available.</p>}
        </div>
      ) });
    } catch (e) { setMsg(errText(e)); }
  }
  async function showQuestions(s: SourceInfo) {
    const r = await api.questions(workspace, s.id);
    setModal({ title: `Suggested questions — ${s.name}`, body: <ul>{r.questions.map((x) => <li key={x}><button className="small" onClick={() => { setModal(null); onAsk(x); }}>{x}</button></li>)}</ul> });
  }
  async function showVersions(s: SourceInfo) {
    try {
      const vs = await api.versions(workspace, s.id);
      setModal({ title: `Versions — ${s.name}`, body: (
        <div>
          <table><thead><tr><th>Version</th><th>Indexed</th><th>Hash</th><th /></tr></thead>
            <tbody>{vs.map((v) => (
              <tr key={v.id}><td>v{v.version} {v.is_current && <Badge kind="high">current</Badge>}</td><td className="small">{v.created_at.slice(0, 16).replace("T", " ")}</td><td className="small"><code>{(v.content_hash ?? "").slice(0, 10)}</code></td>
                <td className="row">
                  {!v.is_current && canIngest && <button className="small" onClick={async () => { await act(() => api.makeCurrent(workspace, v.id)); setModal(null); }}>Make current</button>}
                  {v.version !== undefined && v.version > 1 && <button className="small" onClick={async () => {
                    const d = await api.changes(workspace, v.id);
                    setModal({ title: `Changes v${d.from_version} → v${d.to_version}`, body: <div><p>{d.summary.changed} changed, {d.summary.added} added, {d.summary.removed} removed ({Math.round(d.summary.similarity * 100)}% similar)</p>
                      <DataTable columns={["Before", "After", "Numbers"]} rows={d.changed.map((c) => [c.before.text, c.after.text, c.number_changes.map((n) => `${n.from}→${n.to}`).join(", ")])} /></div> });
                  }}>What changed?</button>}
                </td></tr>
            ))}</tbody></table>
          {vs.length < 2 && <p className="muted small">Re-upload a changed file with the same name to create version 2.</p>}
        </div>
      ) });
    } catch (e) { setMsg(errText(e)); }
  }
  async function showSharing(s: SourceInfo) {
    try {
      const sh = await api.sharing(workspace, s.id);
      setModal({ title: `Sharing — ${s.name}`, body: <SharingForm initial={sh} onSave={async (b) => { await act(() => api.setSharing(workspace, s.id, b)); setModal(null); }} /> });
    } catch (e) { setMsg(errText(e)); }
  }

  const rows = sources.data?.items ?? [];
  return (
    <div>
      {canIngest && (
        <div className="card">
          <div className="row">
            <div className={`drop grow ${over ? "over" : ""}`} role="button" tabIndex={0} aria-label="Upload documents"
              onClick={() => fileRef.current?.click()} onKeyDown={(e) => e.key === "Enter" && fileRef.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
              onDrop={(e) => { e.preventDefault(); setOver(false); void upload([...e.dataTransfer.files]); }}>
              Drop files here or click to choose<br /><span className="small">PDF, DOCX, XLSX/XLS, CSV, TXT, MD, HTML, JSON, PNG/JPG (OCR)</span>
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
                const st = u.error ? "failed" : u.job?.status ?? (u.duplicate ? "duplicate" : "queued");
                return (
                  <div key={u.key}>
                    <div className="row small"><span>{u.name}</span><span className="grow" />
                      {st === "duplicate" && <><span className="warn">identical file already indexed</span>{u.file && <button className="small" onClick={() => void upload([u.file as File], true)}>Upload anyway</button>}</>}
                      {st !== "duplicate" && <span className={st === "failed" ? "bad" : st === "ready" ? "ok" : "muted"}>{st === "failed" ? u.error ?? u.job?.error : st === "ready" ? "indexed" : `${u.job?.stage ?? "queued"} ${u.job?.progress ?? 0}%`}</span>}</div>
                    <div className={`progress ${st === "failed" ? "failed" : ""}`}><i style={{ width: `${st === "failed" || st === "duplicate" ? 100 : u.job?.progress ?? 0}%` }} /></div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
      <div className="card">
        <div className="row"><h2 style={{ margin: 0 }}>Library — “{workspace}”</h2><span className="grow" />
          <input type="text" placeholder="search by name…" aria-label="Search documents" value={q} onChange={(e) => { setQ(e.target.value); setOffset(0); }} style={{ width: 200 }} />
          <select aria-label="Filter by type" value={kind} onChange={(e) => { setKind(e.target.value); setOffset(0); }} style={{ width: 110 }}>{KIND_OPTIONS.map((k) => <option key={k} value={k}>{k || "all types"}</option>)}</select>
          <label className="row small" style={{ margin: 0 }}><input type="checkbox" checked={withVersions} onChange={(e) => { setWithVersions(e.target.checked); setOffset(0); }} />old versions</label>
          <button className="small" onClick={() => void sources.reload()}>Refresh</button></div>
        {sources.error && <div className="error" role="alert">{sources.error}</div>}
        {!canIngest && msg && <div className="error" role="alert">{msg}</div>}
        <table>
          <thead><tr><th>Name</th><th>Type / class</th><th>Size</th><th>Access</th><th>Notes</th><th /></tr></thead>
          <tbody>
            {rows.map((s) => (
              <tr key={s.id}>
                <td>{s.name} <span className="muted small">v{s.version ?? 1}{s.is_current === false ? " (old)" : ""}</span>{s.title && s.title !== s.name ? <div className="muted small">{s.title}</div> : null}</td>
                <td><Badge>{s.kind}</Badge> {s.classification && <Badge>{s.classification.label}</Badge>} {s.language && s.language !== "en" && <Badge>{s.language}</Badge>}</td>
                <td className="small">{s.pages ? `${s.pages} pages · ` : ""}{s.chunks ?? "?"} chunks</td>
                <td><Badge>{s.visibility === "private" ? "private" : s.visibility === "restricted" ? "shared" : "organisation"}</Badge></td>
                <td className="small">{s.needs_reindex && <div className="warn">needs re-index</div>}{s.warnings.map((w) => <div key={w} className="muted">⚠ {w}</div>)}</td>
                <td>
                  <div className="row">
                    {s.kind === "pdf" && <button className="small" onClick={() => setPreview(s)}>Preview</button>}
                    <button className="small" onClick={() => void showDetails(s)}>Details</button>
                    <button className="small" onClick={() => void showQuestions(s)}>Questions</button>
                    <button className="small" onClick={() => void showVersions(s)}>Versions</button>
                    {canShare && <button className="small" onClick={() => void showSharing(s)}>Share</button>}
                    {canIngest && <button className="small" onClick={() => void act(() => api.reindex(workspace, s.id))}>Re-index</button>}
                    {canIngest && <button className="small danger" onClick={() => { if (confirm(`Delete ${s.name}? This removes its text and vectors.`)) void act(() => api.deleteSource(workspace, s.id)); }}>Delete</button>}
                  </div>
                </td>
              </tr>
            ))}
            {!sources.loading && !rows.length && <tr><td colSpan={6} className="muted">{q || kind ? "No documents match." : "Nothing indexed in this workspace yet."}</td></tr>}
          </tbody>
        </table>
        <Pager total={sources.data?.total ?? 0} limit={PAGE} offset={offset} onChange={setOffset} />
      </div>
      {modal && <Modal title={modal.title} onClose={() => setModal(null)}>{modal.body}</Modal>}
      {preview && <Preview workspace={workspace} citation={{ source_id: preview.id, source: preview.name, location: "page 1", excerpt: "", loc: { page: 1 } }} onClose={() => setPreview(null)} />}
    </div>
  );
}

function SharingForm({ initial, onSave }: { initial: Sharing; onSave: (s: Sharing) => Promise<void> }) {
  const [vis, setVis] = useState(initial.visibility);
  const [users, setUsers] = useState(initial.users.join(", "));
  const [roles, setRoles] = useState<string[]>(initial.roles);
  const [err, setErr] = useState<string | null>(null);
  const toggle = (r: string) => setRoles(roles.includes(r) ? roles.filter((x) => x !== r) : [...roles, r]);
  return (
    <form className="col" onSubmit={async (e) => { e.preventDefault(); try { await onSave({ visibility: vis, users: users.split(",").map((x) => x.trim()).filter(Boolean), roles }); } catch (x) { setErr(errText(x)); } }}>
      <div><label htmlFor="shvis">Who can read this document</label>
        <select id="shvis" value={vis} onChange={(e) => setVis(e.target.value)}>
          <option value="tenant">Everyone in the organisation</option><option value="private">Only the owner (and admins)</option><option value="restricted">Selected users / roles</option>
        </select></div>
      {vis === "restricted" && <>
        <div><label htmlFor="shusers">User ids (comma separated)</label><input id="shusers" type="text" value={users} onChange={(e) => setUsers(e.target.value)} /></div>
        <div className="row">{["user", "manager", "admin"].map((r) => <label key={r} className="row small" style={{ margin: 0 }}><input type="checkbox" checked={roles.includes(r)} onChange={() => toggle(r)} />{r}</label>)}</div>
      </>}
      {err && <div className="error" role="alert">{err}</div>}
      <button className="primary">Save sharing</button>
    </form>
  );
}
