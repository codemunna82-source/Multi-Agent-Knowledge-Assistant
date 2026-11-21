import { useMemo, useState } from "react";
import type { Conversation } from "./types";

type Group = "Today" | "Yesterday" | "Previous 7 days" | "Older";
const ORDER: Group[] = ["Today", "Yesterday", "Previous 7 days", "Older"];

/** Server timestamps may come without a zone; treat those as UTC. An unparseable or empty value counts as Older. */
function when(iso: string): number {
  if (!iso) return NaN;
  return Date.parse(/(Z|[+-]\d\d:?\d\d)$/.test(iso) ? iso : iso + "Z");
}

export function groupByDay(items: Conversation[], now = new Date()): [Group, Conversation[]][] {
  const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const DAY = 86_400_000;
  const buckets: Record<Group, Conversation[]> = { Today: [], Yesterday: [], "Previous 7 days": [], Older: [] };
  for (const c of [...items].sort((a, b) => (when(b.updated_at) || 0) - (when(a.updated_at) || 0))) {
    const t = when(c.updated_at);
    const g: Group = Number.isNaN(t) ? "Older" : t >= startToday ? "Today" : t >= startToday - DAY ? "Yesterday" : t >= startToday - 7 * DAY ? "Previous 7 days" : "Older";
    buckets[g].push(c);
  }
  return ORDER.filter((g) => buckets[g].length).map((g) => [g, buckets[g]]);
}

export function ConversationList({ items, active, onOpen, onNew, onDelete }: { items: Conversation[]; active: string | null; onOpen: (id: string) => void; onNew: () => void; onDelete: (c: Conversation) => void }) {
  const [q, setQ] = useState("");
  const [confirm, setConfirm] = useState<string | null>(null);
  const shown = useMemo(() => items.filter((c) => !q.trim() || (c.title || "Untitled").toLowerCase().includes(q.trim().toLowerCase())), [items, q]);
  const groups = useMemo(() => groupByDay(shown), [shown]);

  return (
    <>
      <button className="new" onClick={onNew}>+ New conversation</button>
      {items.length > 0 && (
        <input className="conv-search" type="search" placeholder="Search chats" aria-label="Search conversations" value={q} onChange={(e) => setQ(e.target.value)} />
      )}
      <div className="convs" role="list">
        {groups.map(([g, list]) => (
          <section key={g} aria-label={g}>
            <h3>{g}</h3>
            {list.map((c) => (
              <div key={c.id} role="listitem" className={`conv-row ${c.id === active ? "on" : ""}`}>
                {confirm === c.id ? (
                  <div className="conv-confirm" role="group" aria-label={`Delete ${c.title || "Untitled"}?`}>
                    <span>Delete this chat?</span>
                    <button className="small danger" onClick={() => { setConfirm(null); onDelete(c); }}>Delete</button>
                    <button className="small" onClick={() => setConfirm(null)}>Cancel</button>
                  </div>
                ) : (
                  <>
                    <button className="conv-title" aria-current={c.id === active ? "true" : undefined} onClick={() => onOpen(c.id)} title={c.title}>{c.title || "Untitled"}</button>
                    <button className="small danger x" aria-label={`Delete conversation ${c.title}`} onClick={() => setConfirm(c.id)}>×</button>
                  </>
                )}
              </div>
            ))}
          </section>
        ))}
        {!items.length && <div className="conv-empty"><b>No conversations yet</b><span className="muted small">Your chats appear here. Ask your first question to start one.</span></div>}
        {items.length > 0 && !shown.length && <span className="muted small">No chats match “{q}”.</span>}
      </div>
    </>
  );
}
