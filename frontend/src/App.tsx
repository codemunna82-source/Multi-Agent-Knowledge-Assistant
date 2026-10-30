import { useCallback, useEffect, useState } from "react";
import { Admin } from "./Admin";
import { Analyst } from "./Analyst";
import { api, hasToken, setToken, silentRefresh } from "./api";
import { Chat } from "./Chat";
import { Compare } from "./Compare";
import { Dashboard } from "./Dashboard";
import { Documents } from "./Documents";
import { Evaluation } from "./Evaluation";
import { ExactSearch } from "./ExactSearch";
import { History } from "./History";
import { Login } from "./Login";
import { Reports } from "./Reports";
import { Settings } from "./Settings";
import { applyTheme, loadTheme } from "./theme";
import type { Health, Role, User } from "./types";

type Page = "dashboard" | "documents" | "chat" | "search" | "compare" | "analyst" | "reports" | "history" | "evaluation" | "settings" | "admin";
const DEV_USER: User = { id: "anonymous", tenant_id: "default", email: "anonymous@local", role: "admin" };
const WS_RE = /^[A-Za-z0-9_-]{1,64}$/;
const RANK: Record<Role, number> = { user: 0, manager: 1, admin: 2 };

export function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [booting, setBooting] = useState(true);
  const [page, setPage] = useState<Page>("dashboard");
  const [workspace, setWorkspace] = useState(() => { try { return localStorage.getItem("mka_ws") ?? "default"; } catch { return "default"; } });
  const [wsDraft, setWsDraft] = useState(workspace);
  const [prefill, setPrefill] = useState<string | null>(null);
  const [fatal, setFatal] = useState<string | null>(null);

  useEffect(() => {
    applyTheme(loadTheme());
    (async () => {
      try {
        const h = await api.health();
        setHealth(h);
        if (!h.auth_enabled) setUser(DEV_USER);
        else {
          // the access token is kept in memory only: after a reload, the httpOnly refresh cookie gives a new one
          if (!hasToken()) await silentRefresh(true);
          if (hasToken()) { try { setUser(await api.me()); } catch { setToken(null); } }
        }
      } catch (e) { setFatal(e instanceof Error ? e.message : "Cannot reach the API"); } finally { setBooting(false); }
    })();
  }, []);

  const applyWs = useCallback(() => {
    if (WS_RE.test(wsDraft)) { setWorkspace(wsDraft); try { localStorage.setItem("mka_ws", wsDraft); } catch { /* ignore */ } } else setWsDraft(workspace);
  }, [wsDraft, workspace]);

  if (booting) return <div className="page muted">Loading…</div>;
  if (fatal) return <div className="page error" role="alert">Cannot reach the API: {fatal}</div>;
  if (!user) return <Login onUser={setUser} allowSignup />;

  const atLeast = (r: Role) => RANK[user.role] >= RANK[r];
  const nav: [Page, string, boolean][] = [
    ["dashboard", "Dashboard", true], ["documents", "Library", true], ["chat", "Chat", true], ["search", "Exact search", true], ["compare", "Compare", true], ["analyst", "Data analyst", true],
    ["reports", "Reports", true], ["history", "History", true], ["evaluation", "Evaluation", atLeast("manager")], ["settings", "Settings", true], ["admin", "Admin", atLeast("admin")],
  ];
  const go = (p: string) => setPage(p as Page);

  return (
    <div className="shell">
      {!health?.auth_enabled && <div className="banner">Development mode: authentication is disabled, everyone is an admin of tenant “default”. Enable MKA_AUTH_ENABLED for real deployments.</div>}
      <header className="top">
        <span className="brand">📚 Knowledge Intelligence</span>
        <nav className="tabs" aria-label="Sections">{nav.filter((n) => n[2]).map(([p, label]) => <button key={p} className={page === p ? "on" : ""} aria-current={page === p ? "page" : undefined} onClick={() => setPage(p)}>{label}</button>)}</nav>
        <span className="grow" />
        <form className="row" onSubmit={(e) => { e.preventDefault(); applyWs(); }}>
          <label htmlFor="ws" style={{ margin: 0 }}>Workspace</label>
          <input id="ws" type="text" value={wsDraft} onChange={(e) => setWsDraft(e.target.value)} onBlur={applyWs} style={{ width: 130 }} />
        </form>
        <span className="muted small">{user.email} · {user.role}</span>
        {health?.auth_enabled && <button className="small" onClick={async () => { try { await api.logout(); } catch { /* ignore */ } setToken(null); setUser(null); }}>Sign out</button>}
      </header>
      <main className="page">
        {page === "dashboard" && <Dashboard workspace={workspace} user={user} health={health} go={go} />}
        {page === "documents" && <Documents workspace={workspace} canIngest={atLeast("manager")} canShare={atLeast("manager")} onAsk={(q) => { setPrefill(q); setPage("chat"); }} />}
        {page === "chat" && <Chat workspace={workspace} prefill={prefill} onPrefillUsed={() => setPrefill(null)} />}
        {page === "search" && <ExactSearch workspace={workspace} />}
        {page === "compare" && <Compare workspace={workspace} />}
        {page === "analyst" && <Analyst workspace={workspace} />}
        {page === "reports" && <Reports workspace={workspace} />}
        {page === "history" && <History workspace={workspace} />}
        {page === "evaluation" && atLeast("manager") && <Evaluation />}
        {page === "settings" && <Settings user={user} authEnabled={Boolean(health?.auth_enabled)} />}
        {page === "admin" && atLeast("admin") && <Admin me={user} />}
      </main>
    </div>
  );
}
