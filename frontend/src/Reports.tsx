import { useState } from "react";
import { api, saveBlob } from "./api";
import type { ReportItem } from "./types";
import { Badge, Pager, errText, useLoad } from "./ui";

const KINDS: [string, string][] = [["summary", "Summary"], ["executive", "Executive summary"], ["comparison", "Comparison"], ["research", "Research (questions)"], ["analytics", "Data analysis"], ["exact_search", "Exact search"]];
const PER = 20;

export function Reports({ workspace }: { workspace: string }) {
  const [offset, setOffset] = useState(0);
  const list = useLoad(() => api.reports(workspace), [workspace]);
  const sources = useLoad(() => api.sources(workspace, { limit: 200 }), [workspace]);
  const [kind, setKind] = useState("summary");
  const [format, setFormat] = useState("pdf");
  const [picked, setPicked] = useState<string[]>([]);
  const [style, setStyle] = useState("detailed");
  const [mode, setMode] = useState("diff");
  const [term, setTerm] = useState("");
  const [questions, setQuestions] = useState("");
  const [queries, setQueries] = useState("");
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const docs = (sources.data?.items ?? []).filter((s) => (kind === "analytics" ? s.tabular : kind === "comparison" ? !s.tabular : true));
  const toggle = (id: string) => setPicked(picked.includes(id) ? picked.filter((x) => x !== id) : [...picked, id]);

  async function create() {
    setBusy(true); setErr(null); setOk(null);
    const params: Record<string, unknown> = {};
    if (kind === "summary") params.style = style;
    if (kind === "comparison") params.mode = mode;
    if (kind === "exact_search") params.term = term;
    if (kind === "research") params.questions = questions.split("\n").map((x) => x.trim()).filter(Boolean);
    if (kind === "analytics" && queries.trim()) params.queries = queries.split("\n").map((x) => x.trim()).filter(Boolean);
    try {
      const r = await api.createReport(workspace, { kind, format, source_ids: picked.length ? picked : undefined, params, title: title || undefined });
      setOk(`Report “${r.title}” is ready.`);
      void list.reload();
    } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  async function download(r: ReportItem) {
    try { saveBlob(await api.downloadReport(workspace, r.id), `${r.title.replace(/[^\w.-]+/g, "_").slice(0, 60)}.${r.format}`); } catch (e) { setErr(errText(e)); }
  }
  const items = list.data?.items ?? [];
  return (
    <div>
      <form className="card" onSubmit={(e) => { e.preventDefault(); void create(); }} aria-label="Create report">
        <h2 style={{ marginTop: 0 }}>Generate a report</h2>
        <div className="row">
          <div><label htmlFor="rk">Report type</label><select id="rk" value={kind} onChange={(e) => { setKind(e.target.value); setPicked([]); }}>{KINDS.map(([k, n]) => <option key={k} value={k}>{n}</option>)}</select></div>
          <div><label htmlFor="rf">Format</label><select id="rf" value={format} onChange={(e) => setFormat(e.target.value)}><option value="pdf">PDF</option><option value="docx">Word (DOCX)</option><option value="xlsx">Excel (XLSX)</option></select></div>
          <div className="grow"><label htmlFor="rt">Title (optional)</label><input id="rt" type="text" value={title} onChange={(e) => setTitle(e.target.value)} /></div>
        </div>
        {kind === "summary" && <div><label htmlFor="rs">Style</label><select id="rs" value={style} onChange={(e) => setStyle(e.target.value)}><option value="short">Short</option><option value="detailed">Detailed</option><option value="chapter">Chapter by chapter</option></select></div>}
        {kind === "comparison" && <div><label htmlFor="rm">Mode</label><select id="rm" value={mode} onChange={(e) => setMode(e.target.value)}><option value="diff">Differences (exactly two documents)</option><option value="contradictions">Contradictions</option></select></div>}
        {kind === "exact_search" && <div><label htmlFor="rterm">Search term</label><input id="rterm" type="text" value={term} onChange={(e) => setTerm(e.target.value)} /></div>}
        {kind === "research" && <div><label htmlFor="rq">Questions (one per line, up to 10)</label><textarea id="rq" rows={4} value={questions} onChange={(e) => setQuestions(e.target.value)} /></div>}
        {kind === "analytics" && <div><label htmlFor="rsql">Optional read-only SQL queries (one per line)</label><textarea id="rsql" rows={2} value={queries} onChange={(e) => setQueries(e.target.value)} /></div>}
        <h3>Documents {picked.length === 0 && <span className="muted">(none selected = all suitable)</span>}</h3>
        <div className="row">{docs.map((s) => <label key={s.id} className="row small" style={{ margin: 0 }}><input type="checkbox" checked={picked.includes(s.id)} onChange={() => toggle(s.id)} />{s.name}</label>)}{!docs.length && <span className="muted small">No suitable documents.</span>}</div>
        {err && <div className="error" role="alert">{err}</div>}
        {ok && <div className="ok" role="status">{ok}</div>}
        <div className="row" style={{ marginTop: 10 }}><button className="primary" disabled={busy}>{busy ? "Generating…" : "Generate report"}</button><span className="muted small">Every report lists its sources and generation time.</span></div>
      </form>
      <div className="card">
        <div className="row"><h2 style={{ margin: 0 }}>Generated reports</h2><span className="grow" /><button className="small" onClick={() => void list.reload()}>Refresh</button></div>
        {list.error && <div className="error" role="alert">{list.error}</div>}
        <table><thead><tr><th>Title</th><th>Type</th><th>Format</th><th>Created</th><th>Size</th><th /></tr></thead>
          <tbody>{items.slice(offset, offset + PER).map((r) => (
            <tr key={r.id}><td>{r.title}</td><td><Badge>{r.kind}</Badge></td><td>{r.format.toUpperCase()}</td><td className="small">{r.created_at.slice(0, 16).replace("T", " ")}</td><td className="small">{r.size_bytes ? `${Math.max(1, Math.round(r.size_bytes / 1024))} KB` : ""}</td>
              <td className="row"><button className="small" onClick={() => void download(r)}>Download</button>
                <button className="small danger" onClick={async () => { if (confirm(`Delete “${r.title}”?`)) { await api.deleteReport(workspace, r.id); void list.reload(); } }}>Delete</button></td></tr>
          ))}
            {!list.loading && !items.length && <tr><td colSpan={6} className="muted">No reports yet.</td></tr>}</tbody></table>
        <Pager total={items.length} limit={PER} offset={offset} onChange={setOffset} />
      </div>
    </div>
  );
}
