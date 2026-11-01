import { useState } from "react";
import { academy } from "../../api";
import { errText } from "../../ui";
import type { PgCaps, RagRun } from "../types";
import { fmt, Unavailable } from "./common";

const SAMPLE = "Employees accrue 25 days of annual leave per year. Unused leave can be carried over for up to 5 days. Parental leave is 26 weeks for the primary caregiver and 4 weeks for the partner. Expense reports must be filed within 30 days of travel. Travel above 500 dollars needs manager approval.";

/** RAG playground: upload a PDF/TXT/CSV (or paste text), tune chunking and retrieval, and inspect every stage including reranking before and after. Nothing is stored. */
export function RagPlayground({ ws: _ws, caps }: { ws: string; caps: PgCaps | null }) {
  const [file, setFile] = useState<File | null>(null);
  const [text, setText] = useState(SAMPLE);
  const [question, setQuestion] = useState("How long is parental leave?");
  const [size, setSize] = useState(120);
  const [overlap, setOverlap] = useState(20);
  const [topK, setTopK] = useState(3);
  const [mode, setMode] = useState("hybrid");
  const [rerank, setRerank] = useState("lexical");
  const [answer, setAnswer] = useState(true);
  const [out, setOut] = useState<RagRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function go() {
    setBusy(true); setErr(null);
    const f = new FormData();
    if (file) f.append("file", file); else f.append("text", text);
    f.append("question", question); f.append("chunk_size", String(size)); f.append("chunk_overlap", String(overlap)); f.append("top_k", String(topK)); f.append("mode", mode); f.append("rerank", rerank); f.append("answer", String(answer));
    try { setOut(await academy.pgRag(f)); } catch (e) { setErr(errText(e)); setOut(null); } finally { setBusy(false); }
  }
  const stage = (n: string, title: string, body: React.ReactNode, open = false) => <details className="ac-stage" open={open}><summary><b>{n}. {title}</b></summary>{body}</details>;
  const maxLen = Math.max(1, ...(out?.chunks.lengths ?? [1]));
  return (
    <section aria-label="RAG playground">
      <h2>RAG playground</h2>
      <p className="muted small">An ephemeral pipeline: nothing you upload is stored or indexed. PDF, TXT, CSV or MD up to 2 MB (scanned PDFs need OCR, which is off here).</p>
      <div className="viz-inputs">
        <div><label htmlFor="rag-file">Upload a file</label><input id="rag-file" type="file" accept=".pdf,.txt,.csv,.md" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />{file && <button className="small" onClick={() => setFile(null)}>Use pasted text instead</button>}</div>
        <div><label htmlFor="rag-text">…or paste text</label><textarea id="rag-text" rows={4} value={text} disabled={Boolean(file)} onChange={(e) => setText(e.target.value)} /></div>
        <div><label htmlFor="rag-q">Question</label><input id="rag-q" value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={500} /></div>
        <div><label htmlFor="rag-size">Chunk size: {size}</label><input id="rag-size" type="range" min={100} max={1500} step={10} value={size} onChange={(e) => setSize(Number(e.target.value))} /></div>
        <div><label htmlFor="rag-ov">Overlap: {overlap}</label><input id="rag-ov" type="range" min={0} max={Math.min(300, size - 10)} step={5} value={Math.min(overlap, size - 10)} onChange={(e) => setOverlap(Number(e.target.value))} /></div>
        <div><label htmlFor="rag-k">Top-k: {topK}</label><input id="rag-k" type="range" min={1} max={8} value={topK} onChange={(e) => setTopK(Number(e.target.value))} /></div>
        <div><label htmlFor="rag-mode">Search</label><select id="rag-mode" value={mode} onChange={(e) => setMode(e.target.value)}><option value="hybrid">Hybrid (vector + keyword, RRF)</option><option value="vector">Vector only</option><option value="keyword">Keyword (BM25) only</option></select></div>
        <div><label htmlFor="rag-rr">Reranking</label><select id="rag-rr" value={rerank} onChange={(e) => setRerank(e.target.value)}><option value="none">None</option><option value="lexical">Lexical</option><option value="cross_encoder">Cross-encoder{caps && !caps.cross_encoder.available ? " (not installed: falls back)" : ""}</option></select></div>
      </div>
      <div className="viz-controls"><label className="check"><input type="checkbox" checked={answer} onChange={(e) => setAnswer(e.target.checked)} />Generate a grounded answer with citations</label><button className="primary" disabled={busy || !question.trim() || (!file && !text.trim())} onClick={() => void go()}>{busy ? "Running…" : "▶ Run the pipeline"}</button></div>
      {err && <div className="error" role="alert">{err}</div>}
      {out && (
        <div aria-label="Pipeline stages">
          {stage("1", "Document loading", <><p className="small">{out.extract.file}: {out.extract.units} unit(s), {out.extract.chars.toLocaleString()} characters.</p><pre className="out">{out.extract.preview}</pre>{out.extract.warnings.map((w) => <p key={w} className="warn small">{w}</p>)}</>)}
          {stage("2", "Chunking", <><p className="small"><b>{out.chunks.count}</b> chunks (size {out.chunks.size}, overlap {out.chunks.overlap}).</p>
            <div className="chunk-bars" aria-label="Chunk lengths">{out.chunks.lengths.map((l, i) => <i key={i} title={`chunk ${i + 1}: ${l} chars`} style={{ height: `${(l / maxLen) * 100}%` }} />)}</div>
            <ol className="ac-chunks">{out.chunks.items.map((c) => <li key={c.id} value={c.id}><span className="muted small">{c.location} · {c.chars} chars</span> {c.text}</li>)}</ol>{out.chunks.truncated_list && <p className="muted small">Only the first 60 are listed.</p>}</>, true)}
          {stage("3", "Embedding generation", <><p className="small">{out.embed.embedder}: {out.embed.dim} numbers per chunk, {out.embed.ms} ms.</p>{out.embed.note && <p className="warn small">{out.embed.note}</p>}</>)}
          {stage("4", "Vector storage", <p className="small">{out.store.vectors} vectors ({Math.round(out.store.bytes / 1024)} KB). {out.store.note}</p>)}
          {stage("5", `Search (${out.search.mode}), top ${out.search.top.length}`, <table aria-label="Search results"><thead><tr><th>#</th><th>Chunk</th><th>Cosine</th><th>BM25</th><th>Score</th><th>Text</th></tr></thead><tbody>{out.search.top.map((t) => <tr key={t.chunk}><td>{t.rank}</td><td>{t.chunk}</td><td>{fmt(t.cosine, 3)}</td><td>{fmt(t.bm25)}</td><td>{fmt(t.score, 4)}</td><td className="small">{t.text}</td></tr>)}</tbody></table>, true)}
          {stage("6", `Reranking: ${out.rerank.method}`, <><p className="small">Before: chunks {out.rerank.before.join(", ")} → after: chunks <b>{out.rerank.after.join(", ")}</b>{out.rerank.moved.length ? ` (changed: ${out.rerank.moved.join(", ")})` : " (same order)"}</p>
            <table aria-label="Reranking results"><thead><tr><th>Now</th><th>Chunk</th><th>Was</th><th>Rerank score</th><th>Text</th></tr></thead><tbody>{out.rerank.items.map((r) => <tr key={r.chunk} className={r.was_rank !== r.rank ? "picked" : ""}><td>{r.rank}</td><td>{r.chunk}</td><td>{r.was_rank}</td><td>{r.rerank_score === null ? "–" : fmt(r.rerank_score, 3)}</td><td className="small">{r.text}</td></tr>)}</tbody></table></>, true)}
          {stage("7", "Context construction", <pre className="out">{out.context.prompt}</pre>)}
          {out.answer && stage("8", "Grounded answer", <><div className="ac-output" aria-label="Answer">{out.answer.text}</div><p className="muted small">{out.answer.method}{out.answer.usage?.completion_tokens ? ` · ${out.answer.usage.completion_tokens} tokens` : ""}</p>
            {out.answer.citations.length > 0 ? <p className="small">Citations: {out.answer.citations.map((c) => `[${c.n}] chunk ${c.chunk} (${c.location})`).join(" · ")}</p> : out.answer.found ? <p className="warn small">The answer cites no source.</p> : null}</>, true)}
          {!out.answer && <Unavailable what="Answer generation" />}
          <p className="muted small">Total {out.total_ms} ms.</p>
        </div>
      )}
    </section>
  );
}
