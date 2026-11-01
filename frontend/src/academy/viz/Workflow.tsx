import { useEffect, useMemo, useRef, useState } from "react";
import { GraphDiagram } from "../../GraphDiagram";
import type { GraphInfo } from "../../types";
import type { Lang } from "../types";
import { say, type InputDef, type Scene, type Values } from "./scenes";

const defaults = (inputs: InputDef[]): Values => Object.fromEntries(inputs.map((i) => [i.key, i.default]));
const reduceMotion = () => typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const UI = {
  en: { play: "Play", pause: "Pause", reset: "Reset", step: "Step", back: "Back", speed: "Speed", input: "Input", output: "Output", simple: "In simple words", tech: "Technical details", hideTech: "Hide technical details", state: "State", stage: "Stage", note: "A simplified teaching model that runs in your browser: the numbers are illustrative. The Playground runs the real thing on the server." },
  hi: { play: "चलाएँ", pause: "रोकें", reset: "फिर से", step: "अगला", back: "पीछे", speed: "गति", input: "Input", output: "Output", simple: "आसान शब्दों में", tech: "तकनीकी विवरण", hideTech: "विवरण छिपाएँ", state: "State", stage: "चरण", note: "यह आपके browser में चलने वाला सरल शिक्षण model है: numbers सिर्फ़ समझाने के लिए हैं। असली चीज़ Playground में server पर चलती है।" },
  hinglish: { play: "Play", pause: "Pause", reset: "Reset", step: "Agla step", back: "Peeche", speed: "Speed", input: "Input", output: "Output", simple: "Aasan shabdon mein", tech: "Technical details", hideTech: "Details chhupao", state: "State", stage: "Stage", note: "Yeh aapke browser mein chalne wala simplified teaching model hai: numbers sirf samjhane ke liye hain. Asli cheez Playground mein server par chalti hai." },
} as const;

/** Generic animated workflow: stages are recomputed from the learner's inputs, played with Play/Pause/Step/Reset, with input, output and explanations per stage. */
export function Workflow({ scene, lang }: { scene: Scene; lang: Lang }) {
  const t = UI[lang];
  const [values, setValues] = useState<Values>(() => defaults(scene.inputs));
  const [variant, setVariant] = useState(scene.variants?.[0]?.id ?? "");
  const [idx, setIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [tech, setTech] = useState(false);
  const stages = useMemo(() => scene.build(values, variant), [scene, values, variant]);
  const last = stages.length - 1;
  const cur = stages[Math.min(idx, last)];
  const stageRefs = useRef<(HTMLButtonElement | null)[]>([]);

  useEffect(() => { setIdx((i) => Math.min(i, last)); }, [last]);
  useEffect(() => {
    if (!playing) return;
    if (idx >= last) { setPlaying(false); return; }
    const id = setTimeout(() => setIdx((i) => Math.min(i + 1, last)), (reduceMotion() ? 900 : 1500) / speed);
    return () => clearTimeout(id);
  }, [playing, idx, last, speed]);
  useEffect(() => { stageRefs.current[idx]?.scrollIntoView?.({ block: "nearest", inline: "center" }); }, [idx]);

  const graph = useMemo<GraphInfo | null>(() => {
    const g = scene.graph?.(variant);
    if (!g) return null;
    const id = (n: string) => (n === "START" ? "__start__" : n === "END" ? "__end__" : n);
    return { nodes: g.nodes.map((n) => ({ id: id(n), description: "" })), edges: g.edges.map(([s, d, c]) => ({ source: id(s), target: id(d), conditional: Boolean(c) })), mermaid: "" };
  }, [scene, variant]);

  const set = (k: string, v: string | number) => { setValues((o) => ({ ...o, [k]: v })); setIdx(0); setPlaying(false); };
  const play = () => { if (idx >= last) setIdx(0); setPlaying(true); };

  return (
    <section className="viz" aria-label={scene.title}>
      <h3>{scene.title}</h3>
      <p className="muted small">{scene.intro}</p>
      <p className="viz-note small">{t.note}</p>

      <div className="viz-inputs">
        {scene.variants && (
          <div><label htmlFor={`v-${scene.id}`}>Pattern</label>
            <select id={`v-${scene.id}`} value={variant} onChange={(e) => { setVariant(e.target.value); setIdx(0); setPlaying(false); }}>{scene.variants.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}</select></div>
        )}
        {scene.inputs.map((i) => (
          <div key={i.key}><label htmlFor={`${scene.id}-${i.key}`}>{i.label}</label>
            {i.type === "textarea" ? <textarea id={`${scene.id}-${i.key}`} rows={3} value={String(values[i.key])} onChange={(e) => set(i.key, e.target.value)} />
              : i.type === "select" ? <select id={`${scene.id}-${i.key}`} value={String(values[i.key])} onChange={(e) => set(i.key, e.target.value)}>{i.options!.map((o) => <option key={o}>{o}</option>)}</select>
                : <input id={`${scene.id}-${i.key}`} type={i.type === "number" ? "number" : "text"} min={i.min} max={i.max} value={String(values[i.key])} onChange={(e) => set(i.key, i.type === "number" ? Number(e.target.value) : e.target.value)} />}</div>
        ))}
      </div>

      <div className="viz-controls" role="group" aria-label="Playback">
        {playing ? <button className="primary" onClick={() => setPlaying(false)}>⏸ {t.pause}</button> : <button className="primary" onClick={play}>▶ {t.play}</button>}
        <button onClick={() => { setPlaying(false); setIdx((i) => Math.max(0, i - 1)); }} disabled={idx === 0} aria-label={t.back}>◀ {t.back}</button>
        <button onClick={() => { setPlaying(false); setIdx((i) => Math.min(last, i + 1)); }} disabled={idx >= last}>{t.step} ▶</button>
        <button onClick={() => { setPlaying(false); setIdx(0); }}>↺ {t.reset}</button>
        <label className="row" style={{ margin: 0 }}>{t.speed}<select aria-label={t.speed} value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>{[0.5, 1, 2].map((s) => <option key={s} value={s}>{s}×</option>)}</select></label>
        <span className="muted small" aria-live="polite">{t.stage} {Math.min(idx, last) + 1} / {stages.length}</span>
      </div>

      <ol className="viz-flow" aria-label="Workflow stages">
        {stages.map((s, n) => (
          <li key={s.id}>
            <button ref={(el) => { stageRefs.current[n] = el; }} className={`${n === idx ? "on" : n < idx ? "done" : ""}`} aria-current={n === idx ? "step" : undefined} onClick={() => { setPlaying(false); setIdx(n); }}>{s.label}</button>
          </li>
        ))}
      </ol>

      {graph && <GraphDiagram info={graph} visited={(cur.active ?? []).map((n) => (n === "START" ? "__start__" : n === "END" ? "__end__" : n))} />}

      <div className="viz-detail" key={cur.id}>
        <h4>{cur.label}</h4>
        <p className="viz-simple"><b>{t.simple}:</b> {say(cur.simple, lang)}</p>
        <div className="viz-io">
          {cur.input !== undefined && <div><span className="muted small">{t.input}</span><pre>{cur.input}</pre></div>}
          <div><span className="muted small">{t.output}</span><pre>{cur.output}</pre></div>
        </div>
        {cur.segments && <div className="viz-seg" aria-label="Chunks of the text">{cur.segments.map((g, n) => <span key={n} className={`seg-${g.cls}`}>{g.text}</span>)}</div>}
        {cur.lines && <pre className="viz-lines">{cur.lines.join("\n")}</pre>}
        {cur.state && <div><span className="muted small">{t.state}</span><pre>{JSON.stringify(cur.state, null, 1)}</pre></div>}
        <button className="small" aria-expanded={tech} onClick={() => setTech(!tech)}>{tech ? t.hideTech : t.tech}</button>
        {tech && <p className="viz-tech">{cur.technical}</p>}
      </div>
    </section>
  );
}
