import { useCallback, useEffect, useRef, useState } from "react";
import { api, askStream, saveBlob } from "./api";
import { Chart } from "./Chart";
import { Preview } from "./Preview";
import type { AskResponse, Citation, Message, RetrievalOptions } from "./types";
import { Badge, useLoad } from "./ui";

interface Turn { role: "user" | "assistant"; text: string; resp?: Partial<AskResponse>; steps?: string[]; pending?: boolean; animate?: boolean }
const KINDS = ["pdf", "docx", "xlsx", "csv", "txt", "md", "json", "url", "image"];

type SR = { new (): { lang: string; interimResults: boolean; onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null; onend: (() => void) | null; onerror: (() => void) | null; start(): void; stop(): void } };
const SpeechRec: SR | undefined = typeof window !== "undefined" ? ((window as unknown as { SpeechRecognition?: SR; webkitSpeechRecognition?: SR }).SpeechRecognition ?? (window as unknown as { webkitSpeechRecognition?: SR }).webkitSpeechRecognition) : undefined;

export function CitationList({ citations, onOpen }: { citations: Citation[]; onOpen?: (c: Citation) => void }) {
  if (!citations.length) return null;
  return (
    <details className="cites" open={citations.length <= 3}>
      <summary>{citations.length} citation{citations.length > 1 ? "s" : ""}</summary>
      {citations.map((c, i) => (
        <div className="cite" key={i}>
          <b>[{i + 1}] {c.source} — {c.location}</b> {c.origin === "web" && <Badge kind="low">web</Badge>}{c.version ? <span className="muted small"> v{c.version}</span> : null}
          <div>{c.excerpt}</div>
          {onOpen && <button className="small" aria-label={`Open citation ${i + 1} in context`} onClick={() => onOpen(c)}>{c.origin === "web" ? "Details" : "View in context"}</button>}
        </div>
      ))}
    </details>
  );
}

const reduceMotion = () => typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Reveals text character by character (a display effect: the full answer has already arrived). Click to skip. */
export function Typed({ text, animate, onTick }: { text: string; animate: boolean; onTick?: () => void }) {
  const live = animate && !reduceMotion();
  const [n, setN] = useState(live ? 0 : text.length);
  useEffect(() => {
    if (!live) { setN(text.length); return; }
    setN(0);
    const step = Math.max(2, Math.ceil(text.length / 90));   // long answers finish in about 1.5 s
    const t = setInterval(() => {
      setN((v) => { const nv = Math.min(text.length, v + step); if (nv >= text.length) clearInterval(t); return nv; });
      onTick?.();
    }, 16);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, live]);
  return <span onClick={() => setN(text.length)}>{text.slice(0, n)}{n < text.length && <span className="caret" aria-hidden="true" />}</span>;
}

function AutoPick({ resp }: { resp: Partial<AskResponse> }) {
  const a = (resp.details?.plan as { auto_strategy?: { chosen: string; why: string; candidates: { name: string; why: string; grade: string; hits: number; ms: number; score: number }[] } } | undefined)?.auto_strategy;
  if (!a) return null;
  return (
    <details className="autopick">
      <summary>✨ Auto picked <b>{a.chosen}</b> — {a.why}</summary>
      <table><thead><tr><th>Candidate</th><th>Grade</th><th>Passages</th><th>Score</th><th>ms</th></tr></thead>
        <tbody>{a.candidates.map((c) => <tr key={c.name} className={c.name === a.chosen ? "picked" : ""}><td>{c.name}{c.name === a.chosen ? " ✓" : ""}<div className="muted small">{c.why}</div></td><td>{c.grade}</td><td>{c.hits}</td><td>{c.score}</td><td>{c.ms}</td></tr>)}</tbody></table>
    </details>
  );
}

function FeedbackBar({ workspace, question, resp }: { workspace: string; question: string; resp: Partial<AskResponse> }) {
  const [state, setState] = useState<"idle" | "form" | "sent">("idle");
  const [expected, setExpected] = useState("");
  const [comment, setComment] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  async function exportReport() {
    setExporting(true); setErr(null);
    try {
      const r = await api.createReport(workspace, { kind: "research", format: "pdf", params: { questions: [question], title: question.slice(0, 80) } });
      saveBlob(await api.downloadReport(workspace, r.id), "answer-report.pdf");
    } catch (e) { setErr(e instanceof Error ? e.message : "Export failed"); } finally { setExporting(false); }
  }
  const sources = (resp.citations ?? []).slice(0, 5).map((c) => ({ source: c.source, location: c.location }));
  async function send(rating: 1 | -1) {
    try {
      await api.sendFeedback(workspace, rating === 1 ? { rating, route: resp.route } : { rating, route: resp.route, question, answer: resp.answer, expected: expected || undefined, comment: comment || undefined, sources });
      setState("sent");
    } catch (e) { setErr(e instanceof Error ? e.message : "Could not send"); }
  }
  if (state === "sent") return <div className="muted small" role="status">Thanks — feedback saved.</div>;
  return (
    <div className="fb">
      <div className="row small">
        <button className="icon" aria-label="Good answer" title="Good answer" onClick={() => void send(1)}>👍</button>
        <button className="icon" aria-label="Export this answer as a report" title="Export as a PDF report with sources" disabled={exporting} onClick={() => void exportReport()}>{exporting ? "…" : "⬇"}</button>
        <button className="icon" aria-label="Bad answer" title="Bad answer" aria-expanded={state === "form"} onClick={() => setState(state === "form" ? "idle" : "form")}>👎</button>
      </div>
      {state === "form" && (
        <form className="col" onSubmit={(e) => { e.preventDefault(); void send(-1); }}>
          <label htmlFor="fbexp">What should the answer contain? (optional — lets this become a regression test)</label>
          <input id="fbexp" type="text" value={expected} onChange={(e) => setExpected(e.target.value)} placeholder="e.g. 25 days" />
          <label htmlFor="fbcom">Comment (optional)</label>
          <input id="fbcom" type="text" value={comment} onChange={(e) => setComment(e.target.value)} />
          <p className="muted small" style={{ margin: 0 }}>Sends this question and answer to your organisation's feedback list.</p>
          <div className="row"><button className="small primary">Send feedback</button></div>
        </form>
      )}
      {err && <div className="error small" role="alert">{err}</div>}
    </div>
  );
}

const STARTERS = ["Summarize my documents", "Does a specific name appear in these files?", "Which employee has the highest sales?", "Compare two of my documents"];

function fromMessage(m: Message): Turn {
  return { role: m.role, text: m.content, resp: m.role === "assistant" ? (m.meta ?? undefined) : undefined };
}

export function Chat({ workspace, prefill, onPrefillUsed }: { workspace: string; prefill: string | null; onPrefillUsed: () => void }) {
  const convs = useLoad(() => api.conversations(workspace), [workspace]);
  const sources = useLoad(() => api.sources(workspace), [workspace]);
  const [active, setActive] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [opts, setOpts] = useState<RetrievalOptions>({ mode: "hybrid", rewrite: true, corrective: true, parent_child: true, compression: true, reranker: "lexical", top_k: 6 });
  const [kinds, setKinds] = useState<string[]>([]);
  const [pageMin, setPageMin] = useState("");
  const [pageMax, setPageMax] = useState("");
  const [nameContains, setNameContains] = useState("");
  const [caseSensitive, setCaseSensitive] = useState(false);
  const [listening, setListening] = useState(false);
  const [incognito, setIncognito] = useState(false);
  const [showOpts, setShowOpts] = useState(false);
  const [cite, setCite] = useState<Citation | null>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const recRef = useRef<{ stop(): void } | null>(null);

  useEffect(() => { setActive(null); setTurns([]); }, [workspace]);
  const toBottom = useCallback(() => { if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight; }, []);
  useEffect(() => { toBottom(); }, [turns, toBottom]);
  useEffect(() => { if (prefill) { setInput(prefill); onPrefillUsed(); } }, [prefill, onPrefillUsed]);
  useEffect(() => () => abortRef.current?.abort(), []);

  async function open(id: string) {
    setActive(id);
    setErr(null);
    try { setTurns((await api.messages(workspace, id)).map(fromMessage)); } catch (e) { setErr(e instanceof Error ? e.message : "Failed"); }
  }

  async function send(question: string) {
    const q = question.trim();
    if (!q || busy) return;
    setInput("");
    setErr(null);
    setBusy(true);
    const filters = {
      ...(kinds.length ? { kinds } : {}), ...(pageMin ? { page_min: Number(pageMin) } : {}), ...(pageMax ? { page_max: Number(pageMax) } : {}),
      ...(nameContains ? { name_contains: nameContains } : {}),
    };
    const retrieval: RetrievalOptions = { ...opts, ...(Object.keys(filters).length ? { filters } : {}) };
    setTurns((t) => [...t, { role: "user", text: q }, { role: "assistant", text: "", steps: [], pending: true }]);
    const patch = (fn: (t: Turn) => Turn) => setTurns((all) => all.map((t, i) => (i === all.length - 1 ? fn(t) : t)));
    const ctl = new AbortController();
    abortRef.current = ctl;
    try {
      await askStream(workspace, { question: q, conversation_id: active ?? undefined, source_ids: selected.length ? selected : undefined, case_sensitive: caseSensitive, retrieval, incognito }, (ev) => {
        if (ev.type === "step") patch((t) => ({ ...t, steps: [...(t.steps ?? []), ev.detail] }));
        else if (ev.type === "token") { /* tokens arrive together with the verified answer; the "final" event reveals it character by character */ }
        else if (ev.type === "final") {
          patch((t) => ({ ...t, text: ev.response.answer, resp: ev.response, pending: false, animate: true }));
          if (ev.response.conversation_id) setActive(ev.response.conversation_id);
        } else if (ev.type === "error") { setErr(ev.detail); patch((t) => ({ ...t, text: "", pending: false })); }
      }, ctl.signal);
      void convs.reload();
    } catch (e) {
      if (!(e instanceof DOMException && e.name === "AbortError")) setErr(e instanceof Error ? e.message : "Request failed");
      patch((t) => ({ ...t, pending: false }));
    } finally {
      setBusy(false);
    }
  }

  async function voice() {
    if (listening) { recRef.current?.stop(); return; }
    if (SpeechRec) {
      const r = new SpeechRec();
      r.lang = navigator.language || "en-US";
      r.interimResults = false;
      r.onresult = (e) => setInput(Array.from(e.results).map((x) => x[0].transcript).join(" "));
      r.onend = () => setListening(false);
      r.onerror = () => setListening(false);
      recRef.current = r;
      setListening(true);
      r.start();
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rec = new MediaRecorder(stream);
      const chunks: Blob[] = [];
      rec.ondataavailable = (e) => chunks.push(e.data);
      rec.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        setListening(false);
        try { setInput((await api.transcribe(workspace, new Blob(chunks, { type: rec.mimeType || "audio/webm" }))).text); } catch (e) { setErr(e instanceof Error ? e.message : "Transcription failed"); }
      };
      recRef.current = rec;
      setListening(true);
      rec.start();
    } catch { setErr("Microphone is not available in this browser."); }
  }

  const toggle = <T,>(arr: T[], v: T) => (arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);

  const empty = !turns.length;
  const composer = (
    <form className="composer" onSubmit={(e) => { e.preventDefault(); void send(input); }}>
      <textarea rows={1} value={input} onChange={(e) => { setInput(e.target.value); e.target.style.height = "auto"; e.target.style.height = Math.min(e.target.scrollHeight, 180) + "px"; }}
        placeholder="Message your documents…" aria-label="Question" onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(input); } }} />
      <div className="composer-bar">
        <button type="button" className={`pill ${opts.auto ? "on" : ""}`} aria-pressed={Boolean(opts.auto)} aria-label="Auto strategy" title="The agent graph tries candidate retrieval settings for each question and uses the best" onClick={() => setOpts({ ...opts, auto: !opts.auto })}>✨ Auto</button>
        <button type="button" className={`pill ${incognito ? "on" : ""}`} aria-pressed={incognito} aria-label="Incognito mode" title="Nothing is stored" onClick={() => setIncognito(!incognito)}>🕶 Incognito</button>
        <button type="button" className="pill" aria-expanded={showOpts} onClick={() => setShowOpts(!showOpts)}>⚙ Options</button>
        <span className="grow" />
        <button type="button" className="icon" aria-label="Voice input" aria-pressed={listening} onClick={() => void voice()}>{listening ? "■" : "🎤"}</button>
        {busy ? <button type="button" className="send" aria-label="Stop" onClick={() => abortRef.current?.abort()}>■</button> : <button className="send primary" aria-label="Ask" disabled={!input.trim()}>↑</button>}
      </div>
    </form>
  );

  return (
    <div className={`gpt ${showOpts ? "with-opts" : ""}`}>
      <aside className="gpt-side" aria-label="Conversations">
        <button className="new" onClick={() => { setActive(null); setTurns([]); }}>+ New conversation</button>
        <h3>History</h3>
        <div className="convs">
          {(convs.data?.items ?? []).map((c) => (
            <div key={c.id} className="conv-row">
              <button className={c.id === active ? "on" : ""} onClick={() => void open(c.id)} title={c.title}>{c.title || "Untitled"}</button>
              <button className="small danger x" aria-label={`Delete conversation ${c.title}`} onClick={async () => { await api.deleteConversation(workspace, c.id); if (c.id === active) { setActive(null); setTurns([]); } void convs.reload(); }}>×</button>
            </div>
          ))}
          {!convs.data?.items.length && <span className="muted small">No conversations yet.</span>}
        </div>
      </aside>

      <section className="gpt-main">
        <div className="log" ref={logRef} aria-live="polite">
          {empty && (
            <div className="hello">
              <div className="logo">📚</div>
              <h1>How can I help with your documents?</h1>
              <p className="muted">Ask in English or Hindi. Answers cite their sources; counts and spreadsheet figures are computed by code.</p>
              <div className="starters">{STARTERS.map((x) => <button key={x} onClick={() => setInput(x)}>{x}</button>)}</div>
            </div>
          )}
          {turns.map((t, i) => (
            <div key={i} className={`msg ${t.role}`}>
              {t.role === "assistant" && <div className="avatar" aria-hidden="true">AI</div>}
              <div className="bubble">
                {t.role === "assistant" && t.resp && (
                  <div className="row small badges">
                    {t.resp.confidence && <Badge kind={t.resp.confidence}>confidence: {t.resp.confidence}</Badge>}
                    {t.resp.route && <Badge>{t.resp.route}</Badge>}
                    {t.resp.verified === false && <Badge kind="none">not verified</Badge>}
                    {t.resp.details?.citation_check && t.resp.details.citation_check.accuracy !== null && <Badge kind={t.resp.details.citation_check.accuracy === 1 ? "high" : "low"}>citations checked: {Math.round(t.resp.details.citation_check.accuracy * 100)}%</Badge>}
                    {t.resp.details?.private === true && <Badge>incognito</Badge>}
                  </div>
                )}
                <div className="text">
                  {t.role === "assistant" ? (t.text ? <Typed text={t.text} animate={Boolean(t.animate)} onTick={toBottom} /> : t.pending ? <span className="thinking">Thinking<i>.</i><i>.</i><i>.</i></span> : "") : t.text}
                </div>
                {t.pending && t.steps && t.steps.length > 0 && <div className="steps">{t.steps.map((st, k) => <div key={k}>› {st}</div>)}</div>}
                {t.resp && <AutoPick resp={t.resp} />}
                {t.resp?.details?.chart && <Chart spec={t.resp.details.chart} />}
                {t.resp?.citations && <CitationList citations={t.resp.citations} onOpen={setCite} />}
                {t.resp?.limitations && t.resp.limitations.length > 0 && <div className="muted small" style={{ marginTop: 6 }}>ℹ {t.resp.limitations.join(" • ")}</div>}
                {t.resp?.followups && t.resp.followups.length > 0 && !t.pending && (
                  <div className="chips" aria-label="Follow-up questions">{t.resp.followups.map((f) => <button key={f} onClick={() => void send(f)}>{f}</button>)}</div>
                )}
                {t.role === "assistant" && t.resp && !t.pending && !t.resp.details?.private && i > 0 && <FeedbackBar workspace={workspace} question={turns[i - 1]?.text ?? ""} resp={t.resp} />}
                {t.resp?.usage && t.resp.latency_ms && (
                  <div className="muted small" style={{ marginTop: 6 }}>
                    {t.resp.latency_ms.toFixed(0)} ms · {(t.resp.usage.prompt_tokens ?? 0) + (t.resp.usage.completion_tokens ?? 0) + (t.resp.usage.embed_tokens ?? 0)} tokens · ${(t.resp.usage.cost_usd ?? 0).toFixed(5)}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
        {err && <div className="error" role="alert">{err}</div>}
        <div className="composer-wrap">{composer}<div className="muted small center">Answers are checked against your documents; verify important facts in the cited source.</div></div>
      </section>

      <aside className="gpt-opts" aria-label="Search filters" hidden={!showOpts}>
        <div className="row"><h3 style={{ margin: 0 }}>Search filters</h3><span className="grow" /><button className="small" onClick={() => setShowOpts(false)} aria-label="Close options">×</button></div>
        <label htmlFor="mode">Retrieval mode</label>
        <select id="mode" value={opts.mode} onChange={(e) => setOpts({ ...opts, mode: e.target.value as RetrievalOptions["mode"] })}>
          <option value="hybrid">Hybrid (vector + keyword)</option><option value="semantic">Semantic only</option><option value="keyword">Keyword (BM25) only</option>
        </select>
        <div className="col" style={{ marginTop: 8 }}>
          {([["rewrite", "Query rewriting"], ["multi_query", "Multi-query"], ["hyde", "HyDE (needs LLM)"], ["parent_child", "Parent-child context"], ["compression", "Contextual compression"], ["corrective", "Corrective retry"], ["graph", "Graph expansion"], ["self_rag", "Self-RAG (check each statement)"]] as const).map(([k, label]) => (
            <label key={k} className="check">
              <input type="checkbox" checked={Boolean(opts[k])} onChange={(e) => setOpts({ ...opts, [k]: e.target.checked })} />{label}
            </label>
          ))}
          <p className="muted small" style={{ margin: 0 }}>Turn on <b>✨ Auto</b> (below the message box) to let the agent graph choose these for each question. Not sure what a filter does? Open <b>Learn lab</b>.</p>
          <label htmlFor="rr">Reranker</label>
          <select id="rr" value={opts.reranker} onChange={(e) => setOpts({ ...opts, reranker: e.target.value as RetrievalOptions["reranker"] })}>
            <option value="lexical">Lexical</option><option value="llm">LLM (needs LLM)</option><option value="cross_encoder">Cross-encoder (optional)</option><option value="none">None</option>
          </select>
          <label htmlFor="topk">Passages (top-k)</label>
          <input id="topk" type="number" min={1} max={30} value={opts.top_k} onChange={(e) => setOpts({ ...opts, top_k: Number(e.target.value) || 6 })} />
        </div>
        <h3>Metadata filters</h3>
        <div className="chips">{KINDS.map((k) => <button key={k} className={`small ${kinds.includes(k) ? "primary" : ""}`} aria-pressed={kinds.includes(k)} onClick={() => setKinds(toggle(kinds, k))}>{k}</button>)}</div>
        <div className="row" style={{ marginTop: 8 }}>
          <input type="number" min={1} placeholder="page ≥" aria-label="Minimum page" value={pageMin} onChange={(e) => setPageMin(e.target.value)} style={{ width: 90 }} />
          <input type="number" min={1} placeholder="page ≤" aria-label="Maximum page" value={pageMax} onChange={(e) => setPageMax(e.target.value)} style={{ width: 90 }} />
        </div>
        <input type="text" placeholder="file name contains…" aria-label="File name contains" value={nameContains} onChange={(e) => setNameContains(e.target.value)} style={{ marginTop: 8 }} />
        <label className="check" style={{ marginTop: 8 }}><input type="checkbox" checked={caseSensitive} onChange={(e) => setCaseSensitive(e.target.checked)} />Case-sensitive exact search</label>
        <h3>Limit to documents</h3>
        <div className="col" style={{ maxHeight: 180, overflow: "auto" }}>
          {(sources.data?.items ?? []).map((s) => (
            <label key={s.id} className="check"><input type="checkbox" checked={selected.includes(s.id)} onChange={() => setSelected(toggle(selected, s.id))} />{s.name}</label>
          ))}
          {!sources.data?.items.length && <span className="muted small">No documents.</span>}
        </div>
      </aside>
      {cite && <Preview workspace={workspace} citation={cite} onClose={() => setCite(null)} />}
    </div>
  );
}
