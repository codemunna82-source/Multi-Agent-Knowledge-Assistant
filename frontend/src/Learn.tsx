import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { GraphDiagram } from "./GraphDiagram";
import type { GraphInfo, GraphRun, LabRow, LcDemo, Lesson, LessonsOut } from "./types";
import { Badge, Tabs, errText, useLoad } from "./ui";

type Lab = "lessons" | "retrieval" | "chunking" | "graph" | "langchain";
const DEFAULT_Q = "How many weeks of parental leave do partners get?";

function QuestionBar({ question, setQuestion, onDemo, demoMsg, demos }: { question: string; setQuestion: (q: string) => void; onDemo: () => void; demoMsg: string | null; demos: LessonsOut["demo_questions"] }) {
  return (
    <div className="card">
      <label htmlFor="lq">Question to experiment with</label>
      <input id="lq" type="text" value={question} onChange={(e) => setQuestion(e.target.value)} />
      <div className="row" style={{ marginTop: 8 }}>
        <button onClick={onDemo}>Load demo documents</button>
        <span className="muted small">{demoMsg ?? "Adds a sample handbook, policies, contract and spreadsheets to this workspace so every technique has something to show (safe to repeat)."}</span>
      </div>
      <div className="chips" aria-label="Example questions">{demos.map((d) => <button key={d.q} title={d.teaches} onClick={() => setQuestion(d.q)}>{d.q}</button>)}</div>
    </div>
  );
}

export function Learn({ workspace, canIngest }: { workspace: string; canIngest: boolean }) {
  const lessons = useLoad(() => api.learnLessons(), []);
  const [lab, setLab] = useState<Lab>("lessons");
  const [question, setQuestion] = useState(DEFAULT_Q);
  const [demoMsg, setDemoMsg] = useState<string | null>(null);
  const [preset, setPreset] = useState<string | null>(null);
  const data = lessons.data;

  async function demo() {
    try { const r = await api.learnDemoCorpus(workspace); setDemoMsg(`Loaded ${r.documents.filter((d) => d.status === "ready").length} new, ${r.documents.filter((d) => d.status === "duplicate").length} already present.`); }
    catch (e) { setDemoMsg(errText(e)); }
  }
  const tryIt = (l: Lesson) => { setPreset(l.try.preset ?? null); setLab(l.try.lab === "eval" ? "retrieval" : (l.try.lab as Lab)); };

  return (
    <div>
      <div className="card">
        <h1 style={{ marginTop: 0 }}>Learn lab — RAG, LangGraph and LangChain on your own documents</h1>
        <p className="muted">Every technique below is real code from this project. Pick a question, switch techniques on one at a time, and watch what changes: which passages come back, how many characters reach the model, which graph node ran and what it wrote.
          {data && !data.llm_available && " No language model is configured, so model-dependent steps (multi-query, HyDE, LLM re-ranking, Self-RAG) show their deterministic fallbacks and say so."}
          {data && ` Embedder: ${data.embedder}.`}</p>
        <Tabs label="Labs" value={lab} onChange={setLab} tabs={[["lessons", "Lessons"], ["retrieval", "Retrieval lab"], ["chunking", "Chunking lab"], ["graph", "Agent graph"], ["langchain", "LangChain lab"]]} />
      </div>
      {lessons.error && <div className="error" role="alert">{lessons.error}</div>}
      {data && lab !== "lessons" && <QuestionBar question={question} setQuestion={setQuestion} onDemo={() => void demo()} demoMsg={canIngest ? demoMsg : "Ask a manager to load the demo documents."} demos={data.demo_questions} />}
      {data && lab === "lessons" && <Lessons data={data} onTry={tryIt} />}
      {data && lab === "retrieval" && <RetrievalLab workspace={workspace} question={question} presets={data.presets} initial={preset} />}
      {lab === "chunking" && <ChunkLab workspace={workspace} />}
      {lab === "graph" && <GraphLab workspace={workspace} question={question} initial={preset} />}
      {lab === "langchain" && <LangChainLab workspace={workspace} question={question} />}
    </div>
  );
}

function Lessons({ data, onTry }: { data: LessonsOut; onTry: (l: Lesson) => void }) {
  const groups = useMemo(() => ["RAG", "LangGraph", "LangChain"].map((g) => [g, data.lessons.filter((l) => l.group === g)] as const), [data]);
  return (
    <div>
      {groups.map(([g, ls]) => (
        <div className="card" key={g} aria-label={`${g} lessons`}>
          <h2 style={{ marginTop: 0 }}>{g}</h2>
          {ls.map((l) => (
            <details key={l.id} className="lesson">
              <summary><b>{l.title}</b>{l.needs_llm && <> <Badge kind="low">needs a model for full effect</Badge></>}</summary>
              <p>{l.what}</p><p className="muted"><b>Why it matters:</b> {l.why}</p>
              <p className="small">Code: <code>{l.code}</code></p>
              <button className="small primary" onClick={() => onTry(l)}>Try it →</button>
            </details>
          ))}
        </div>
      ))}
    </div>
  );
}

function RowView({ r, base }: { r: LabRow; base?: LabRow }) {
  const d = r.delta;
  return (
    <>
      <tr className={r.abstained ? "abst" : ""}>
        <td><b>{r.name}</b>{r.notes.map((n) => <div key={n} className="warn small">⚠ {n}</div>)}</td>
        <td><Badge kind={r.grade === "correct" ? "high" : r.grade === "ambiguous" ? "low" : "none"}>{r.grade}</Badge></td>
        <td>{r.hits.length}</td>
        <td className="small">{r.hits[0] ? `${r.hits[0].source} · ${r.hits[0].location}` : "— (abstained)"}</td>
        <td className="small">{r.hits.reduce((n, h) => n + h.chars_to_model, 0).toLocaleString()}</td>
        <td className="small">{r.ms.toFixed(0)} ms</td>
        <td className="small">
          {!d ? <span className="muted">baseline</span> : (
            <>
              <div>{d.overlap === 1 && !d.new.length && !d.dropped.length ? "same passages" : `${Math.round(d.overlap * 100)}% same passages`}{d.same_top1 ? "" : ", different #1"}</div>
              {d.grade_changed && <div className="warn">grade {d.grade_changed}</div>}
              {d.new.length > 0 && <div className="ok">+ {d.new.slice(0, 2).join("; ")}</div>}
              {d.dropped.length > 0 && <div className="bad">− {d.dropped.slice(0, 2).join("; ")}</div>}
              {d.chars_to_model_change !== 0 && <div>{d.chars_to_model_change > 0 ? "+" : ""}{d.chars_to_model_change} characters to the model</div>}
              <div className="muted">vs {d.vs}</div>
            </>
          )}
        </td>
      </tr>
      <tr><td colSpan={7} className="detail">
        <details><summary className="small">Passages and pipeline steps</summary>
          {r.hits.map((h) => (
            <div key={h.chunk_id} className="cite"><b>#{h.rank} {h.source} — {h.location}</b> <span className="muted small">sim {h.score} · words {h.lexical} · rrf {h.fused}{h.rerank !== null ? ` · rerank ${h.rerank}` : ""}{h.compressed ? " · compressed" : ""}</span>
              <div>{h.excerpt}</div></div>
          ))}
          {!r.hits.length && <div className="muted small">Nothing passed the relevance gate{r.attempts > 1 ? ` after ${r.attempts} attempts` : ""}: the system would answer “I could not verify”.</div>}
          <div className="chips">{r.trace.map((t, i) => <Badge key={i}>{String(t.step)}{t.method ? `: ${String(t.method)}` : ""}{t.grade ? `: ${String(t.grade)}` : ""}{t.kept !== undefined ? `: kept ${String(t.kept)}` : ""}</Badge>)}</div>
          <div className="muted small">Settings: {Object.keys(r.overrides).length ? JSON.stringify(r.overrides) : "(bare defaults)"}{base ? "" : ""}</div>
        </details>
      </td></tr>
    </>
  );
}

function RetrievalLab({ workspace, question, presets, initial }: { workspace: string; question: string; presets: string[]; initial: string | null }) {
  const [mode, setMode] = useState<"ablation" | "compare">(initial ? "compare" : "ablation");
  const [picked, setPicked] = useState<string[]>(initial && presets.includes(initial) ? ["semantic only", initial] : ["semantic only", "keyword only (BM25)", "hybrid (RRF)"]);
  const [rows, setRows] = useState<LabRow[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  type Saved = { q: string; rows: { name: string; grade: string; n: number; top: string | null; chars: number }[] };
  const readSaved = (): Saved | null => { try { const v = localStorage.getItem("mka_lab_run"); return v ? (JSON.parse(v) as Saved) : null; } catch { return null; } };
  const [saved, setSaved] = useState<Saved | null>(readSaved);
  const [showDiff, setShowDiff] = useState(false);
  async function run() {
    setBusy(true); setErr(null);
    try { setRows((mode === "ablation" ? await api.learnAblation(workspace, question) : await api.learnCompare(workspace, question, picked)).rows); } catch (e) { setErr(errText(e)); setRows(null); } finally { setBusy(false); }
  }
  return (
    <div className="card" aria-label="Retrieval lab">
      <Tabs label="Lab mode" value={mode} onChange={(m) => { setMode(m); setRows(null); }} tabs={[["ablation", "Add techniques one by one"], ["compare", "Compare settings side by side"]]} />
      {mode === "compare" && <div className="row" style={{ margin: "8px 0" }}>{presets.map((p) => <label key={p} className="check small"><input type="checkbox" checked={picked.includes(p)} onChange={() => setPicked(picked.includes(p) ? picked.filter((x) => x !== p) : [...picked, p])} />{p}</label>)}</div>}
      <p className="muted small">{mode === "ablation" ? "Starts from plain semantic search and switches on one more technique per row (cumulative). The last column says what that addition changed." : "Runs each chosen setting independently; differences are shown against the first row."}</p>
      <button className="primary" onClick={() => void run()} disabled={busy || (mode === "compare" && picked.length < 2)}>{busy ? "Running…" : "Run experiment"}</button>
      {err && <div className="error" role="alert">{err}</div>}
      {rows && (
        <div className="scroll"><table aria-label="Experiment results">
          <thead><tr><th>Setting</th><th>Grade</th><th>Passages</th><th>Top passage</th><th>Chars to model</th><th>Time</th><th>What changed</th></tr></thead>
          <tbody>{rows.map((r) => <RowView key={r.name} r={r} base={rows[0]} />)}</tbody>
        </table></div>
      )}
      {rows && (
        <div className="row small">
          <button className="small" onClick={() => { try { localStorage.setItem("mka_lab_run", JSON.stringify({ q: question, rows: rows.map((r) => ({ name: r.name, grade: r.grade, n: r.hits.length, top: r.hits[0]?.location ?? null, chars: r.hits.reduce((a, h) => a + h.chars_to_model, 0) })) })); setSaved(readSaved()); } catch { /* storage may be blocked */ } }}>Save this run</button>
          {saved && <span className="muted">Saved run for “{saved.q}”.</span>}
          {saved && <button className="small" onClick={() => setShowDiff(!showDiff)}>{showDiff ? "Hide" : "Compare with saved"}</button>}
        </div>
      )}
      {rows && saved && showDiff && (
        <table aria-label="Saved run comparison"><thead><tr><th>Setting</th><th>Grade (saved → now)</th><th>Passages</th><th>Chars to model</th></tr></thead>
          <tbody>{rows.map((r) => { const o = saved.rows.find((x) => x.name === r.name); const now = r.hits.reduce((a, h) => a + h.chars_to_model, 0);
            return <tr key={r.name}><td>{r.name}</td><td>{o ? (o.grade === r.grade ? `${r.grade} (same)` : `${o.grade} → ${r.grade}`) : "new row"}</td><td>{o ? `${o.n} → ${r.hits.length}` : r.hits.length}</td><td>{o ? `${o.chars} → ${now}` : now}</td></tr>; })}</tbody></table>
      )}
      {rows && <p className="muted small">Grade: <b>correct</b> = confident match, <b>ambiguous</b> = weak, <b>incorrect</b> = the system abstains instead of guessing. “Chars to model” is the amount of text that would be put in the prompt — parent-child adds context, compression removes noise.</p>}
    </div>
  );
}

function ChunkLab({ workspace }: { workspace: string }) {
  const src = useLoad(() => api.sources(workspace, { limit: 100 }), [workspace]);
  const docs = (src.data?.items ?? []).filter((d) => !d.tabular);
  const [id, setId] = useState("");
  const [res, setRes] = useState<Awaited<ReturnType<typeof api.learnChunking>> | null>(null);
  const [err, setErr] = useState<string | null>(null);
  async function go() { setErr(null); try { setRes(await api.learnChunking(workspace, id || docs[0].id)); } catch (e) { setErr(errText(e)); setRes(null); } }
  return (
    <div className="card" aria-label="Chunking lab">
      <h2 style={{ marginTop: 0 }}>How chunk size cuts a document</h2>
      <p className="muted small">Nothing is re-indexed: the stored text is only re-cut for the experiment. Chunks never cross a page, sheet or section boundary.</p>
      <div className="row"><select aria-label="Document" value={id} onChange={(e) => setId(e.target.value)}>{docs.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</select>
        <button className="primary" disabled={!docs.length} onClick={() => void go()}>Cut with 400 / 1000 / 2500 characters</button></div>
      {!docs.length && <p className="muted small">Load the demo documents first.</p>}
      {err && <div className="error" role="alert">{err}</div>}
      {res && <>
        <table aria-label="Chunking results"><thead><tr><th>Size / overlap</th><th>Chunks</th><th>Average</th><th>Min–max</th><th>Tiny (&lt;20%)</th></tr></thead>
          <tbody>{res.rows.map((r) => <tr key={r.size}><td>{r.size} / {r.overlap}</td><td>{r.chunks}</td><td>{r.avg_chars}</td><td>{r.min_chars}–{r.max_chars}</td><td>{r.tiny_chunks}</td></tr>)}</tbody></table>
        {res.rows.map((r) => <details key={r.size}><summary className="small">First chunks at {r.size} characters</summary>{r.samples.map((s, i) => <div className="cite" key={i}><b>{s.location}</b> <span className="muted small">{s.chars} chars</span><div>{s.text}</div></div>)}</details>)}
        <p className="muted small">{res.reading}</p></>}
    </div>
  );
}

function GraphLab({ workspace, question, initial }: { workspace: string; question: string; initial: string | null }) {
  const info = useLoad<GraphInfo>(() => api.learnGraph(), []);
  const [auto, setAuto] = useState(initial === "auto");
  const [selfRag, setSelfRag] = useState(initial === "self_rag");
  const [run, setRun] = useState<GraphRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { setRun(null); }, [question]);
  async function go() {
    setBusy(true); setErr(null);
    try { setRun(await api.learnGraphRun(workspace, question, { auto, self_rag: selfRag })); } catch (e) { setErr(errText(e)); setRun(null); } finally { setBusy(false); }
  }
  return (
    <div>
      <div className="card" aria-label="Agent graph">
        <h2 style={{ marginTop: 0 }}>The compiled LangGraph</h2>
        <p className="muted small">Boxes are nodes (agents); solid arrows are fixed edges, dashed arrows are conditional edges chosen from the state. After a run, the nodes that executed are highlighted.</p>
        {info.error && <div className="error" role="alert">{info.error}</div>}
        {info.data && <GraphDiagram info={info.data} visited={run?.steps.map((s) => s.node) ?? []} />}
        {info.data && <details><summary className="small">Mermaid source (paste into any Mermaid viewer)</summary><pre className="code">{info.data.mermaid}</pre></details>}
        {info.data && <details><summary className="small">What each node does</summary><ul>{info.data.nodes.filter((n) => n.description).map((n) => <li key={n.id}><code>{n.id}</code> — {n.description}</li>)}</ul></details>}
      </div>
      <div className="card">
        <h2 style={{ marginTop: 0 }}>Run a question and watch the state</h2>
        <div className="row">
          <label className="check"><input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />Auto strategy (adds the <code>strategy</code> node)</label>
          <label className="check"><input type="checkbox" checked={selfRag} onChange={(e) => setSelfRag(e.target.checked)} />Self-RAG</label>
          <button className="primary" onClick={() => void go()} disabled={busy}>{busy ? "Running…" : "Run through the graph"}</button>
        </div>
        <p className="muted small">Try a compound question such as <i>How many times does “Anjali Rao” appear, and what is the highest sales?</i> to see parallel branches and the merge node.</p>
        {err && <div className="error" role="alert">{err}</div>}
        {run && (
          <ol className="steps-list" aria-label="Graph steps">
            {run.steps.map((s, i) => (
              <li key={i}><b>{s.node}</b> <span className="muted small">{s.ms} ms · wrote {s.writes.join(", ") || "nothing"}</span>
                <pre className="code small">{JSON.stringify(s.summary, null, 1)}</pre></li>
            ))}
          </ol>
        )}
        {run?.response && <div className="card" style={{ background: "var(--soft)" }}><b>Final answer</b> <Badge>{run.response.route}</Badge> <Badge kind={run.response.confidence}>{run.response.confidence}</Badge><div style={{ whiteSpace: "pre-wrap" }}>{run.response.answer}</div></div>}
        {run && <details><summary className="small">Checkpoints saved by LangGraph ({run.checkpoints.length})</summary><ul>{run.checkpoints.map((c, i) => <li key={i} className="small">step {c.step} → next: {c.next.join(", ") || "end"}{c.writes.length ? ` (writes: ${c.writes.join(", ")})` : ""}</li>)}</ul>
          <p className="muted small">These snapshots (state after each step) are what lets a conversation be resumed or inspected; they are deleted after this lab run.</p></details>}
      </div>
    </div>
  );
}

function LangChainLab({ workspace, question }: { workspace: string; question: string }) {
  const [d, setD] = useState<LcDemo | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function go() {
    setBusy(true); setErr(null);
    try { setD(await api.learnLangchain(workspace, question)); } catch (e) { setErr(errText(e)); setD(null); } finally { setBusy(false); }
  }
  const Section = ({ title, code, children }: { title: string; code: string; children: React.ReactNode }) => (
    <div className="card"><h2 style={{ marginTop: 0 }}>{title}</h2><details open><summary className="small">Code</summary><pre className="code">{code}</pre></details>{children}</div>
  );
  return (
    <div>
      <div className="card" aria-label="LangChain lab">
        <p className="muted">This platform is built directly on LangGraph. Here the same ideas run as <b>real <code>langchain_core</code> objects</b> on your documents: retriever → prompt → model → parser, a tool schema, structured output and message windows.</p>
        <button className="primary" onClick={() => void go()} disabled={busy}>{busy ? "Running…" : "Run the LangChain examples"}</button>
        {err && <div className="error" role="alert">{err}</div>}
      </div>
      {d && (
        <>
          <Section title="1 · Retriever" code={d.code.retriever}>
            {d.retriever.documents.map((x, i) => <div className="cite" key={i}><b>{x.source} — {x.location}</b> <span className="muted small">score {x.score}</span><div>{x.text}</div></div>)}
          </Section>
          <Section title="2 · LCEL chain (prompt | model | parser)" code={d.code.chain}>
            <p className="small">Model: {d.llm_used ? "your configured LLM" : "deterministic extractive function (no LLM configured)"}.</p>
            <h3>Recorded steps (callback handler)</h3>
            <table><thead><tr><th>Runnable</th><th>Input</th><th>Output</th><th>ms</th></tr></thead><tbody>{d.chain.steps.map((s, i) => <tr key={i}><td>{s.name}<div className="muted small">{s.kind}</div></td><td className="small">{s.input}</td><td className="small">{s.output}</td><td>{s.ms}</td></tr>)}</tbody></table>
            <h3>Rendered prompt</h3><pre className="code small">{d.chain.prompt}</pre>
            <h3>Answer</h3><div className="answer">{d.chain.answer}</div>
          </Section>
          <Section title="3 · Tool schema and validated call" code={d.code.tool}>
            <p>Result for <code>{d.tool.term}</code>: <b>{d.tool.result}</b></p><p className="small">An invalid call is rejected before the function runs: <code>{d.tool.invalid_call_rejected}</code></p>
            <details><summary className="small">Schema a chat model receives (OpenAI function format)</summary><pre className="code small">{JSON.stringify(d.tool.schema, null, 1)}</pre></details>
          </Section>
          <Section title="4 · Structured output parser" code={d.code.parser}>
            <pre className="code small">{d.parser.format_instructions}</pre><p className="small">Parsed: <code>{JSON.stringify(d.parser.parsed)}</code></p><p className="small">Malformed output → <code>{d.parser.malformed_output_error}</code></p>
          </Section>
          <Section title="5 · Messages and a memory window" code={d.code.memory}>
            <div className="small"><b>All turns:</b> {d.memory.messages.map((m, i) => <div key={i}>{m.type}: {m.content}</div>)}<b>Kept by the window (last 2):</b> {d.memory.kept_by_window.map((m, i) => <div key={i}>{m.type}: {m.content}</div>)}</div>
          </Section>
        </>
      )}
    </div>
  );
}
