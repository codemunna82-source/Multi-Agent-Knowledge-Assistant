import { useEffect, useRef, useState } from "react";
import { api, askStream } from "./api";
import { Chart } from "./Chart";
import { Preview } from "./Preview";
import type { AskResponse, Citation, Message, RetrievalOptions } from "./types";
import { Badge, useLoad } from "./ui";

interface Turn { role: "user" | "assistant"; text: string; resp?: Partial<AskResponse>; steps?: string[]; pending?: boolean }
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
  const [cite, setCite] = useState<Citation | null>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const recRef = useRef<{ stop(): void } | null>(null);

  useEffect(() => { setActive(null); setTurns([]); }, [workspace]);
  useEffect(() => { if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight; }, [turns]);
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
        else if (ev.type === "token") patch((t) => ({ ...t, text: t.text + ev.text }));
        else if (ev.type === "final") {
          patch((t) => ({ ...t, text: ev.response.answer, resp: ev.response, pending: false }));
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

  return (
    <div className="chat">
      <aside className="card convs" aria-label="Conversations">
        <button className="primary" onClick={() => { setActive(null); setTurns([]); }}>+ New conversation</button>
        <h3>History</h3>
        {(convs.data?.items ?? []).map((c) => (
          <div key={c.id} className="row" style={{ flexWrap: "nowrap" }}>
            <button className={c.id === active ? "on" : ""} onClick={() => void open(c.id)} title={c.title}>{c.title || "Untitled"}</button>
            <button className="small danger" aria-label={`Delete conversation ${c.title}`} onClick={async () => { await api.deleteConversation(workspace, c.id); if (c.id === active) { setActive(null); setTurns([]); } void convs.reload(); }}>×</button>
          </div>
        ))}
        {!convs.data?.items.length && <span className="muted small">No conversations yet.</span>}
      </aside>

      <section className="card">
        <div className="log" ref={logRef} aria-live="polite">
          {!turns.length && <div className="muted">Ask a question about your documents. Try “Does <i>Name</i> appear in these files?”, “Which employee has the highest sales?” or “Summarize report.pdf”.</div>}
          {turns.map((t, i) => (
            <div key={i} className={`msg ${t.role}`}>
              {t.role === "assistant" && t.resp && (
                <div className="row small" style={{ marginBottom: 4 }}>
                  {t.resp.confidence && <Badge kind={t.resp.confidence}>confidence: {t.resp.confidence}</Badge>}
                  {t.resp.route && <Badge>{t.resp.route}</Badge>}
                  {t.resp.verified === false && <Badge kind="none">not verified</Badge>}
                  {t.resp.details?.citation_check && t.resp.details.citation_check.accuracy !== null && <Badge kind={t.resp.details.citation_check.accuracy === 1 ? "high" : "low"}>citations checked: {Math.round(t.resp.details.citation_check.accuracy * 100)}%</Badge>}
                  {t.resp.details?.private === true && <Badge>incognito</Badge>}
                </div>
              )}
              {t.text || (t.pending ? "Thinking…" : "")}
              {t.pending && t.steps && t.steps.length > 0 && <div className="steps">{t.steps.map((s, k) => <div key={k}>› {s}</div>)}</div>}
              {t.resp?.details?.chart && <Chart spec={t.resp.details.chart} />}
              {t.resp?.citations && <CitationList citations={t.resp.citations} onOpen={setCite} />}
              {t.resp?.limitations && t.resp.limitations.length > 0 && <div className="muted small" style={{ marginTop: 6 }}>ℹ {t.resp.limitations.join(" • ")}</div>}
              {t.resp?.followups && t.resp.followups.length > 0 && !t.pending && (
                <div className="chips" aria-label="Follow-up questions">{t.resp.followups.map((f) => <button key={f} onClick={() => void send(f)}>{f}</button>)}</div>
              )}
              {t.resp?.usage && t.resp.latency_ms && (
                <div className="muted small" style={{ marginTop: 6 }}>
                  {t.resp.latency_ms.toFixed(0)} ms · {(t.resp.usage.prompt_tokens ?? 0) + (t.resp.usage.completion_tokens ?? 0) + (t.resp.usage.embed_tokens ?? 0)} tokens · ${(t.resp.usage.cost_usd ?? 0).toFixed(5)}
                </div>
              )}
            </div>
          ))}
        </div>
        {err && <div className="error" role="alert">{err}</div>}
        <form className="row" style={{ marginTop: 10, flexWrap: "nowrap" }} onSubmit={(e) => { e.preventDefault(); void send(input); }}>
          <textarea rows={2} value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask about your documents…" aria-label="Question"
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(input); } }} />
          <button type="button" aria-label="Voice input" aria-pressed={listening} onClick={() => void voice()}>{listening ? "■" : "🎤"}</button>
          {busy ? <button type="button" onClick={() => abortRef.current?.abort()}>Stop</button> : <button className="primary" disabled={!input.trim()}>Ask</button>}
        </form>
      </section>

      <aside className="card" aria-label="Search filters">
        <h3 style={{ marginTop: 0 }}>Search filters</h3>
        <label htmlFor="mode">Retrieval mode</label>
        <select id="mode" value={opts.mode} onChange={(e) => setOpts({ ...opts, mode: e.target.value as RetrievalOptions["mode"] })}>
          <option value="hybrid">Hybrid (vector + keyword)</option><option value="semantic">Semantic only</option><option value="keyword">Keyword (BM25) only</option>
        </select>
        <div className="col" style={{ marginTop: 8 }}>
          {([["rewrite", "Query rewriting"], ["multi_query", "Multi-query"], ["hyde", "HyDE (needs LLM)"], ["parent_child", "Parent-child context"], ["compression", "Contextual compression"], ["corrective", "Corrective retry"], ["graph", "Graph expansion"], ["self_rag", "Self-RAG (check each statement)"]] as const).map(([k, label]) => (
            <label key={k} style={{ display: "flex", gap: 6, alignItems: "center", color: "inherit", fontSize: 13, margin: 0 }}>
              <input type="checkbox" checked={Boolean(opts[k])} onChange={(e) => setOpts({ ...opts, [k]: e.target.checked })} />{label}
            </label>
          ))}
          <label htmlFor="rr">Reranker</label>
          <select id="rr" value={opts.reranker} onChange={(e) => setOpts({ ...opts, reranker: e.target.value as RetrievalOptions["reranker"] })}>
            <option value="lexical">Lexical</option><option value="llm">LLM (needs LLM)</option><option value="cross_encoder">Cross-encoder (optional)</option><option value="none">None</option>
          </select>
          <label htmlFor="topk">Passages (top-k)</label>
          <input id="topk" type="number" min={1} max={30} value={opts.top_k} onChange={(e) => setOpts({ ...opts, top_k: Number(e.target.value) || 6 })} />
        </div>
        <label style={{ display: "flex", gap: 6, alignItems: "center", marginTop: 8, color: "inherit", fontSize: 13 }}><input type="checkbox" checked={incognito} onChange={(e) => setIncognito(e.target.checked)} />Incognito (nothing is stored)</label>
        <h3>Metadata filters</h3>
        <div className="chips">{KINDS.map((k) => <button key={k} className={`small ${kinds.includes(k) ? "primary" : ""}`} aria-pressed={kinds.includes(k)} onClick={() => setKinds(toggle(kinds, k))}>{k}</button>)}</div>
        <div className="row" style={{ marginTop: 8 }}>
          <input type="number" min={1} placeholder="page ≥" aria-label="Minimum page" value={pageMin} onChange={(e) => setPageMin(e.target.value)} style={{ width: 90 }} />
          <input type="number" min={1} placeholder="page ≤" aria-label="Maximum page" value={pageMax} onChange={(e) => setPageMax(e.target.value)} style={{ width: 90 }} />
        </div>
        <input type="text" placeholder="file name contains…" aria-label="File name contains" value={nameContains} onChange={(e) => setNameContains(e.target.value)} style={{ marginTop: 8 }} />
        <label style={{ display: "flex", gap: 6, alignItems: "center", marginTop: 8, color: "inherit", fontSize: 13 }}><input type="checkbox" checked={caseSensitive} onChange={(e) => setCaseSensitive(e.target.checked)} />Case-sensitive exact search</label>
        <h3>Limit to documents</h3>
        <div className="col" style={{ maxHeight: 180, overflow: "auto" }}>
          {(sources.data?.items ?? []).map((s) => (
            <label key={s.id} style={{ display: "flex", gap: 6, alignItems: "center", color: "inherit", fontSize: 13, margin: 0 }}>
              <input type="checkbox" checked={selected.includes(s.id)} onChange={() => setSelected(toggle(selected, s.id))} />{s.name}
            </label>
          ))}
          {!sources.data?.items.length && <span className="muted small">No documents.</span>}
        </div>
      </aside>
      {cite && <Preview workspace={workspace} citation={cite} onClose={() => setCite(null)} />}
    </div>
  );
}
