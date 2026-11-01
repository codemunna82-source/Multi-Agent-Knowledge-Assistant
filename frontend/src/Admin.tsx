import { useState } from "react";
import { api } from "./api";
import type { Role, User } from "./types";
import { useLoad } from "./ui";

function Users({ me }: { me: User }) {
  const users = useLoad(() => api.users(), []);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("user");
  const [err, setErr] = useState<string | null>(null);
  const run = async (fn: () => Promise<unknown>) => { try { await fn(); setErr(null); } catch (e) { setErr(e instanceof Error ? e.message : "Failed"); } void users.reload(); };
  return (
    <div className="card">
      <h2 style={{ marginTop: 0 }}>Users &amp; roles</h2>
      <table><thead><tr><th>Email</th><th>Role</th><th>Status</th><th /></tr></thead>
        <tbody>{(users.data ?? []).map((u) => (
          <tr key={u.id}><td>{u.email}{u.id === me.id && <span className="muted"> (you)</span>}</td>
            <td><select aria-label={`Role of ${u.email}`} value={u.role} onChange={(e) => void run(() => api.updateUser(u.id, { role: e.target.value }))}><option>user</option><option>manager</option><option>admin</option></select></td>
            <td>{u.is_active ? "active" : "disabled"}</td>
            <td className="row"><button className="small" onClick={() => void run(() => api.updateUser(u.id, { is_active: !u.is_active }))}>{u.is_active ? "Disable" : "Enable"}</button>
              <button className="small danger" onClick={() => { if (confirm(`Delete ${u.email} and their conversations?`)) void run(() => api.deleteUser(u.id)); }}>Delete</button></td></tr>
        ))}</tbody></table>
      {err && <div className="error" role="alert">{err}</div>}
      <h3>Add user</h3>
      <form className="row" onSubmit={(e) => { e.preventDefault(); void run(async () => { await api.createUser(email, password, role); setEmail(""); setPassword(""); }); }}>
        <input type="email" placeholder="email" aria-label="New user email" value={email} onChange={(e) => setEmail(e.target.value)} required style={{ width: 220 }} />
        <input type="password" placeholder="password (10+ chars)" aria-label="New user password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={10} style={{ width: 200 }} />
        <select aria-label="New user role" value={role} onChange={(e) => setRole(e.target.value as Role)} style={{ width: 110 }}><option>user</option><option>manager</option><option>admin</option></select>
        <button className="primary">Create</button>
      </form>
    </div>
  );
}

function Audit() {
  const [action, setAction] = useState("");
  const log = useLoad(() => api.audit(action || undefined), [action]);
  return (
    <div className="card">
      <div className="row"><h2 style={{ margin: 0 }}>Audit log</h2><span className="grow" />
        <input type="text" placeholder="filter by action (e.g. ask, login)" aria-label="Audit action filter" value={action} onChange={(e) => setAction(e.target.value)} style={{ width: 260 }} />
        <button className="small" onClick={() => void log.reload()}>Refresh</button></div>
      <p className="muted small">Questions and document text are never stored in the audit log - only a hash and length.</p>
      <table><thead><tr><th>Time</th><th>Action</th><th>Resource</th><th>Outcome</th><th>IP</th><th>Request</th></tr></thead>
        <tbody>{(log.data ?? []).map((a) => <tr key={a.id}><td className="small">{a.ts}</td><td>{a.action}</td><td className="small">{a.resource}</td><td className={a.outcome === "success" ? "ok" : "bad"}>{a.outcome}</td><td className="small">{a.ip}</td><td className="small">{a.request_id}</td></tr>)}</tbody></table>
    </div>
  );
}

function PlatformSettings() {
  const s = useLoad(() => api.settings(), []);
  const [confirmText, setConfirmText] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <div className="card">
      <h2 style={{ marginTop: 0 }}>Platform settings</h2>
      <p className="muted small">Effective configuration (read-only; change it through environment variables). Secrets are masked.</p>
      <table><tbody>{Object.entries(s.data ?? {}).map(([k, v]) => <tr key={k}><td><code>{k}</code></td><td>{String(v)}</td></tr>)}</tbody></table>
      <h2 className="bad">Danger zone</h2>
      <p className="small">Permanently erases every document, vector, conversation, job and evaluation of your organisation. Users are kept.</p>
      <div className="row">
        <input type="text" placeholder="type DELETE-ALL-TENANT-DATA" aria-label="Purge confirmation" value={confirmText} onChange={(e) => setConfirmText(e.target.value)} style={{ width: 280 }} />
        <button className="danger" disabled={confirmText !== "DELETE-ALL-TENANT-DATA"} onClick={async () => { try { const r = await api.purge(); setMsg(`Erased ${r.sources_removed} source(s).`); setConfirmText(""); } catch (e) { setMsg(e instanceof Error ? e.message : "Failed"); } }}>Erase all data</button>
      </div>
      {msg && <div role="status">{msg}</div>}
    </div>
  );
}

export function Admin({ me }: { me: User }) {
  return <div><Insightsview /><Users me={me} /><Audit /><PlatformSettings /></div>;
}

function Insightsview() {
  const [days, setDays] = useState(30);
  const d = useLoad(() => api.insights(days), [days]);
  const x = d.data;
  const max = Math.max(1, ...(x?.per_day ?? []).map((p) => p.answers));
  return (
    <div className="card" aria-label="Usage insights"><h2 style={{ marginTop: 0 }}>Usage &amp; quality</h2>
      <div className="row"><label htmlFor="ins-days" style={{ margin: 0 }}>Period</label>
        <select id="ins-days" value={days} onChange={(e) => setDays(Number(e.target.value))}>{[7, 30, 90].map((n) => <option key={n} value={n}>last {n} days</option>)}</select></div>
      {d.error && <div className="error" role="alert">{d.error}</div>}
      {x && (x.answers === 0 ? <p className="muted">No stored answers in this period.</p> : <>
        <div className="row" style={{ gap: 24, flexWrap: "wrap" }}>
          <div><b>{x.answers}</b><div className="muted small">answers</div></div>
          <div><b>{x.verified_rate === null ? "–" : `${Math.round(x.verified_rate * 100)}%`}</b><div className="muted small">verified</div></div>
          <div><b>{x.without_citations}</b><div className="muted small">without citations</div></div>
          <div><b>👍 {x.feedback.up} / 👎 {x.feedback.down}</b><div className="muted small">feedback</div></div>
          <div><b>${x.cost_usd.toFixed(4)}</b><div className="muted small">{x.tokens.toLocaleString()} tokens</div></div>
        </div>
        <div role="img" aria-label="Answers per day" style={{ display: "flex", alignItems: "flex-end", gap: 2, height: 60, marginTop: 10 }}>
          {x.per_day.map((p) => <div key={p.day} title={`${p.day}: ${p.answers}`} style={{ flex: 1, minWidth: 2, height: `${(p.answers / max) * 100}%`, background: "var(--accent, #4f46e5)" }} />)}
        </div>
        <div className="row" style={{ alignItems: "flex-start", gap: 24, flexWrap: "wrap", marginTop: 10 }}>
          <div><b className="small">Routes</b>{Object.entries(x.routes).map(([k, v]) => <div key={k} className="small">{k}: {v}</div>)}</div>
          <div><b className="small">Most cited documents</b>{x.top_sources.map((s) => <div key={s.source} className="small">{s.source}: {s.answers}</div>)}</div>
          {Object.keys(x.feedback.down_by_route).length > 0 && <div><b className="small">👎 by route</b>{Object.entries(x.feedback.down_by_route).map(([k, v]) => <div key={k} className="small">{k}: {v}</div>)}</div>}
        </div>
        <p className="muted small">{x.note}</p></>)}
    </div>
  );
}
