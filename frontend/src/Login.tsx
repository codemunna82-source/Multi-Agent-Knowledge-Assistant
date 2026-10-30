import { useState } from "react";
import { api, setToken } from "./api";
import type { User } from "./types";

export function Login({ onUser, allowSignup }: { onUser: (u: User) => void; allowSignup: boolean }) {
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [tenant, setTenant] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const r = mode === "login" ? await api.login(email, password) : await api.signup(tenant, email, password);
      setToken(r.access_token);
      onUser(r.user);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card login col" onSubmit={submit} aria-label={mode}>
      <h1>{mode === "login" ? "Sign in" : "Create your organisation"}</h1>
      {mode === "signup" && (
        <div><label htmlFor="tenant">Organisation name</label><input id="tenant" type="text" value={tenant} onChange={(e) => setTenant(e.target.value)} required minLength={2} /></div>
      )}
      <div><label htmlFor="email">Email</label><input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="username" /></div>
      <div><label htmlFor="pw">Password</label><input id="pw" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={mode === "signup" ? 10 : 1} autoComplete={mode === "login" ? "current-password" : "new-password"} /></div>
      {err && <div className="error" role="alert">{err}</div>}
      <button className="primary" disabled={busy}>{mode === "login" ? "Sign in" : "Create account"}</button>
      {allowSignup && (
        <button type="button" className="small" onClick={() => setMode(mode === "login" ? "signup" : "login")}>
          {mode === "login" ? "New organisation? Sign up" : "Have an account? Sign in"}
        </button>
      )}
      {mode === "signup" && <span className="muted small">Passwords need at least 10 characters.</span>}
    </form>
  );
}
