import { useState } from "react";
import { api } from "./api";
import { type Theme, applyTheme, loadTheme } from "./theme";
import type { TenantSettings, User } from "./types";
import { errText, useLoad } from "./ui";

export function Settings({ user, authEnabled }: { user: User; authEnabled: boolean }) {
  return (
    <div>
      <Appearance />
      <Memory authEnabled={authEnabled} />
      {user.role === "admin" && <Organisation />}
      {user.role === "admin" && <Maintenance />}
    </div>
  );
}

function Appearance() {
  const [theme, setTheme] = useState<Theme>(loadTheme());
  return (
    <div className="card"><h2 style={{ marginTop: 0 }}>Appearance</h2>
      <div className="row" role="radiogroup" aria-label="Theme">
        {(["system", "light", "dark"] as Theme[]).map((t) => (
          <label key={t} className="row" style={{ margin: 0 }}><input type="radio" name="theme" checked={theme === t} onChange={() => { setTheme(t); applyTheme(t); }} />{t === "system" ? "Follow my device" : t[0].toUpperCase() + t.slice(1)}</label>
        ))}
      </div>
    </div>
  );
}

function Memory({ authEnabled }: { authEnabled: boolean }) {
  const prefs = useLoad(() => api.memoryPrefs(), []);
  const facts = useLoad(() => api.facts(), []);
  const [note, setNote] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const run = async (fn: () => Promise<unknown>, ok?: string) => { try { await fn(); setErr(null); if (ok) setMsg(ok); } catch (e) { setErr(errText(e)); } void prefs.reload(); void facts.reload(); };
  return (
    <div className="card"><h2 style={{ marginTop: 0 }}>Memory &amp; privacy</h2>
      {!authEnabled && <p className="muted small">Authentication is disabled on this server, so memory preferences cannot be saved. Use incognito mode in the chat for private questions.</p>}
      <div className="col">
        <label className="row" style={{ margin: 0, color: "inherit" }}><input type="checkbox" checked={prefs.data?.memory_enabled ?? true} onChange={(e) => void run(() => api.setMemoryPrefs({ memory_enabled: e.target.checked }))} />Remember my conversation context (earlier turns inform follow-up questions)</label>
        <label className="row" style={{ margin: 0, color: "inherit" }}><input type="checkbox" checked={prefs.data?.long_term_memory ?? false} onChange={(e) => void run(() => api.setMemoryPrefs({ long_term_memory: e.target.checked }))} />Use my saved notes as context (never as evidence or citations)</label>
      </div>
      <h3>Saved notes</h3>
      <form className="row" onSubmit={(e) => { e.preventDefault(); if (note.trim()) void run(async () => { await api.addFact(note.trim()); setNote(""); }); }}>
        <input type="text" aria-label="New note" placeholder="e.g. I prefer answers as short bullet points" value={note} onChange={(e) => setNote(e.target.value)} style={{ flex: 1 }} maxLength={300} />
        <button className="primary" disabled={!note.trim()}>Save note</button>
      </form>
      <p className="muted small">Notes with passwords, card numbers, ID numbers, e-mail addresses or phone numbers are refused.</p>
      {(facts.data?.items ?? []).map((f) => <div key={f.id} className="row small"><span className="grow">{f.text}</span><button className="small danger" aria-label={`Delete note ${f.text}`} onClick={() => void run(() => api.deleteFact(f.id))}>Delete</button></div>)}
      <div className="row" style={{ marginTop: 10 }}>
        <button className="danger" onClick={() => { if (confirm("Delete all saved notes and conversation summaries?")) void run(async () => { const r = await api.resetMemory(false); setMsg(`Deleted ${r.facts_deleted} note(s); cleared ${r.summaries_cleared} summary(ies).`); }); }}>Reset memory</button>
        <button className="danger" onClick={() => { if (confirm("Delete ALL your conversations, messages and notes?")) void run(async () => { const r = await api.resetMemory(true); setMsg(`Deleted ${r.conversations_deleted} conversation(s) and ${r.facts_deleted} note(s).`); }); }}>Delete all my conversations</button>
      </div>
      {err && <div className="error" role="alert">{err}</div>}{msg && <div role="status">{msg}</div>}
    </div>
  );
}

function Organisation() {
  const t = useLoad(() => api.tenantSettings(), []);
  const [draft, setDraft] = useState<TenantSettings | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [domains, setDomains] = useState<string | null>(null);
  const cur = draft ?? t.data;
  if (!cur) return <div className="card muted">{t.error ?? "Loading organisation policy…"}</div>;
  const set = (patch: Partial<TenantSettings>) => setDraft({ ...cur, ...patch });
  const days = (key: keyof TenantSettings, label: string) => (
    <div><label htmlFor={key}>{label}</label>
      <input id={key} type="number" min={1} placeholder="keep forever" value={(cur[key] as number | null) ?? ""} onChange={(e) => set({ [key]: e.target.value ? Number(e.target.value) : null } as Partial<TenantSettings>)} /></div>
  );
  return (
    <form className="card" onSubmit={async (e) => { e.preventDefault(); try { const body = { ...cur, web_allowed_domains: (domains ?? cur.web_allowed_domains.join(", ")).split(/[\s,]+/).filter(Boolean) }; setDraft(await api.setTenantSettings(body)); setDomains(null); setErr(null); setMsg("Saved."); } catch (x) { setErr(errText(x)); setMsg(null); } }} aria-label="Organisation policy">
      <h2 style={{ marginTop: 0 }}>Organisation policy</h2>
      <h3>Retention (days)</h3>
      <div className="grid4">{days("retention_days_documents", "Documents")}{days("retention_days_conversations", "Conversations")}{days("retention_days_audit", "Audit log (min 30)")}{days("retention_days_reports", "Reports")}</div>
      <h3>Web research</h3>
      <label className="row" style={{ margin: 0, color: "inherit" }}><input type="checkbox" checked={cur.web_allowed} onChange={(e) => set({ web_allowed: e.target.checked })} />Allow the assistant to read web pages</label>
      <label htmlFor="dom">Approved domains (empty = any public site; sub-domains included)</label>
      <input id="dom" type="text" placeholder="example.com, docs.python.org" value={domains ?? cur.web_allowed_domains.join(", ")} onChange={(e) => setDomains(e.target.value)} />
      <h3>Privacy</h3>
      <label className="row" style={{ margin: 0, color: "inherit" }}><input type="checkbox" checked={cur.redact_stored_messages} onChange={(e) => set({ redact_stored_messages: e.target.checked })} />Mask e-mail addresses, phone numbers, card numbers and secrets in stored messages</label>
      {err && <div className="error" role="alert">{err}</div>}{msg && <div role="status" className="ok">{msg}</div>}
      <div className="row" style={{ marginTop: 10 }}><button className="primary">Save policy</button></div>
    </form>
  );
}

function Maintenance() {
  const [res, setRes] = useState<Record<string, { removed?: number; error?: string }> | null>(null);
  const [dry, setDry] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  return (
    <div className="card"><h2 style={{ marginTop: 0 }}>Retention sweep</h2>
      <p className="muted small">Applies the retention periods above to your organisation now. The scheduler (<code>python -m app.scheduler</code>) does the same periodically.</p>
      <div className="row"><label className="row" style={{ margin: 0 }}><input type="checkbox" checked={dry} onChange={(e) => setDry(e.target.checked)} />Dry run (only report)</label>
        <button className={dry ? "" : "danger"} onClick={async () => { if (!dry && !confirm("Permanently delete everything older than the retention periods?")) return; try { setRes((await api.maintenance({ dry_run: dry })).results); setErr(null); } catch (e) { setErr(errText(e)); } }}>{dry ? "Preview sweep" : "Run sweep"}</button></div>
      {err && <div className="error" role="alert">{err}</div>}
      {res && <table aria-label="Sweep result"><tbody>{Object.entries(res).map(([k, v]) => <tr key={k}><td><code>{k}</code></td><td>{v.error ? <span className="bad">{v.error}</span> : `${v.removed ?? 0} ${dry ? "would be removed" : "removed"}`}</td></tr>)}</tbody></table>}
    </div>
  );
}
