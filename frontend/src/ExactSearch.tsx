import { useState } from "react";
import { api } from "./api";
import { Preview } from "./Preview";
import type { Citation, ExactResult, SourceInfo } from "./types";
import { Pager, errText, useLoad } from "./ui";

const LIMIT = 20;

export function ExactSearch({ workspace }: { workspace: string }) {
  const sources = useLoad(() => api.sources(workspace), [workspace]);
  const [term, setTerm] = useState("");
  const [caseSensitive, setCaseSensitive] = useState(false);
  const [wholeWord, setWholeWord] = useState(true);
  const [selected, setSelected] = useState<string[]>([]);
  const [res, setRes] = useState<ExactResult | null>(null);
  const [offset, setOffset] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [cite, setCite] = useState<Citation | null>(null);
  const byName = new Map<string, SourceInfo>((sources.data?.items ?? []).map((s) => [s.name, s]));

  async function run(off = 0, t = term) {
    if (!t.trim()) return;
    setBusy(true);
    setErr(null);
    try { setRes(await api.exact(workspace, { term: t.trim(), source_ids: selected.length ? selected : undefined, case_sensitive: caseSensitive, whole_word: wholeWord }, LIMIT, off)); setOffset(off); }
    catch (e) { setErr(errText(e)); setRes(null); } finally { setBusy(false); }
  }
  const open = (source: string, page: number, excerpt: string) => { const s = byName.get(source); if (s) setCite({ source_id: s.id, source, location: `page ${page}`, excerpt, loc: { page } }); };

  return (
    <div>
      <form className="card" onSubmit={(e) => { e.preventDefault(); void run(0); }} aria-label="Exact search">
        <h2 style={{ marginTop: 0 }}>Exact search</h2>
        <p className="muted small">Finds every literal occurrence of a name, number, ID or phrase in the complete extracted text — not a sample — with counts and page numbers.</p>
        <div className="row">
          <input type="text" aria-label="Search term" placeholder="e.g. Anjali Rao, INV-2041, clause 8.2" value={term} onChange={(e) => setTerm(e.target.value)} style={{ flex: 1, minWidth: 240 }} />
          <button className="primary" disabled={busy || !term.trim()}>{busy ? "Searching…" : "Search"}</button>
        </div>
        <div className="row small" style={{ marginTop: 8 }}>
          <label className="row" style={{ margin: 0 }}><input type="checkbox" checked={caseSensitive} onChange={(e) => setCaseSensitive(e.target.checked)} />Case-sensitive</label>
          <label className="row" style={{ margin: 0 }}><input type="checkbox" checked={wholeWord} onChange={(e) => setWholeWord(e.target.checked)} />Whole word</label>
          <span className="muted">Limit to:</span>
          {(sources.data?.items ?? []).slice(0, 12).map((s) => (
            <label key={s.id} className="row" style={{ margin: 0 }}><input type="checkbox" checked={selected.includes(s.id)} onChange={() => setSelected(selected.includes(s.id) ? selected.filter((x) => x !== s.id) : [...selected, s.id])} />{s.name}</label>
          ))}
        </div>
        {err && <div className="error" role="alert">{err}</div>}
      </form>
      {res && (
        <div className="card" aria-label="Search results">
          <h2 style={{ marginTop: 0 }}>“{res.term}” — {res.count} occurrence{res.count === 1 ? "" : "s"} in {res.locations_with_match} location{res.locations_with_match === 1 ? "" : "s"}</h2>
          <p className="muted small">{res.rules}. Searched {res.sources_searched} document(s).</p>
          {res.count === 0 && <p>No occurrences found in the extracted text. (Scanned pages need OCR to be searchable.)</p>}
          {res.by_source.length > 0 && (
            <table><thead><tr><th>Document</th><th>Occurrences</th><th>Pages</th></tr></thead>
              <tbody>{res.by_source.map((b) => (
                <tr key={b.name}><td>{b.name}</td><td>{b.count}</td>
                  <td>{(res.pages[b.name] ?? []).map((p) => <button key={p} className="small" style={{ marginRight: 4 }} onClick={() => open(b.name, p, res.term)} aria-label={`Open page ${p} of ${b.name}`}>{p}</button>)}</td></tr>
              ))}</tbody></table>
          )}
          {res.matches.length > 0 && (
            <>
              <h3>Matches</h3>
              {res.matches.map((m, i) => (
                <div className="cite" key={`${m.source_id}-${offset + i}`}>
                  <b>{m.source} — {m.location}</b>
                  <div>{m.excerpt}</div>
                  <button className="small" onClick={() => setCite({ source_id: m.source_id, source: m.source, location: m.location, excerpt: m.excerpt, loc: m.loc })}>Open in context</button>
                </div>
              ))}
              <Pager total={res.count} limit={LIMIT} offset={offset} onChange={(o) => void run(o, res.term)} />
            </>
          )}
        </div>
      )}
      {cite && <Preview workspace={workspace} citation={cite} onClose={() => setCite(null)} />}
    </div>
  );
}
