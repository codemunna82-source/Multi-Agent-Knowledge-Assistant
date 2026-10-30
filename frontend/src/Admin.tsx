import { useState } from "react";
import { api } from "./api";
import type { Role, User } from "./types";
import { useLoad } from "./ui";

function Users({ me }: { me: User }) {
  const users = useLoad(() => api.users(), []);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("viewer");
  const [err, setErr] = useState<string | null>(null);
  const run = async (fn: () => Promise<unknown>) => { try { await fn(); setErr(null); } catch (e) { setErr(e instanceof Error ? e.message : "Failed"); } void users.reload(); };
  return (
    <div className="card">
      <h2 style={{ marginTop: 0 }}>Users &amp; roles</h2>
      <table><thead><tr><th>Email</th><th>Role</th><th>Status</th><th /></tr></thead>
        <tbody>{(users.data ?? []).map((u) => (
          <tr key={u.id}><td>{u.email}{u.id === me.id && <span className="muted"> (you)</span>}</td>
            <td><select aria-label={`Role of ${u.email}`} value={u.role} onChange={(e) => void run(() => api.updateUser(u.id, { role: e.target.value }))}><option>viewer</option><option>editor</option><option>admin</option></select></td>
            <td>{u.is_active ? "active" : "disabled"}</td>
            <td className="row"><button className="small" onClick={() => void run(() => api.updateUser(u.id, { is_active: !u.is_active }))}>{u.is_active ? "Disable" : "Enable"}</button>
              <button className="small danger" onClick={() => { if (confirm(`Delete ${u.email} and their conversations?`)) void run(() => api.deleteUser(u.id)); }}>Delete</button></td></tr>
        ))}</tbody></table>
      {err && <div className="error" role="alert">{err}</div>}
      <h3>Add user</h3>
      <form className="row" onSubmit={(e) => { e.preventDefault(); void run(async () => { await api.createUser(email, password, role); setEmail(""); setPassword(""); }); }}>
        <input type="email" placeholder="email" aria-label="New user email" value={email} onChange={(e) => setEmail(e.target.value)} required style={{ width: 220 }} />
        <input type="password" placeholder="password (10+ chars)" aria-label="New user password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={10} style={{ width: 200 }} />
        <select aria-label="New user role" value={role} onChange={(e) => setRole(e.target.value as Role)} style={{ width: 110 }}><option>viewer</option><option>editor</option><option>admin</option></select>
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

function Settings() {
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
  return <div><Users me={me} /><Audit /><Settings /></div>;
}
