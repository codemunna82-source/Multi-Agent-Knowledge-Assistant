import { useCallback, useEffect, useRef, useState } from "react";
import { api, askStream } from "./api";
import { ChatMessage, type Turn } from "./ChatMessage";
import { Preview } from "./Preview";
import { StopGeneratingButton } from "./StopGeneratingButton";
import type { Citation, Message, RetrievalOptions } from "./types";
import { useLoad } from "./ui";

export { CitationList } from "./ChatMessage";

const KINDS = ["pdf", "docx", "xlsx", "csv", "txt", "md", "json", "url", "image"];

type SR = { new (): { lang: string; interimResults: boolean; onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null; onend: (() => void) | null; onerror: (() => void) | null; start(): void; stop(): void } };
const SpeechRec: SR | undefined = typeof window !== "undefined" ? ((window as unknown as { SpeechRecognition?: SR; webkitSpeechRecognition?: SR }).SpeechRecognition ?? (window as unknown as { webkitSpeechRecognition?: SR }).webkitSpeechRecognition) : undefined;

const STARTERS = ["Summarize my documents", "Does a specific name appear in these files?", "Which employee has the highest sales?", "Compare two of my documents"];

function fromMessage(m: Message): Turn {
  return { role: m.role, text: m.content, resp: m.role === "assistant" ? (m.meta ?? undefined) : undefined, status: m.role === "assistant" ? "done" : undefined };
}

const NEAR_BOTTOM_PX = 80;

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
  const stick = useRef(true);                      // follow the newest text unless the reader scrolled up
  const [away, setAway] = useState(false);
  const toBottom = useCallback((force = false) => {
    const el = logRef.current;
    if (!el || (!force && !stick.current)) return;
    // re-checked inside the frame: a scroll by the reader after this was queued must win
    requestAnimationFrame(() => { if (force || stick.current) el.scrollTop = el.scrollHeight; });
  }, []);
  const onScroll = useCallback(() => {
    const el = logRef.current;
    if (!el) return;
    const near = el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM_PX;
    stick.current = near;
    setAway((v) => (v === !near ? v : !near));
  }, []);
  useEffect(() => { toBottom(); }, [turns, toBottom]);
  useEffect(() => { if (prefill) { setInput(prefill); onPrefillUsed(); } }, [prefill, onPrefillUsed]);
  useEffect(() => () => abortRef.current?.abort(), []);

  async function open(id: string) {
    setActive(id);
    setErr(null);
    try { setTurns((await api.messages(workspace, id)).map(fromMessage)); } catch (e) { setErr(e instanceof Error ? e.message : "Failed"); }
  }

  const busyRef = useRef(false);
  const lastAsk = useRef<{ q: string; regenerate: boolean } | null>(null);

  async function send(question: string, regenerate = false) {
    const q = question.trim();
    if (!q || busyRef.current) return;                    // one active answer at a time (also guards double clicks within one render)
    busyRef.current = true;
    lastAsk.current = { q, regenerate };
    setInput("");
    setErr(null);
    setBusy(true);
    stick.current = true;
    setAway(false);
    const filters = {
      ...(kinds.length ? { kinds } : {}), ...(pageMin ? { page_min: Number(pageMin) } : {}), ...(pageMax ? { page_max: Number(pageMax) } : {}),
      ...(nameContains ? { name_contains: nameContains } : {}),
    };
    const retrieval: RetrievalOptions = { ...opts, ...(Object.keys(filters).length ? { filters } : {}) };
    const fresh: Turn = { role: "assistant", text: "", status: "pending" };
    // regenerate / retry re-use the existing question bubble and only replace the answer
    setTurns((t) => (regenerate || (t.length >= 2 && t[t.length - 1].role === "assistant" && t[t.length - 1].status !== "done" && t[t.length - 2].text === q)
      ? [...t.slice(0, t.length - 1), fresh] : [...t, { role: "user", text: q }, fresh]));
    const patch = (fn: (t: Turn) => Turn) => setTurns((all) => all.map((t, i) => (i === all.length - 1 ? fn(t) : t)));
    const ctl = new AbortController();
    abortRef.current = ctl;
    // Incoming tokens are collected here and applied at most once per animation frame: smooth rendering, one React update per frame instead of one per token.
    let buf = "";
    let raf = 0;
    let streamed = "";
    const flush = () => { raf = 0; if (!buf) return; const add = buf; buf = ""; streamed += add; patch((t) => ({ ...t, text: t.text + add, status: "streaming" })); };
    const schedule = () => { if (!raf) raf = requestAnimationFrame(flush); };
    let finished = false;
    try {
      await askStream(workspace, { question: q, conversation_id: active ?? undefined, source_ids: selected.length ? selected : undefined, case_sensitive: caseSensitive, retrieval, incognito, ...(regenerate && active ? { regenerate: true } : {}) }, (ev) => {
        if (ev.type === "status") patch((t) => (t.status === "done" ? t : { ...t, stage: ev.label }));
        else if (ev.type === "draft") { buf += ev.text; schedule(); }
        else if (ev.type === "draft_reset") { if (raf) cancelAnimationFrame(raf); raf = 0; buf = ""; streamed = ""; patch((t) => ({ ...t, text: "", status: "pending", stage: null })); }
        else if (ev.type === "final") {
          if (raf) cancelAnimationFrame(raf);
          raf = 0; buf = "";
          finished = true;
          const answer = ev.response.answer;
          patch((t) => ({ ...t, text: answer, resp: ev.response, status: "done", stage: null, error: undefined, corrected: streamed.trim() !== "" && streamed.trim() !== answer.trim() }));
          if (ev.response.conversation_id) setActive(ev.response.conversation_id);
        } else if (ev.type === "error") {
          finished = true;
          patch((t) => ({ ...t, status: "error", stage: null, error: ev.detail }));
        }
      }, ctl.signal);
      if (!finished && !ctl.signal.aborted) patch((t) => (t.status === "done" ? t : { ...t, status: "error", stage: null, error: "The connection closed before the answer was complete." }));
      void convs.reload();
    } catch (e) {
      if (raf) cancelAnimationFrame(raf);
      if (e instanceof DOMException && e.name === "AbortError") patch((t) => ({ ...t, status: "stopped", stage: null }));
      else patch((t) => ({ ...t, status: "error", stage: null, error: e instanceof Error && e.message !== "Failed to fetch" && e.name !== "TypeError" ? e.message : "The connection was lost while the answer was being written." }));
    } finally {
      if (raf) cancelAnimationFrame(raf);
      if (ctl.signal.aborted) { buf = ""; }
      abortRef.current = null;
      busyRef.current = false;
      setBusy(false);
    }
  }

  const stop = () => abortRef.current?.abort();

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
        <div className="log" ref={logRef} onScroll={onScroll}>
          {empty && (
            <div className="hello">
              <div className="logo">📚</div>
              <h1>How can I help with your documents?</h1>
              <p className="muted">Ask in English or Hindi. Answers cite their sources; counts and spreadsheet figures are computed by code.</p>
              <div className="starters">{STARTERS.map((x) => <button key={x} onClick={() => setInput(x)}>{x}</button>)}</div>
            </div>
          )}
          {turns.map((t, i) => (
            <ChatMessage key={i} turn={t} question={turns[i - 1]?.text ?? ""} workspace={workspace} isLast={i === turns.length - 1} busy={busy}
              onOpenCitation={setCite} onFollowup={(f) => void send(f)}
              onRegenerate={() => void send(turns[i - 1]?.text ?? "", t.status === "done")} onRetry={() => void send(turns[i - 1]?.text ?? "")} />
          ))}
        </div>
        {away && busy && <button className="jump" onClick={() => { stick.current = true; setAway(false); toBottom(true); }} aria-label="Scroll to latest">↓ Latest</button>}
        {err && <div className="error" role="alert">{err}</div>}
        <div className="composer-wrap">{busy && <StopGeneratingButton onStop={stop} />}{composer}<div className="muted small center">Answers are checked against your documents; verify important facts in the cited source.</div></div>
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
