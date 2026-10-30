import { useState } from "react";
import { api } from "./api";
import { CitationList } from "./Chat";
import { Preview } from "./Preview";
import type { Citation, Conversation, Message } from "./types";
import { Badge, errText, useLoad } from "./ui";

export function History({ workspace }: { workspace: string }) {
  const convs = useLoad(() => api.conversations(workspace), [workspace]);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<Conversation | null>(null);
  const [msgs, setMsgs] = useState<Message[]>([]);
  const [cite, setCite] = useState<Citation | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const items = (convs.data?.items ?? []).filter((c) => (c.title || "").toLowerCase().includes(q.toLowerCase()));

  async function show(c: Conversation) {
    setOpen(c); setErr(null);
    try { setMsgs(await api.messages(workspace, c.id)); } catch (e) { setErr(errText(e)); }
  }
  async function patch(c: Conversation, body: { title?: string; memory_enabled?: boolean }) {
    try { const u = await api.patchConversation(workspace, c.id, body); setOpen(u); void convs.reload(); } catch (e) { setErr(errText(e)); }
  }
  return (
    <div className="split">
      <aside className="card" aria-label="Conversation history">
        <h2 style={{ marginTop: 0 }}>History</h2>
        <input type="text" placeholder="search titles…" aria-label="Search conversations" value={q} onChange={(e) => setQ(e.target.value)} />
        <div className="col" style={{ marginTop: 8 }}>
          {items.map((c) => (
            <div key={c.id} className="row" style={{ flexWrap: "nowrap" }}>
              <button className={`grow left ${open?.id === c.id ? "on" : ""}`} onClick={() => void show(c)} title={c.title}>{c.title || "Untitled"}<br /><span className="muted small">{c.updated_at.slice(0, 16).replace("T", " ")}</span></button>
              <button className="small danger" aria-label={`Delete conversation ${c.title}`} onClick={async () => { if (confirm(`Delete “${c.title}” and its messages?`)) { await api.deleteConversation(workspace, c.id); if (open?.id === c.id) setOpen(null); void convs.reload(); } }}>×</button>
            </div>
          ))}
          {!items.length && <span className="muted small">{q ? "No match." : "No conversations yet."}</span>}
        </div>
      </aside>
      <section className="card">
        {!open && <p className="muted">Choose a conversation to read it.</p>}
        {open && (
          <>
            <div className="row"><h2 style={{ margin: 0 }}>{open.title || "Untitled"}</h2>{open.memory_enabled === false && <Badge kind="none">private</Badge>}<span className="grow" />
              <button className="small" onClick={() => { const t = prompt("Rename conversation", open.title); if (t) void patch(open, { title: t }); }}>Rename</button>
              <button className="small" onClick={() => void patch(open, { memory_enabled: open.memory_enabled === false })}>{open.memory_enabled === false ? "Resume memory" : "Make private (stop remembering)"}</button></div>
            {err && <div className="error" role="alert">{err}</div>}
            <div className="log" aria-label="Messages">
              {msgs.map((m) => (
                <div key={m.id} className={`msg ${m.role}`}>
                  {m.content}
                  {m.meta?.citations && <CitationList citations={m.meta.citations} onOpen={setCite} />}
                </div>
              ))}
            </div>
          </>
        )}
      </section>
      {cite && <Preview workspace={workspace} citation={cite} onClose={() => setCite(null)} />}
    </div>
  );
}
