import { useState } from "react";
import { api } from "./api";
import type { ContradictionResult, DiffResult, SourceInfo } from "./types";
import { Badge, DataTable, Tabs, errText, useLoad } from "./ui";

type Mode = "diff" | "contradictions" | "versions";
type DiffOut = DiffResult & { left?: { name: string }; right?: { name: string }; document?: string; from_version?: number; to_version?: number };
const isContra = (r: DiffOut | ContradictionResult): r is ContradictionResult => "contradictions" in r;

export function Compare({ workspace }: { workspace: string }) {
  const sources = useLoad(() => api.sources(workspace, { include_versions: false }), [workspace]);
  const docs = (sources.data?.items ?? []).filter((s) => !s.tabular);
  const [mode, setMode] = useState<Mode>("diff");
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [multi, setMulti] = useState<string[]>([]);
  const [out, setOut] = useState<DiffOut | ContradictionResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    setErr(null);
    setOut(null);
    try {
      if (mode === "diff") setOut((await api.compare(workspace, { source_ids: [a, b], mode: "diff" })) as DiffOut);
      else if (mode === "contradictions") setOut((await api.compare(workspace, { source_ids: multi, mode: "contradictions" })) as ContradictionResult);
      else setOut(await api.changes(workspace, a));
    } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  const ready = mode === "diff" ? a && b && a !== b : mode === "contradictions" ? multi.length >= 2 : Boolean(a);
  const pick = (id: string, set: (v: string) => void, label: string, list: SourceInfo[]) => (
    <div><label htmlFor={label}>{label}</label>
      <select id={label} value={id} onChange={(e) => set(e.target.value)}><option value="">Choose…</option>{list.map((s) => <option key={s.id} value={s.id}>{s.name}{s.version && s.version > 1 ? ` (v${s.version})` : ""}</option>)}</select></div>
  );

  return (
    <div>
      <div className="card">
        <h2 style={{ marginTop: 0 }}>Compare documents</h2>
        <Tabs label="Comparison mode" value={mode} onChange={(m) => { setMode(m); setOut(null); }} tabs={[["diff", "Two documents"], ["versions", "Versions of one document"], ["contradictions", "Find contradictions"]]} />
        <div className="row" style={{ marginTop: 10, alignItems: "flex-end" }}>
          {mode === "diff" && <>{pick(a, setA, "Document A", docs)}{pick(b, setB, "Document B", docs)}</>}
          {mode === "versions" && pick(a, setA, "Document", docs.filter((d) => (d.version ?? 1) > 1))}
          {mode === "contradictions" && (
            <div className="col"><span className="small muted">Pick two or more documents</span>
              <div className="row">{docs.map((s) => <label key={s.id} className="row small" style={{ margin: 0 }}><input type="checkbox" checked={multi.includes(s.id)} onChange={() => setMulti(multi.includes(s.id) ? multi.filter((x) => x !== s.id) : [...multi, s.id])} />{s.name}</label>)}</div></div>
          )}
          <button className="primary" disabled={!ready || busy} onClick={() => void run()}>{busy ? "Comparing…" : "Compare"}</button>
        </div>
        {mode === "versions" && !docs.some((d) => (d.version ?? 1) > 1) && <p className="muted small">No document has more than one version yet. Re-upload a changed file with the same name.</p>}
        {err && <div className="error" role="alert">{err}</div>}
      </div>
      {out && !isContra(out) && (
        <div className="card" aria-label="Comparison result">
          <h2 style={{ marginTop: 0 }}>{out.document ? `${out.document}: v${out.from_version} → v${out.to_version}` : `${out.left?.name} ↔ ${out.right?.name}`}</h2>
          <div className="tiles">
            <div className="tile"><b>{Math.round(out.summary.similarity * 100)}%</b><span>similar</span></div><div className="tile"><b>{out.summary.unchanged}</b><span>unchanged</span></div>
            <div className="tile"><b>{out.summary.changed}</b><span>changed</span></div><div className="tile"><b>{out.summary.added}</b><span>only in B / new</span></div><div className="tile"><b>{out.summary.removed}</b><span>only in A / removed</span></div>
          </div>
          {out.changed.length > 0 && <><h3>Changed passages</h3><DataTable columns={["Before", "After", "Numbers"]} rows={out.changed.map((c) => [c.before.text, c.after.text, c.number_changes.map((n) => `${n.from} → ${n.to}`).join(", ")])} /></>}
          {out.added.length > 0 && <><h3>Added</h3><DataTable columns={["Passage"]} rows={out.added.map((x) => [x.text])} /></>}
          {out.removed.length > 0 && <><h3>Removed</h3><DataTable columns={["Passage"]} rows={out.removed.map((x) => [x.text])} /></>}
          {out.truncated && <p className="muted small">Only the first 20,000 sentences of each document were compared.</p>}
        </div>
      )}
      {out && isContra(out) && (
        <div className="card" aria-label="Contradictions">
          <h2 style={{ marginTop: 0 }}>{out.contradictions.length} {out.method === "llm" ? "confirmed" : "candidate"} contradiction(s)</h2>
          <p className="muted small">{out.note}</p>
          {out.contradictions.map((c, i) => (
            <div className="cite" key={i}><Badge>{c.type}</Badge> {c.reason && <span className="small">{c.reason}</span>}
              <div><b>{c.a.source}</b> ({c.a.location}): {c.a.text}</div><div><b>{c.b.source}</b> ({c.b.location}): {c.b.text}</div></div>
          ))}
          {!out.contradictions.length && <p>No contradictions found.</p>}
        </div>
      )}
    </div>
  );
}
