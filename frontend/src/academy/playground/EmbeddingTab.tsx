import { useState } from "react";
import { academy } from "../../api";
import { errText } from "../../ui";
import type { EmbedRun, PgCaps } from "../types";
import { fmt } from "./common";

const START = "How do I quit my job?\nOur resignation procedure and notice period\nThe company pizza party is on Friday\nReset your laptop password";

/** Embedding playground: embed 2-10 sentences with the configured embedder, then see dimensions, the similarity matrix and the ranking against the first sentence. */
export function EmbeddingPlayground({ caps }: { ws: string; caps: PgCaps | null }) {
  const [text, setText] = useState(START);
  const [out, setOut] = useState<EmbedRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const texts = text.split("\n").map((t) => t.trim()).filter(Boolean);
  async function go() { setBusy(true); setErr(null); try { setOut(await academy.pgEmbed(texts)); } catch (e) { setErr(errText(e)); } finally { setBusy(false); } }
  return (
    <section aria-label="Embedding playground">
      <h2>Embedding playground</h2>
      <p className="muted small">One sentence per line (2 to 10). The first line is the query; the others are compared with it. Embedder: <b>{caps?.embedder.name ?? "…"}</b>.</p>
      {caps && !caps.embedder.semantic && <p className="ac-setup small" role="note">{caps.embedder.note}</p>}
      <label htmlFor="pg-emb">Sentences</label>
      <textarea id="pg-emb" rows={6} value={text} onChange={(e) => setText(e.target.value)} />
      <div className="viz-controls"><button className="primary" disabled={busy || texts.length < 2 || texts.length > 10} onClick={() => void go()}>{busy ? "Embedding…" : "Generate embeddings"}</button><span className="muted small">{texts.length} sentence(s)</span></div>
      {err && <div className="error" role="alert">{err}</div>}
      {out && (
        <div>
          <p className="small"><b>{out.dim}</b> numbers per vector · {out.latency_ms} ms · embedder {out.embedder}</p>
          {out.note && <p className="warn small">{out.note}</p>}
          <h3>Ranking against the first sentence</h3>
          <div className="bars" role="table" aria-label="Similarity to the first sentence">
            {out.ranking_vs_first.map((r) => <div key={r.index} className="bar-row" role="row"><span className="bar-label wide" role="cell">{r.text}</span><span className="bar-track" role="cell"><i className="bar-final" style={{ width: `${Math.max(0, r.cosine) * 100}%` }} /></span><span role="cell" className="small">{fmt(r.cosine)}</span></div>)}
          </div>
          <h3>Similarity matrix (cosine)</h3>
          <div className="scroll"><table aria-label="Cosine similarity matrix"><thead><tr><th />{out.texts.map((_, j) => <th key={j}>{j + 1}</th>)}</tr></thead>
            <tbody>{out.similarity.map((row, i) => <tr key={i}><th title={out.texts[i]}>{i + 1}</th>{row.map((v, j) => <td key={j} style={{ background: `rgba(59,91,219,${Math.max(0, v)})`, color: v > 0.55 ? "#fff" : undefined }}>{fmt(v)}</td>)}</tr>)}</tbody></table></div>
          <details><summary className="small">First 8 numbers of each vector</summary><pre className="out">{out.vectors.map((v, i) => `${i + 1}. [${v.first_values.join(", ")} …]  length ${v.norm}`).join("\n")}</pre></details>
        </div>
      )}
    </section>
  );
}
