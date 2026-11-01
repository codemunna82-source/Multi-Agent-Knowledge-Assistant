import { useRef, useState } from "react";
import { academy, sseFetch } from "../../api";
import { errText } from "../../ui";
import type { CompareRun, LlmEvent, LlmRun, PgCaps } from "../types";
import { Unavailable, UsageLine } from "./common";

const EXAMPLES: [string, string, string][] = [
  ["Explain simply", "You are a patient teacher for beginners.", "Explain what an embedding is in three sentences."],
  ["Extract fields", "Reply with JSON only.", "Extract name and age: 'Asha Rao is 31 years old and lives in Pune.'"],
  ["Creative", "You are a poet.", "Write two lines about a dragon who is afraid of fire."],
];

/** LLM playground: your prompt, system instructions and sampling parameters, optionally streamed token by token, with usage and latency from the real provider. */
export function LlmPlayground({ ws, caps }: { ws: string; caps: PgCaps | null }) {
  const [system, setSystem] = useState(EXAMPLES[0][1]);
  const [prompt, setPrompt] = useState(EXAMPLES[0][2]);
  const [temperature, setTemperature] = useState(0.7);
  const [maxTokens, setMaxTokens] = useState(200);
  const [stream, setStream] = useState(true);
  const [busy, setBusy] = useState(false);
  const [text, setText] = useState("");
  const [run, setRun] = useState<{ model?: string; usage?: LlmRun["usage"]; ms?: number; first?: number | null } | null>(null);
  const [unavailable, setUnavailable] = useState<{ setup?: string | null; request?: LlmRun["request"] } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const ctl = useRef<AbortController | null>(null);
  const params = { system, prompt, temperature, max_tokens: maxTokens };

  async function go() {
    setBusy(true); setErr(null); setText(""); setRun(null); setUnavailable(null);
    const c = new AbortController(); ctl.current = c;
    try {
      if (stream) {
        await sseFetch<LlmEvent>("/academy/playground/llm/stream", ws, params, (e) => {
          if (e.type === "token") setText((t) => t + e.text);
          else if (e.type === "done") setRun({ model: e.model, usage: e.usage, ms: e.latency_ms, first: e.first_token_ms });
          else if (e.type === "unavailable") setUnavailable({ setup: e.setup, request: e.request });
          else if (e.type === "error") setErr(e.detail);
        }, c.signal);
      } else {
        const r = await academy.pgLlm(params);
        if (!r.available) setUnavailable({ setup: r.setup, request: r.request }); else { setText(r.text ?? ""); setRun({ model: r.model, usage: r.usage, ms: r.latency_ms }); }
      }
    } catch (e) { if (!(e instanceof DOMException && e.name === "AbortError")) setErr(errText(e)); } finally { setBusy(false); ctl.current = null; }
  }
  return (
    <section aria-label="LLM playground">
      <h2>LLM playground</h2>
      <p className="muted small">Send a real request to the configured model. Change the system instructions and sampling parameters and see how the answer changes.</p>
      <div className="chips">{EXAMPLES.map(([n, s, p]) => <button key={n} className="small" onClick={() => { setSystem(s); setPrompt(p); }}>{n}</button>)}</div>
      <div className="viz-inputs">
        <div><label htmlFor="pg-sys">System instructions</label><textarea id="pg-sys" rows={3} value={system} onChange={(e) => setSystem(e.target.value)} maxLength={4000} /></div>
        <div><label htmlFor="pg-prompt">Your prompt</label><textarea id="pg-prompt" rows={3} value={prompt} onChange={(e) => setPrompt(e.target.value)} maxLength={8000} /></div>
        <div><label htmlFor="pg-temp">Temperature: {temperature.toFixed(2)}</label><input id="pg-temp" type="range" min={0} max={2} step={0.05} value={temperature} onChange={(e) => setTemperature(Number(e.target.value))} /></div>
        <div><label htmlFor="pg-max">Max tokens</label><input id="pg-max" type="number" min={1} max={caps?.limits.max_tokens ?? 1000} value={maxTokens} onChange={(e) => setMaxTokens(Number(e.target.value))} /></div>
      </div>
      <div className="viz-controls">
        <label className="check"><input type="checkbox" checked={stream} onChange={(e) => setStream(e.target.checked)} />Stream token by token</label>
        {busy ? <button className="primary" onClick={() => ctl.current?.abort()}>■ Stop</button> : <button className="primary" disabled={!prompt.trim()} onClick={() => void go()}>▶ Run</button>}
      </div>
      {err && <div className="error" role="alert">{err}</div>}
      {unavailable && <Unavailable what="A language model" setup={unavailable.setup} request={unavailable.request} />}
      {(text || busy) && <div className="ac-output" aria-live="polite" aria-label="Model output">{text}{busy && <span className="caret" aria-hidden="true" />}</div>}
      {run && <UsageLine model={run.model} usage={run.usage} ms={run.ms} first={run.first} />}
    </section>
  );
}

const SHOTS: Record<string, (task: string) => string> = {
  "zero-shot": (t) => `Classify the sentiment as positive, negative or neutral.\nText: ${t}\nSentiment:`,
  "one-shot": (t) => `Classify the sentiment as positive, negative or neutral.\nText: The delivery was late and the box was damaged.\nSentiment: negative\n\nText: ${t}\nSentiment:`,
  "few-shot": (t) => `Classify the sentiment as positive, negative or neutral.\nText: The delivery was late and the box was damaged.\nSentiment: negative\n\nText: Great quality, works as described.\nSentiment: positive\n\nText: It arrived on Tuesday.\nSentiment: neutral\n\nText: ${t}\nSentiment:`,
};

/** Prompt engineering playground: 2-3 prompts side by side, with zero/one/few-shot templates, and a comparison of the outputs. */
export function PromptPlayground({ ws: _ws, caps: _caps }: { ws: string; caps: PgCaps | null }) {
  const task = "I expected more for the price, but the support team was kind.";
  const [variants, setVariants] = useState([{ name: "zero-shot", system: "", prompt: SHOTS["zero-shot"](task) }, { name: "few-shot", system: "", prompt: SHOTS["few-shot"](task) }]);
  const [temperature, setTemperature] = useState(0);
  const [out, setOut] = useState<CompareRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const upd = (i: number, k: "name" | "system" | "prompt", v: string) => setVariants(variants.map((x, n) => (n === i ? { ...x, [k]: v } : x)));
  async function go() { setBusy(true); setErr(null); try { setOut(await academy.pgCompare({ variants, temperature, max_tokens: 150 })); } catch (e) { setErr(errText(e)); } finally { setBusy(false); } }
  return (
    <section aria-label="Prompt engineering playground">
      <h2>Prompt engineering playground</h2>
      <p className="muted small">Write two or three prompts for the same task, run them with the same settings and compare. Use the buttons to fill a prompt with a zero-shot, one-shot or few-shot template.</p>
      <div className="ac-variants">
        {variants.map((v, i) => (
          <div key={i} className="ac-variant">
            <div className="row"><input aria-label={`Variant ${i + 1} name`} value={v.name} onChange={(e) => upd(i, "name", e.target.value)} maxLength={40} style={{ maxWidth: 160 }} />
              {Object.keys(SHOTS).map((s) => <button key={s} className="small" aria-label={`Variant ${i + 1}: ${s} template`} onClick={() => upd(i, "prompt", SHOTS[s](task))}>{s}</button>)}
              {variants.length > 2 && <button className="small danger" aria-label={`Remove variant ${i + 1}`} onClick={() => setVariants(variants.filter((_, n) => n !== i))}>×</button>}</div>
            <label htmlFor={`pv-s${i}`}>System</label><input id={`pv-s${i}`} value={v.system} onChange={(e) => upd(i, "system", e.target.value)} />
            <label htmlFor={`pv-p${i}`}>Prompt</label><textarea id={`pv-p${i}`} rows={7} value={v.prompt} onChange={(e) => upd(i, "prompt", e.target.value)} />
          </div>
        ))}
      </div>
      <div className="viz-controls">
        {variants.length < 3 && <button onClick={() => setVariants([...variants, { name: "variant 3", system: "", prompt: SHOTS["one-shot"](task) }])}>+ Add a variant</button>}
        <label className="row" style={{ margin: 0 }}>Temperature {temperature.toFixed(2)}<input type="range" aria-label="Comparison temperature" min={0} max={1.5} step={0.05} value={temperature} onChange={(e) => setTemperature(Number(e.target.value))} /></label>
        <button className="primary" disabled={busy || variants.some((v) => !v.prompt.trim())} onClick={() => void go()}>{busy ? "Running…" : "▶ Run and compare"}</button>
      </div>
      {err && <div className="error" role="alert">{err}</div>}
      {out && !out.available && <Unavailable what="A language model" setup={out.setup} request={out.variants[0].request} />}
      {out?.available && (
        <div className="ac-variants" aria-label="Comparison results">
          {out.variants.map((v) => (
            <div key={v.name} className="ac-variant"><h4>{v.name}</h4><div className="ac-output">{v.text}</div>
              <p className="muted small">{v.words} words · {v.latency_ms} ms · {(v.usage?.prompt_tokens ?? 0) + (v.usage?.completion_tokens ?? 0)} tokens</p>
              {v.similarity_to_first !== undefined && <p className="small">Similarity to the first output: <b>{Math.round(v.similarity_to_first * 100)}%</b>{v.only_here?.length ? <> · only here: {v.only_here.join(", ")}</> : null}{v.missing_vs_first?.length ? <> · missing: {v.missing_vs_first.join(", ")}</> : null}</p>}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
