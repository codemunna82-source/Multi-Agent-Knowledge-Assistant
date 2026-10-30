import { useCallback, useEffect, useState } from "react";
import { Admin } from "./Admin";
import { api, hasToken, setToken } from "./api";
import { Chat } from "./Chat";
import { Documents } from "./Documents";
import { Evaluation } from "./Evaluation";
import { Login } from "./Login";
import type { Health, User } from "./types";

type Page = "documents" | "chat" | "evaluation" | "admin";
const DEV_USER: User = { id: "anonymous", tenant_id: "default", email: "anonymous@local", role: "admin" };
const WS_RE = /^[A-Za-z0-9_-]{1,64}$/;

export function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [booting, setBooting] = useState(true);
  const [page, setPage] = useState<Page>("documents");
  const [workspace, setWorkspace] = useState(() => { try { return localStorage.getItem("mka_ws") ?? "default"; } catch { return "default"; } });
  const [wsDraft, setWsDraft] = useState(workspace);
  const [prefill, setPrefill] = useState<string | null>(null);
  const [fatal, setFatal] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const h = await api.health();
        setHealth(h);
        if (!h.auth_enabled) setUser(DEV_USER);
        else if (hasToken()) { try { setUser(await api.me()); } catch { setToken(null); } }
      } catch (e) { setFatal(e instanceof Error ? e.message : "Cannot reach the API"); } finally { setBooting(false); }
    })();
  }, []);

  const applyWs = useCallback(() => {
    if (WS_RE.test(wsDraft)) { setWorkspace(wsDraft); try { localStorage.setItem("mka_ws", wsDraft); } catch { /* ignore */ } } else setWsDraft(workspace);
  }, [wsDraft, workspace]);

  if (booting) return <div className="page muted">Loading…</div>;
  if (fatal) return <div className="page error" role="alert">Cannot reach the API: {fatal}</div>;
  if (!user) return <Login onUser={setUser} allowSignup />;

  const can = (r: "editor" | "admin") => user.role === "admin" || (r === "editor" && user.role === "editor");
  const tabs: [Page, string][] = [["documents", "Documents"], ["chat", "Chat"], ...(can("editor") ? [["evaluation", "Evaluation"] as [Page, string]] : []), ...(can("admin") ? [["admin", "Admin"] as [Page, string]] : [])];

  return (
    <div className="shell">
      {!health?.auth_enabled && <div className="banner">Development mode: authentication is disabled, everyone is an admin of tenant “default”. Enable MKA_AUTH_ENABLED for real deployments.</div>}
      <header className="top">
        <span className="brand">📚 Knowledge Intelligence</span>
        <nav className="tabs" aria-label="Sections">{tabs.map(([p, label]) => <button key={p} className={page === p ? "on" : ""} onClick={() => setPage(p)}>{label}</button>)}</nav>
        <span className="grow" />
        <form className="row" onSubmit={(e) => { e.preventDefault(); applyWs(); }}>
          <label htmlFor="ws" style={{ margin: 0 }}>Workspace</label>
          <input id="ws" type="text" value={wsDraft} onChange={(e) => setWsDraft(e.target.value)} onBlur={applyWs} style={{ width: 130 }} />
        </form>
        <span className="muted small">{user.email} · {user.role}</span>
        {health?.auth_enabled && <button className="small" onClick={async () => { try { await api.logout(); } catch { /* ignore */ } setToken(null); setUser(null); }}>Sign out</button>}
      </header>
      <main className="page">
        {page === "documents" && <Documents workspace={workspace} canIngest={can("editor")} onAsk={(q) => { setPrefill(q); setPage("chat"); }} />}
        {page === "chat" && <Chat workspace={workspace} prefill={prefill} onPrefillUsed={() => setPrefill(null)} />}
        {page === "evaluation" && can("editor") && <Evaluation />}
        {page === "admin" && can("admin") && <Admin me={user} />}
      </main>
    </div>
  );
}
