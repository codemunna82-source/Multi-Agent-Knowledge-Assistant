import { useEffect, useMemo, useRef, useState } from "react";
import type { Lang } from "../types";
import { contentWords, cosine, CONCEPTS, filterProbs, fmt, hashVector, rank, rng, sampleIndex, softmax, toyEmbed, toyTokenize, words } from "./toy";

const NOTE = "Teaching model: the numbers are illustrative; the Playground runs real models.";
const H: Record<Lang, Record<string, string>> = {
  en: { temp: "Temperature and sampling", tokgen: "Token-by-token generation", attn: "Attention (toy)", ctx: "Context window budget", emb: "Embeddings and semantic search" },
  hi: { temp: "Temperature और sampling", tokgen: "Token-दर-token generation", attn: "Attention (खिलौना model)", ctx: "Context window का budget", emb: "Embeddings और semantic search" },
  hinglish: { temp: "Temperature aur sampling", tokgen: "Token-by-token generation", attn: "Attention (toy model)", ctx: "Context window ka budget", emb: "Embeddings aur semantic search" },
};

// ----------------------------------------------------------------------------- temperature / top-k / top-p
const SCENARIOS: Record<string, { label: string; prompt: string; tokens: string[]; logits: number[] }> = {
  fact: { label: "Factual: capital of France", prompt: "The capital of France is", tokens: ["Paris", "Lyon", "the", "a", "located", "Marseille"], logits: [8.0, 5.2, 4.8, 4.0, 3.1, 2.9] },
  creative: { label: "Creative: a story opening", prompt: "Once upon a time, a dragon", tokens: ["lived", "woke", "loved", "learned", "sneezed", "vanished"], logits: [3.4, 3.1, 2.9, 2.7, 2.3, 2.1] },
};

export function TemperatureViz({ lang }: { lang: Lang }) {
  const [sc, setSc] = useState("fact");
  const [t, setT] = useState(1);
  const [k, setK] = useState(6);
  const [p, setP] = useState(1);
  const [draws, setDraws] = useState<string[]>([]);
  const seed = useRef(1);
  const s = SCENARIOS[sc];
  const base = useMemo(() => softmax(s.logits, t), [s, t]);
  const filtered = useMemo(() => filterProbs(base, k, p), [base, k, p]);
  const draw = (n: number) => { const r = rng(seed.current++ * 7919); setDraws((d) => [...d, ...Array.from({ length: n }, () => s.tokens[sampleIndex(filtered, r())])].slice(-300)); };
  const counts = s.tokens.map((tok) => draws.filter((d) => d === tok).length);
  return (
    <section className="viz" aria-label={H[lang].temp}>
      <h3>{H[lang].temp}</h3>
      <p className="viz-note small">{NOTE}</p>
      <div className="viz-inputs">
        <div><label htmlFor="t-sc">Prompt</label><select id="t-sc" value={sc} onChange={(e) => { setSc(e.target.value); setDraws([]); }}>{Object.entries(SCENARIOS).map(([id, x]) => <option key={id} value={id}>{x.label}</option>)}</select></div>
        <div><label htmlFor="t-t">Temperature: {fmt(t)}</label><input id="t-t" type="range" min={0.1} max={2} step={0.05} value={t} onChange={(e) => { setT(Number(e.target.value)); setDraws([]); }} /></div>
        <div><label htmlFor="t-k">Top-k: {k}</label><input id="t-k" type="range" min={1} max={6} step={1} value={k} onChange={(e) => { setK(Number(e.target.value)); setDraws([]); }} /></div>
        <div><label htmlFor="t-p">Top-p: {fmt(p)}</label><input id="t-p" type="range" min={0.1} max={1} step={0.05} value={p} onChange={(e) => { setP(Number(e.target.value)); setDraws([]); }} /></div>
      </div>
      <p><b>{s.prompt}</b> …</p>
      <div className="bars" role="table" aria-label="Next-token probabilities">
        {s.tokens.map((tok, i) => (
          <div key={tok} className="bar-row" role="row">
            <span role="cell" className="bar-label">{tok}</span>
            <span className="bar-track" role="cell"><i className="bar-base" style={{ width: `${base[i] * 100}%` }} /><i className="bar-final" style={{ width: `${filtered[i] * 100}%` }} /></span>
            <span role="cell" className="small">{fmt(base[i] * 100, 1)}% → <b>{fmt(filtered[i] * 100, 1)}%</b></span>
            {draws.length > 0 && <span role="cell" className="muted small">drawn {counts[i]}×</span>}
          </div>
        ))}
      </div>
      <p className="muted small">Grey bar: softmax(logit / T). Coloured bar: after top-k and top-p, renormalised. Formula: p = exp(logit / T) / Σ exp(logit / T). Low T makes the top token dominate; high T flattens the bars.</p>
      <div className="viz-controls">
        <button className="primary" onClick={() => draw(1)}>Sample 1 token</button><button onClick={() => draw(100)}>Sample 100</button><button onClick={() => setDraws([])}>Reset</button>
        <span className="muted small" aria-live="polite">{draws.length ? `last draws: ${draws.slice(-8).join(", ")}` : "No samples yet"}</span>
      </div>
    </section>
  );
}

// ----------------------------------------------------------------------------- token-by-token generation (bigram model)
const CORPUS = "the cat sat on the mat . the cat ate the fish . the dog sat on the rug . the dog ate the bone .";
export function TokenGenerationViz({ lang }: { lang: Lang }) {
  const [corpus, setCorpus] = useState(CORPUS);
  const [start, setStart] = useState("the");
  const [temp, setTemp] = useState(0.8);
  const [out, setOut] = useState<string[]>(["the"]);
  const [playing, setPlaying] = useState(false);
  const seed = useRef(3);
  const table = useMemo(() => { const m = new Map<string, Map<string, number>>(); const w = corpus.toLowerCase().split(/\s+/).filter(Boolean); w.slice(0, -1).forEach((a, i) => { const row = m.get(a) ?? new Map(); row.set(w[i + 1], (row.get(w[i + 1]) ?? 0) + 1); m.set(a, row); }); return m; }, [corpus]);
  const last = out[out.length - 1];
  const row = table.get(last);
  const cands = row ? [...row.entries()].sort((a, b) => b[1] - a[1]) : [];
  const probs = cands.length ? softmax(cands.map(([, c]) => Math.log(c)), temp) : [];
  const step = () => { if (!cands.length) { setPlaying(false); return; } const r = rng(seed.current++ * 104729); setOut((o) => [...o, cands[sampleIndex(probs, r())][0]]); };
  useEffect(() => { if (!playing) return; if (!cands.length || out.length > 14) { setPlaying(false); return; } const id = setTimeout(step, 900); return () => clearTimeout(id); }, [playing, out]);  // eslint-disable-line react-hooks/exhaustive-deps
  const reset = () => { setOut([start.trim().toLowerCase() || "the"]); setPlaying(false); seed.current = 3; };
  return (
    <section className="viz" aria-label={H[lang].tokgen}>
      <h3>{H[lang].tokgen}</h3>
      <p className="viz-note small">A tiny bigram model learned from the text below stands in for an LLM: the loop (predict, pick, append, repeat) is exactly the same.</p>
      <div className="viz-inputs">
        <div><label htmlFor="g-c">Training text</label><textarea id="g-c" rows={2} value={corpus} onChange={(e) => { setCorpus(e.target.value); setOut([start]); }} /></div>
        <div><label htmlFor="g-s">Start word</label><input id="g-s" value={start} onChange={(e) => setStart(e.target.value)} /></div>
        <div><label htmlFor="g-t">Temperature: {fmt(temp)}</label><input id="g-t" type="range" min={0.1} max={2} step={0.05} value={temp} onChange={(e) => setTemp(Number(e.target.value))} /></div>
      </div>
      <p className="viz-gen" aria-live="polite">{out.map((w, i) => <span key={i} className={i === out.length - 1 ? "last" : ""}>{w} </span>)}</p>
      <div className="bars" aria-label="Candidates for the next word">
        {cands.length === 0 && <p className="muted small">"{last}" never appeared before another word in the training text: the model has nothing to predict.</p>}
        {cands.map(([w, c], i) => <div className="bar-row" key={w}><span className="bar-label">{w}</span><span className="bar-track"><i className="bar-final" style={{ width: `${probs[i] * 100}%` }} /></span><span className="small">{fmt(probs[i] * 100, 0)}% (seen {c}×)</span></div>)}
      </div>
      <div className="viz-controls">
        {playing ? <button className="primary" onClick={() => setPlaying(false)}>⏸ Pause</button> : <button className="primary" onClick={() => setPlaying(true)}>▶ Play</button>}
        <button onClick={step} disabled={!cands.length}>Step ▶</button><button onClick={reset}>↺ Reset</button>
      </div>
    </section>
  );
}

// ----------------------------------------------------------------------------- attention (toy)
const PRON = new Set(["it", "he", "she", "they", "this", "that"]);
export function attentionMatrix(tokens: string[], causal: boolean): number[][] {
  const vec = tokens.map((t) => hashVector(t.toLowerCase(), 8));
  return tokens.map((qt, i) => {
    const scores = tokens.map((kt, j) => {
      if (causal && j > i) return -Infinity;
      let sc = vec[i].reduce((a, x, d) => a + x * vec[j][d], 0) / Math.sqrt(8);
      if (i === j) sc += 0.5;
      if (j === i - 1) sc += 0.4;                                      // nearby tokens matter
      if (PRON.has(qt.toLowerCase()) && j < i && kt.length > 3 && !PRON.has(kt.toLowerCase())) sc += 2 + (j / Math.max(1, i)) * 0.5;   // 'it' looks back at a content word
      return sc;
    });
    const finite = scores.map((x) => (Number.isFinite(x) ? x : -1e9));
    return softmax(finite, 1);
  });
}
export function AttentionViz({ lang }: { lang: Lang }) {
  const [text, setText] = useState("The animal did not cross the street because it was too tired");
  const [causal, setCausal] = useState(true);
  const toks = useMemo(() => words(text).slice(0, 14), [text]);
  const [q, setQ] = useState(toks.length - 1);
  const m = useMemo(() => attentionMatrix(toks, causal), [toks, causal]);
  const qi = Math.min(q, toks.length - 1);
  return (
    <section className="viz" aria-label={H[lang].attn}>
      <h3>{H[lang].attn}</h3>
      <p className="viz-note small">{NOTE} Real attention weights are learned by the model; here a simple rule (word similarity, nearness, and pronouns looking back at content words) draws a believable picture of the idea.</p>
      <div className="viz-inputs">
        <div><label htmlFor="a-t">Sentence</label><input id="a-t" value={text} onChange={(e) => { setText(e.target.value); setQ(words(e.target.value).slice(0, 14).length - 1); }} /></div>
        <label className="check"><input type="checkbox" checked={causal} onChange={(e) => setCausal(e.target.checked)} />Causal mask (a token only sees earlier tokens, like in GPT-style LLMs)</label>
      </div>
      <p className="small">Click a word to see where it "looks":</p>
      <div className="attn-words" role="group" aria-label="Pick the word that is looking">{toks.map((w, i) => <button key={i} className={i === qi ? "on" : ""} style={{ background: i === qi ? undefined : `rgba(59,91,219,${m[qi]?.[i] ?? 0})` }} aria-pressed={i === qi} onClick={() => setQ(i)}>{w}</button>)}</div>
      {toks.length > 0 && <p className="small" aria-live="polite"><b>{toks[qi]}</b> pays most attention to: {rank(m[qi]).slice(0, 3).filter((j) => m[qi][j] > 0.01).map((j) => `${toks[j]} (${fmt(m[qi][j] * 100, 0)}%)`).join(", ")}</p>}
      <div className="attn-grid scroll" role="img" aria-label="Attention weight matrix: rows look at columns" style={{ gridTemplateColumns: `auto repeat(${toks.length}, 1.9rem)` }}>
        <span />{toks.map((w, j) => <span key={`h${j}`} className="attn-h" title={w}>{w.slice(0, 3)}</span>)}
        {toks.map((w, i) => [<span key={`r${i}`} className="attn-h">{w}</span>, ...toks.map((_, j) => <span key={`${i}-${j}`} className={`attn-c ${i === qi ? "row" : ""}`} style={{ background: `rgba(59,91,219,${m[i][j]})` }} title={`${w} → ${toks[j]}: ${fmt(m[i][j] * 100, 0)}%`} />)])}
      </div>
    </section>
  );
}

// ----------------------------------------------------------------------------- context window
export interface Budget { parts: { name: string; tokens: number; kept: number }[]; window: number; used: number; droppedHistory: number; docsTruncated: boolean; overflow: boolean }
export function contextBudget(window: number, reserve: number, system: string, history: string[], docs: string, userMsg: string): Budget {
  const n = (s: string) => toyTokenize(s).length;
  const avail = Math.max(0, window - reserve);
  const sys = n(system), usr = n(userMsg), doc = n(docs);
  const hist = history.map(n);
  let left = avail - sys - usr;
  const fixedFits = left >= 0;
  left = Math.max(0, left);
  // newest history first: older messages are dropped when the budget is short
  let keptHist = 0, dropped = 0;
  for (let i = hist.length - 1; i >= 0; i--) { if (hist[i] <= left) { left -= hist[i]; keptHist += hist[i]; } else dropped++; }
  const keptDoc = Math.min(doc, left);
  return { parts: [{ name: "System prompt", tokens: sys, kept: sys }, { name: "Chat history", tokens: hist.reduce((a, b) => a + b, 0), kept: keptHist }, { name: "Documents (RAG)", tokens: doc, kept: keptDoc }, { name: "Your message", tokens: usr, kept: usr }, { name: "Reserved for the answer", tokens: reserve, kept: reserve }],
    window, used: sys + keptHist + keptDoc + usr + reserve, droppedHistory: dropped, docsTruncated: keptDoc < doc, overflow: !fixedFits };
}
export function ContextWindowViz({ lang }: { lang: Lang }) {
  const [win, setWin] = useState(120);
  const [reserve, setReserve] = useState(30);
  const [system, setSystem] = useState("You are a helpful HR assistant. Answer only from the documents.");
  const [hist, setHist] = useState("What is the leave policy?\nEmployees get 25 days.\nAnd parental leave?\nIt is 26 weeks for the primary caregiver.");
  const [docs, setDocs] = useState("Parental leave: 26 weeks for the primary caregiver and 4 weeks for the partner. Leave can be split into two blocks within the first year. Requests need manager approval at least 30 days in advance.");
  const [msg, setMsg] = useState("Can I split it?");
  const b = contextBudget(win, reserve, system, hist.split("\n").filter(Boolean), docs, msg);
  const colors = ["#6c5ce7", "#00a8a8", "#e8590c", "#3b5bdb", "#adb5bd"];
  return (
    <section className="viz" aria-label={H[lang].ctx}>
      <h3>{H[lang].ctx}</h3>
      <p className="viz-note small">Tokens are counted with a toy tokenizer, so the numbers differ from a real model's, but the budgeting logic is the same: reserve room for the answer, keep the newest history, trim what does not fit.</p>
      <div className="viz-inputs">
        <div><label htmlFor="c-w">Context window: {win} tokens</label><input id="c-w" type="range" min={40} max={400} step={10} value={win} onChange={(e) => setWin(Number(e.target.value))} /></div>
        <div><label htmlFor="c-r">Reserved for the answer: {reserve}</label><input id="c-r" type="range" min={0} max={100} step={5} value={reserve} onChange={(e) => setReserve(Number(e.target.value))} /></div>
        <div><label htmlFor="c-s">System prompt</label><input id="c-s" value={system} onChange={(e) => setSystem(e.target.value)} /></div>
        <div><label htmlFor="c-h">Chat history (one message per line)</label><textarea id="c-h" rows={3} value={hist} onChange={(e) => setHist(e.target.value)} /></div>
        <div><label htmlFor="c-d">Retrieved documents</label><textarea id="c-d" rows={3} value={docs} onChange={(e) => setDocs(e.target.value)} /></div>
        <div><label htmlFor="c-m">Your message</label><input id="c-m" value={msg} onChange={(e) => setMsg(e.target.value)} /></div>
      </div>
      <div className="ctx-bar" role="img" aria-label={`${b.used} of ${b.window} tokens used`}>
        {b.parts.map((p, i) => <i key={p.name} title={`${p.name}: ${p.kept}/${p.tokens}`} style={{ width: `${(p.kept / Math.max(win, b.used)) * 100}%`, background: colors[i] }} />)}
      </div>
      <ul className="ctx-legend small">{b.parts.map((p, i) => <li key={p.name}><i style={{ background: colors[i] }} />{p.name}: <b>{p.kept}</b>{p.kept < p.tokens ? ` of ${p.tokens} (cut)` : ""}</li>)}</ul>
      <p role="status" className={b.overflow || b.docsTruncated || b.droppedHistory ? "warn small" : "ok small"}>
        {b.overflow ? "The system prompt, your message and the answer reserve alone do not fit: the request would fail with 'context length exceeded'." : b.droppedHistory || b.docsTruncated ? `Did not all fit: ${b.droppedHistory ? `${b.droppedHistory} older message(s) dropped` : ""}${b.droppedHistory && b.docsTruncated ? "; " : ""}${b.docsTruncated ? "documents truncated" : ""}. The model cannot see what is cut.` : "Everything fits."}
      </p>
    </section>
  );
}

// ----------------------------------------------------------------------------- embeddings and semantic search
const SAMPLE = ["Our resignation procedure and notice period", "Submit your leaving letter to your manager", "The company pizza party is on Friday", "Dogs and cats are popular pets", "Reset your laptop password from the IT portal"];
export function EmbeddingViz({ lang }: { lang: Lang }) {
  const [query, setQuery] = useState("how do I quit my job");
  const [docsText, setDocsText] = useState(SAMPLE.join("\n"));
  const [k, setK] = useState(3);
  const docs = docsText.split("\n").map((d) => d.trim()).filter(Boolean).slice(0, 8);
  const qv = useMemo(() => toyEmbed(query), [query]);
  const sims = useMemo(() => docs.map((d) => cosine(qv, toyEmbed(d))), [docs, qv]);
  const order = rank(sims);
  const dims = Object.keys(CONCEPTS);
  const top = order[0];
  return (
    <section className="viz" aria-label={H[lang].emb}>
      <h3>{H[lang].emb}</h3>
      <p className="viz-note small">{NOTE} This toy embedder gives words from the same group (for example resign / quit / notice) a shared dimension, so related texts become similar even with no common word - what a real embedding model learns automatically.</p>
      <div className="viz-inputs">
        <div><label htmlFor="e-q">Query</label><input id="e-q" value={query} onChange={(e) => setQuery(e.target.value)} /></div>
        <div><label htmlFor="e-d">Documents (one per line)</label><textarea id="e-d" rows={5} value={docsText} onChange={(e) => setDocsText(e.target.value)} /></div>
        <div><label htmlFor="e-k">Top-k: {k}</label><input id="e-k" type="range" min={1} max={5} value={k} onChange={(e) => setK(Number(e.target.value))} /></div>
      </div>
      <p className="small"><b>Vector of the query</b> (concept dimensions): {dims.map((d, i) => `${d}=${qv[i]}`).join("  ")}</p>
      <div className="bars" role="table" aria-label="Cosine similarity of every document with the query">
        {order.map((i, n) => (
          <div key={i} className={`bar-row ${n < k ? "pick" : "dim"}`} role="row">
            <span role="cell" className="bar-label wide">{docs[i]}</span>
            <span className="bar-track" role="cell"><i className="bar-final" style={{ width: `${Math.max(0, sims[i]) * 100}%` }} /></span>
            <span role="cell" className="small">{fmt(sims[i])} {n < k ? "← retrieved" : ""}</span>
          </div>
        ))}
      </div>
      {docs.length > 0 && <p className="muted small">Cosine similarity = dot(a, b) / (|a| |b|), from 0 (unrelated) to 1 (same direction). The vector database returns the top-{k} nearest vectors; here that is a plain sort, an index does the same job faster at scale. Best match: <b>{docs[top]}</b> ({fmt(sims[top])}); shared words with the query: {contentWords(query).filter((w) => contentWords(docs[top]).includes(w)).join(", ") || "none - matched by meaning"}.</p>}
    </section>
  );
}
