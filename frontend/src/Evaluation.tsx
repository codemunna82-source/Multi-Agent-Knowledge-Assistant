import { useState } from "react";
import { api } from "./api";
import type { EvalReport } from "./types";
import { Bar, num, pct, useLoad } from "./ui";

export function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return <div className="tile"><span>{label}</span><b>{value}</b>{hint && <span>{hint}</span>}</div>;
}

export function ReportView({ rep }: { rep: EvalReport }) {
  const m = rep.metrics;
  const r = m.retrieval;
  return (
    <div aria-label="Evaluation report">
      <p className="muted small">Dataset <code>{rep.dataset}</code> · {m.cases} cases · {rep.created} · embedder <code>{rep.config.embedder}</code> · LLM <code>{rep.config.llm}</code> · {rep.config.vector_store}</p>
      <div className="tiles">
        <Tile label="Recall@5" value={pct(r["recall@5"])} hint="gold passages found in top 5" />
        <Tile label="Precision@5" value={pct(r["precision@5"])} hint="relevant results ÷ 5" />
        <Tile label="MRR" value={num(r.mrr)} hint="first relevant rank" />
        <Tile label="Faithfulness*" value={pct(m.answers["faithfulness_lexical (proxy)"])} hint="lexical proxy, not RAGAS" />
        <Tile label="Answer relevancy*" value={pct(m.answers["answer_relevancy_embedding (proxy)"])} hint="embedding proxy, not RAGAS" />
        <Tile label="Latency p50 / p95" value={`${num(m.latency_ms.p50, 0)} / ${num(m.latency_ms.p95, 0)} ms`} />
        <Tile label="Tokens / query" value={num(m.tokens.per_query, 0)} hint={m.tokens.estimated ? "estimated" : "provider-reported"} />
        <Tile label="Cost / query" value={`$${m.cost_usd.per_query.toFixed(5)}`} hint={`total $${m.cost_usd.total.toFixed(4)}`} />
      </div>
      <h2>Retrieval</h2>
      <table><thead><tr><th>K</th><th>Recall@K</th><th>Precision@K</th><th>nDCG@K</th></tr></thead>
        <tbody>{[1, 3, 5].map((k) => <tr key={k}><td>{k}</td><td><Bar value={r[`recall@${k}`]} /></td><td><Bar value={r[`precision@${k}`]} /></td><td>{num(r[`ndcg@${k}`])}</td></tr>)}</tbody></table>
      <h2>Answers</h2>
      <table><tbody>{Object.entries(m.answers).map(([k, v]) => <tr key={k}><td>{k}</td><td><Bar value={v} /></td></tr>)}</tbody></table>
      <h2>By question type</h2>
      <table><thead><tr><th>Type</th><th>Cases</th><th>Correct</th><th>Recall@5</th><th>MRR</th><th>Route acc.</th><th>p50 ms</th></tr></thead>
        <tbody>{Object.entries(m.by_type).map(([t, d]) => <tr key={t}><td>{t}</td><td>{d.cases}</td><td><Bar value={d.correct} /></td><td><Bar value={d["recall@5"]} /></td><td>{num(d.mrr)}</td><td><Bar value={d.route_accuracy} /></td><td>{num(d.latency_p50_ms, 1)}</td></tr>)}</tbody></table>
      {rep.comparison && (<>
        <h2>Strategy comparison</h2>
        <table><thead><tr><th>Strategy</th><th>Recall@5</th><th>Precision@5</th><th>MRR</th><th>nDCG@5</th><th>p50 ms</th><th>p95 ms</th></tr></thead>
          <tbody>{rep.comparison.map((c) => <tr key={c.strategy}><td>{c.strategy}</td><td><Bar value={c["recall@5"]} /></td><td><Bar value={c["precision@5"]} /></td><td>{num(c.mrr)}</td><td>{num(c["ndcg@5"])}</td><td>{num(c.p50_ms, 1)}</td><td>{num(c.p95_ms, 1)}</td></tr>)}</tbody></table>
      </>)}
      <h2>Failures ({rep.failures.length})</h2>
      <ul>{rep.failures.map((f) => <li key={f.id}><code>{f.id}</code> {f.question} — <span className="bad">{f.why.join(", ")}</span></li>)}{!rep.failures.length && <li>None</li>}</ul>
      <ul className="muted small">{rep.notes.map((n) => <li key={n}>{n}</li>)}</ul>
    </div>
  );
}

export function Evaluation() {
  const runs = useLoad(() => api.evalRuns(), []);
  const [report, setReport] = useState<EvalReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function runSample() {
    setBusy(true);
    setErr(null);
    try { const r = await api.runEval({ sample: true, compare_strategies: true, name: "Sample corpus" }); setReport(r); void runs.reload(); } catch (e) { setErr(e instanceof Error ? e.message : "Failed"); } finally { setBusy(false); }
  }
  async function open(id: string) {
    try { setReport(await api.evalRun(id)); } catch (e) { setErr(e instanceof Error ? e.message : "Failed"); }
  }

  return (
    <div>
      <div className="card">
        <div className="row"><h2 style={{ margin: 0 }}>Evaluation</h2><span className="grow" />
          <button className="primary" onClick={() => void runSample()} disabled={busy}>{busy ? "Running…" : "Run sample evaluation"}</button></div>
        <p className="muted small">Runs the built-in synthetic corpus (PDF, DOCX, XLSX, CSV, MD, TXT, JSON) through the real pipeline in a throw-away workspace and compares retrieval strategies. To evaluate your own documents, POST a dataset to <code>/eval/run</code>.</p>
        {err && <div className="error" role="alert">{err}</div>}
        <table><thead><tr><th>Run</th><th>When</th><th>Cases</th><th>Recall@5</th><th>MRR</th><th>p50 ms</th><th /></tr></thead>
          <tbody>{(runs.data ?? []).map((r) => <tr key={r.id}><td>{r.name}</td><td className="small">{r.created_at}</td><td>{r.cases}</td><td>{pct(r["recall@5"])}</td><td>{num(r.mrr)}</td><td>{num(r.latency_p50, 1)}</td><td><button className="small" onClick={() => void open(r.id)}>Open</button></td></tr>)}
            {!runs.data?.length && <tr><td colSpan={7} className="muted">No runs yet.</td></tr>}</tbody></table>
      </div>
      {report && <div className="card"><h2 style={{ marginTop: 0 }}>{report.name}</h2><ReportView rep={report} /></div>}
    </div>
  );
}
