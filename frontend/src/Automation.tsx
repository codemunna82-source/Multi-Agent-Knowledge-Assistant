import { useState } from "react";
import { api } from "./api";
import { Badge, DataTable, Tabs, errText, useLoad } from "./ui";

type Tab = "alerts" | "schedules" | "connectors";

export function Automation({ workspace, canIngest }: { workspace: string; canIngest: boolean }) {
  const [tab, setTab] = useState<Tab>("alerts");
  return (
    <div>
      <div className="card"><h1 style={{ marginTop: 0 }}>Automation</h1>
        <p className="muted">Watch for names in new documents, generate reports on a schedule, and keep this workspace in sync with a folder, a list of web pages or an S3 prefix. The scheduler process (<code>python -m app.scheduler</code>) runs schedules and syncs.</p>
        <Tabs label="Automation" value={tab} onChange={setTab} tabs={[["alerts", "Watches & alerts"], ["schedules", "Scheduled reports"], ...(canIngest ? [["connectors", "Connectors"] as [Tab, string]] : [])]} /></div>
      {tab === "alerts" && <Alerts workspace={workspace} />}
      {tab === "schedules" && <Schedules workspace={workspace} />}
      {tab === "connectors" && canIngest && <Connectors workspace={workspace} />}
    </div>
  );
}

function Alerts({ workspace }: { workspace: string }) {
  const watches = useLoad(() => api.savedSearches(), []);
  const alerts = useLoad(() => api.alerts(workspace), [workspace]);
  const [term, setTerm] = useState("");
  const [hook, setHook] = useState("");
  const [err, setErr] = useState<string | null>(null);
  async function add() {
    try { await api.addSavedSearch(workspace, { term: term.trim(), webhook_url: hook.trim() || undefined }); setTerm(""); setHook(""); setErr(null); void watches.reload(); } catch (e) { setErr(errText(e)); }
  }
  return (
    <div>
      <form className="card" onSubmit={(e) => { e.preventDefault(); void add(); }} aria-label="Add watch">
        <h2 style={{ marginTop: 0 }}>Watch a name or phrase</h2>
        <div className="row"><input type="text" aria-label="Term to watch" placeholder="e.g. Anjali Rao, INV-2041" value={term} onChange={(e) => setTerm(e.target.value)} style={{ flex: 1, minWidth: 200 }} />
          <input type="text" aria-label="Webhook URL (optional)" placeholder="https://hooks.example.com/… (optional)" value={hook} onChange={(e) => setHook(e.target.value)} style={{ flex: 1, minWidth: 200 }} />
          <button className="primary" disabled={term.trim().length < 2}>Watch</button></div>
        <p className="muted small">Every newly ingested document you may read is searched; a match creates an alert (and POSTs ids, counts and locations — never document text — to the webhook).</p>
        {err && <div className="error" role="alert">{err}</div>}
        <div className="chips">{(watches.data ?? []).map((w) => <span key={w.id} className="badge">{w.term}{w.webhook_url ? " 🔗" : ""} <button className="small" aria-label={`Stop watching ${w.term}`} onClick={async () => { await api.deleteSavedSearch(w.id); void watches.reload(); }}>×</button></span>)}</div>
      </form>
      <div className="card">
        <div className="row"><h2 style={{ margin: 0 }}>Alerts</h2><span className="grow" /><button className="small" onClick={async () => { await api.alertsSeen(); void alerts.reload(); }}>Mark all seen</button></div>
        {alerts.error && <div className="error" role="alert">{alerts.error}</div>}
        <DataTable columns={["When", "Term", "Document", "Occurrences", "Where", ""]} rows={(alerts.data?.items ?? []).map((a) => [a.created_at.slice(0, 16).replace("T", " "), a.term, a.source_name, a.count, a.locations.slice(0, 3).join(", "), a.seen ? "" : "new"])} />
        {!alerts.data?.items.length && <p className="muted small">No alerts yet.</p>}
      </div>
    </div>
  );
}

function Schedules({ workspace }: { workspace: string }) {
  const list = useLoad(() => api.schedules(workspace), [workspace]);
  const [name, setName] = useState("");
  const [kind, setKind] = useState("summary");
  const [format, setFormat] = useState("pdf");
  const [hours, setHours] = useState(168);
  const [hook, setHook] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  async function add() {
    try { await api.addSchedule(workspace, { name: name.trim(), kind, format, every_hours: hours, webhook_url: hook.trim() || undefined }); setName(""); setErr(null); void list.reload(); } catch (e) { setErr(errText(e)); }
  }
  return (
    <div>
      <form className="card" onSubmit={(e) => { e.preventDefault(); void add(); }} aria-label="Add schedule">
        <h2 style={{ marginTop: 0 }}>Generate a report on a schedule</h2>
        <div className="row">
          <input type="text" aria-label="Schedule name" placeholder="Weekly summary" value={name} onChange={(e) => setName(e.target.value)} />
          <select aria-label="Report kind" value={kind} onChange={(e) => setKind(e.target.value)}>{["summary", "executive", "analytics"].map((k) => <option key={k}>{k}</option>)}</select>
          <select aria-label="Report format" value={format} onChange={(e) => setFormat(e.target.value)}><option>pdf</option><option>docx</option><option>xlsx</option></select>
          <label className="row small" style={{ margin: 0 }}>every <input type="number" min={1} max={744} aria-label="Every N hours" value={hours} onChange={(e) => setHours(Number(e.target.value) || 1)} style={{ width: 80 }} /> hours</label>
          <input type="text" aria-label="Report webhook URL" placeholder="webhook when ready (optional)" value={hook} onChange={(e) => setHook(e.target.value)} />
          <button className="primary" disabled={!name.trim()}>Schedule</button></div>
        {err && <div className="error" role="alert">{err}</div>}
      </form>
      <div className="card">
        <h2 style={{ marginTop: 0 }}>Schedules</h2>
        {msg && <div role="status" className="small">{msg}</div>}
        {(list.data ?? []).map((s) => (
          <div key={s.id} className="row small" style={{ borderTop: "1px solid var(--line)", padding: "6px 0" }}>
            <b>{s.name}</b><Badge>{s.spec.kind} · {s.spec.format}</Badge><span>every {s.every_hours} h</span><span className="muted">last: {s.last_run_at ? s.last_run_at.slice(0, 16).replace("T", " ") : "never"} {s.last_status ?? ""}</span><span className="grow" />
            <button className="small" onClick={async () => { try { setMsg((await api.runSchedule(workspace, s.id)).status); void list.reload(); } catch (e) { setMsg(errText(e)); } }}>Run now</button>
            <button className="small" onClick={async () => { await api.toggleSchedule(workspace, s.id, !s.enabled); void list.reload(); }}>{s.enabled ? "Pause" : "Resume"}</button>
            <button className="small danger" onClick={async () => { await api.deleteSchedule(s.id); void list.reload(); }}>Delete</button>
          </div>
        ))}
        {!list.data?.length && <p className="muted small">No schedules yet. Reports appear under Reports when they run.</p>}
      </div>
    </div>
  );
}

function Connectors({ workspace }: { workspace: string }) {
  const list = useLoad(() => api.connectors(workspace), [workspace]);
  const [name, setName] = useState("");
  const [kind, setKind] = useState("folder");
  const [value, setValue] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const hint = { folder: "folder below the server's connector root, e.g. hr/policies", urls: "one URL per line", s3: "bucket/prefix (needs boto3 on the server)" }[kind as "folder" | "urls" | "s3"];
  async function add() {
    const config = kind === "folder" ? { path: value.trim(), recursive: true } : kind === "urls" ? { urls: value.split("\n").map((x) => x.trim()).filter(Boolean) } : { bucket: value.split("/")[0], prefix: value.split("/").slice(1).join("/") };
    try { await api.addConnector(workspace, { name: name.trim(), kind, config, every_hours: 24 }); setName(""); setValue(""); setErr(null); void list.reload(); } catch (e) { setErr(errText(e)); }
  }
  return (
    <div>
      <form className="card" onSubmit={(e) => { e.preventDefault(); void add(); }} aria-label="Add connector">
        <h2 style={{ marginTop: 0 }}>Keep this workspace in sync</h2>
        <div className="row"><input type="text" aria-label="Connector name" placeholder="HR share" value={name} onChange={(e) => setName(e.target.value)} />
          <select aria-label="Connector kind" value={kind} onChange={(e) => setKind(e.target.value)}><option value="folder">Folder</option><option value="urls">Web pages</option><option value="s3">S3</option></select></div>
        <label htmlFor="cval">{hint}</label>{kind === "urls" ? <textarea id="cval" rows={3} value={value} onChange={(e) => setValue(e.target.value)} /> : <input id="cval" type="text" value={value} onChange={(e) => setValue(e.target.value)} />}
        <p className="muted small">Identical files are skipped, a changed file with the same name becomes a new version. Runs every 24 hours on the scheduler, or on demand.</p>
        {err && <div className="error" role="alert">{err}</div>}<button className="primary" disabled={!name.trim() || !value.trim()}>Add connector</button>
      </form>
      <div className="card"><h2 style={{ marginTop: 0 }}>Connectors</h2>{msg && <div role="status" className="small">{msg}</div>}
        {(list.data ?? []).map((c) => (
          <div key={c.id} className="row small" style={{ borderTop: "1px solid var(--line)", padding: "6px 0" }}>
            <b>{c.name}</b><Badge>{c.kind}</Badge><span className="muted">{c.last_result ? `last: ${c.last_result.ready} new, ${c.last_result.duplicate} unchanged, ${c.last_result.failed} failed` : "never synced"}</span><span className="grow" />
            <button className="small" onClick={async () => { try { const r = await api.syncConnector(workspace, c.id); setMsg(`${c.name}: ${r.ready} new, ${r.duplicate} unchanged, ${r.failed} failed${r.errors.length ? " — " + r.errors[0] : ""}`); void list.reload(); } catch (e) { setMsg(errText(e)); } }}>Sync now</button>
            <button className="small danger" onClick={async () => { await api.deleteConnector(c.id); void list.reload(); }}>Delete</button>
          </div>
        ))}{!list.data?.length && <p className="muted small">No connectors yet.</p>}</div>
    </div>
  );
}
