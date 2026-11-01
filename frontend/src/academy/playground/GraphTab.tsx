import { useEffect, useMemo, useState } from "react";
import { academy } from "../../api";
import { GraphDiagram } from "../../GraphDiagram";
import { errText } from "../../ui";
import type { GraphPreset, GraphRun, GraphSpec } from "../types";

const TYPES = ["set", "increment", "append", "uppercase", "concat", "noop"];
const OPS = ["==", "!=", "<", "<=", ">", ">=", "contains"];
const num = (v: string): string | number => (v.trim() !== "" && !Number.isNaN(Number(v)) ? Number(v) : v);

/** LangGraph playground: describe a graph (state, nodes, edges, a conditional edge, a pause point), run it on the real LangGraph library and step through the state changes. */
export function LangGraphPlayground({ ws: _ws }: { ws: string }) {
  const [presets, setPresets] = useState<Record<string, GraphPreset>>({});
  const [name, setName] = useState("loop");
  const [spec, setSpec] = useState<GraphSpec | null>(null);
  const [input, setInput] = useState("{}");
  const [json, setJson] = useState(false);
  const [jsonText, setJsonText] = useState("");
  const [maxSteps, setMaxSteps] = useState(15);
  const [run, setRun] = useState<GraphRun | null>(null);
  const [idx, setIdx] = useState(0);
  const [edit, setEdit] = useState("{}");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => { academy.pgPresets().then((p) => { setPresets(p); const f = p.loop; setSpec(f.spec); setInput(JSON.stringify(f.input)); }).catch((e) => setErr(errText(e))); }, []);
  const choose = (n: string) => { const p = presets[n]; if (!p) return; setName(n); setSpec(structuredClone(p.spec)); setInput(JSON.stringify(p.input)); setRun(null); setJsonText(JSON.stringify(p.spec, null, 1)); };
  const upd = (fn: (s: GraphSpec) => GraphSpec) => spec && setSpec(fn(structuredClone(spec)));
  const ids = useMemo(() => spec?.nodes.map((n) => n.id) ?? [], [spec]);
  const targets = [...ids, "END"];

  async function go(resume = false) {
    if (!spec) return;
    setBusy(true); setErr(null);
    try {
      let r: GraphRun;
      if (resume && run) r = await academy.pgGraphResume({ thread_id: run.thread_id, state_update: JSON.parse(edit || "{}"), max_steps: maxSteps });
      else r = await academy.pgGraphRun({ spec: json ? JSON.parse(jsonText) : spec, input: JSON.parse(input || "{}"), max_steps: maxSteps });
      setRun(r); setIdx(0);
    } catch (e) { setErr(e instanceof SyntaxError ? `That is not valid JSON: ${e.message}` : errText(e)); } finally { setBusy(false); }
  }
  const cur = run?.steps[Math.min(idx, (run?.steps.length ?? 1) - 1)];
  const prev = run && idx > 0 ? run.steps[idx - 1].state_after : {};
  if (!spec) return <div className="muted">{err ?? "Loading…"}</div>;
  return (
    <section aria-label="LangGraph playground">
      <h2>LangGraph playground</h2>
      <p className="muted small">Runs on the real <code>langgraph</code> library with checkpoints. Nodes are limited to safe built-in types (set, increment, append, uppercase, concat, noop) - no learner code runs here; use the code runner for that.</p>
      <div className="viz-inputs">
        <div><label htmlFor="g-pre">Start from a preset</label><select id="g-pre" value={name} onChange={(e) => choose(e.target.value)}>{Object.entries(presets).map(([k, p]) => <option key={k} value={k}>{p.label}</option>)}</select></div>
        <div><label htmlFor="g-in">Initial state (JSON)</label><input id="g-in" value={input} onChange={(e) => setInput(e.target.value)} /></div>
        <div><label htmlFor="g-max">Step limit: {maxSteps}</label><input id="g-max" type="range" min={2} max={25} value={maxSteps} onChange={(e) => setMaxSteps(Number(e.target.value))} /></div>
        <label className="check"><input type="checkbox" checked={json} onChange={(e) => { setJson(e.target.checked); setJsonText(JSON.stringify(spec, null, 1)); }} />Edit as JSON</label>
      </div>

      {json ? <textarea aria-label="Graph specification (JSON)" rows={14} value={jsonText} onChange={(e) => setJsonText(e.target.value)} className="cm-fallback" /> : (
        <div className="ac-builder">
          <h3>State</h3>
          <div className="row">{Object.entries(spec.state).map(([k, t]) => <span key={k} className="badge">{k}: {t} <button className="small" aria-label={`Remove state key ${k}`} onClick={() => upd((s) => { delete s.state[k]; return s; })}>×</button></span>)}
            <button className="small" onClick={() => { const k = `key${Object.keys(spec.state).length + 1}`; upd((s) => ({ ...s, state: { ...s.state, [k]: "int" } })); }}>+ key</button></div>
          <h3>Nodes</h3>
          {spec.nodes.map((n, i) => (
            <div key={i} className="row ac-node">
              <input aria-label={`Node ${i + 1} id`} value={n.id} onChange={(e) => upd((s) => { s.nodes[i].id = e.target.value; return s; })} style={{ width: 110 }} />
              <select aria-label={`Node ${i + 1} type`} value={n.type} onChange={(e) => upd((s) => { s.nodes[i].type = e.target.value; return s; })}>{TYPES.map((t) => <option key={t}>{t}</option>)}</select>
              {n.type !== "noop" && <select aria-label={`Node ${i + 1} state key`} value={n.key ?? ""} onChange={(e) => upd((s) => { s.nodes[i].key = e.target.value; return s; })}><option value="">key…</option>{Object.keys(spec.state).map((k) => <option key={k}>{k}</option>)}</select>}
              {(n.type === "set" || n.type === "append") && <input aria-label={`Node ${i + 1} value`} placeholder="value" value={String(n.value ?? "")} onChange={(e) => upd((s) => { s.nodes[i].value = num(e.target.value); return s; })} style={{ width: 120 }} />}
              {n.type === "increment" && <input aria-label={`Node ${i + 1} by`} type="number" value={n.by ?? 1} onChange={(e) => upd((s) => { s.nodes[i].by = Number(e.target.value); return s; })} style={{ width: 70 }} />}
              {n.type === "concat" && <input aria-label={`Node ${i + 1} template`} placeholder="text with {key}" value={n.template ?? ""} onChange={(e) => upd((s) => { s.nodes[i].template = e.target.value; return s; })} />}
              <label className="check"><input type="checkbox" aria-label={`Pause before ${n.id}`} checked={spec.interrupt_before?.includes(n.id) ?? false} onChange={(e) => upd((s) => { const set = new Set(s.interrupt_before ?? []); if (e.target.checked) set.add(n.id); else set.delete(n.id); s.interrupt_before = [...set]; return s; })} />pause before</label>
              <button className="small danger" aria-label={`Remove node ${n.id}`} onClick={() => upd((s) => ({ ...s, nodes: s.nodes.filter((_, k) => k !== i), edges: s.edges.filter(([a, b]) => a !== n.id && b !== n.id) }))}>×</button>
            </div>
          ))}
          <button className="small" onClick={() => upd((s) => ({ ...s, nodes: [...s.nodes, { id: `node${s.nodes.length + 1}`, type: "noop" }] }))}>+ node</button>
          <h3>Edges</h3>
          <div className="row"><label className="row" style={{ margin: 0 }}>Entry node <select aria-label="Entry node" value={spec.entry} onChange={(e) => upd((s) => ({ ...s, entry: e.target.value }))}>{ids.map((i) => <option key={i}>{i}</option>)}</select></label></div>
          {spec.edges.map(([a, b], i) => <div key={i} className="row"><select aria-label={`Edge ${i + 1} from`} value={a} onChange={(e) => upd((s) => { s.edges[i][0] = e.target.value; return s; })}>{ids.map((x) => <option key={x}>{x}</option>)}</select>→<select aria-label={`Edge ${i + 1} to`} value={b} onChange={(e) => upd((s) => { s.edges[i][1] = e.target.value; return s; })}>{targets.map((x) => <option key={x}>{x}</option>)}</select><button className="small danger" aria-label={`Remove edge ${i + 1}`} onClick={() => upd((s) => ({ ...s, edges: s.edges.filter((_, k) => k !== i) }))}>×</button></div>)}
          <button className="small" onClick={() => upd((s) => ({ ...s, edges: [...s.edges, [ids[0], "END"]] }))}>+ edge</button>
          <h3>Conditional routing</h3>
          {spec.conditional.map((c, i) => (
            <div key={i} className="row ac-node">if after <select aria-label={`Condition ${i + 1} source`} value={c.source} onChange={(e) => upd((s) => { s.conditional[i].source = e.target.value; return s; })}>{ids.map((x) => <option key={x}>{x}</option>)}</select>
              <select aria-label={`Condition ${i + 1} key`} value={c.key} onChange={(e) => upd((s) => { s.conditional[i].key = e.target.value; return s; })}>{Object.keys(spec.state).map((k) => <option key={k}>{k}</option>)}</select>
              <select aria-label={`Condition ${i + 1} operator`} value={c.op} onChange={(e) => upd((s) => { s.conditional[i].op = e.target.value; return s; })}>{OPS.map((o) => <option key={o}>{o}</option>)}</select>
              <input aria-label={`Condition ${i + 1} value`} value={String(c.value)} onChange={(e) => upd((s) => { s.conditional[i].value = num(e.target.value); return s; })} style={{ width: 80 }} />
              then <select aria-label={`Condition ${i + 1} then`} value={c.then} onChange={(e) => upd((s) => { s.conditional[i].then = e.target.value; return s; })}>{targets.map((x) => <option key={x}>{x}</option>)}</select>
              else <select aria-label={`Condition ${i + 1} otherwise`} value={c.otherwise} onChange={(e) => upd((s) => { s.conditional[i].otherwise = e.target.value; return s; })}>{targets.map((x) => <option key={x}>{x}</option>)}</select>
              <button className="small danger" aria-label={`Remove condition ${i + 1}`} onClick={() => upd((s) => ({ ...s, conditional: s.conditional.filter((_, k) => k !== i) }))}>×</button></div>
          ))}
          <button className="small" onClick={() => upd((s) => ({ ...s, conditional: [...s.conditional, { source: ids[0], key: Object.keys(s.state)[0], op: "==", value: 0, then: "END", otherwise: "END" }] }))}>+ conditional edge</button>
        </div>
      )}

      <div className="viz-controls"><button className="primary" disabled={busy} onClick={() => void go()}>{busy ? "Running…" : "▶ Run the graph"}</button></div>
      {err && <div className="error" role="alert">{err}</div>}
      {run && (
        <div aria-label="Run result">
          <p className={run.status === "finished" ? "ok" : run.status === "paused" ? "warn" : "bad"} role="status"><b>{run.status}</b>{run.message ? `: ${run.message}` : ""} · {run.steps.length} step(s) · {run.ms} ms</p>
          <GraphDiagram info={{ nodes: run.graph.nodes.map((id) => ({ id, description: "" })), edges: run.graph.edges.map(([source, target, conditional]) => ({ source, target, conditional })), mermaid: "" }} visited={cur ? [cur.node] : []} />
          {run.steps.length > 0 && cur && (
            <div>
              <div className="viz-controls"><button disabled={idx === 0} onClick={() => setIdx(idx - 1)}>◀ Back</button><button disabled={idx >= run.steps.length - 1} onClick={() => setIdx(idx + 1)}>Step ▶</button><span className="muted small">step {idx + 1} / {run.steps.length}: node <b>{cur.node}</b> ({cur.ms} ms)</span></div>
              <div className="viz-io"><div><span className="muted small">Node returned (the update)</span><pre>{JSON.stringify(cur.update)}</pre></div>
                <div><span className="muted small">State after this step (changed keys marked ●)</span><pre>{Object.entries(cur.state_after).map(([k, v]) => `${JSON.stringify(prev[k]) !== JSON.stringify(v) ? "●" : " "} ${k}: ${JSON.stringify(v)}`).join("\n")}</pre></div></div>
            </div>
          )}
          {run.status === "paused" && (
            <div className="ac-setup"><b>Waiting for a person.</b> The run is saved at a checkpoint before <code>{run.pending[0]}</code>. Optionally edit the state, then approve.
              <label htmlFor="g-edit">State changes (JSON, optional)</label><input id="g-edit" value={edit} onChange={(e) => setEdit(e.target.value)} />
              <button className="primary small" disabled={busy} onClick={() => void go(true)}>✓ Approve and continue</button></div>
          )}
          <details><summary className="small">Execution history ({run.history.length} checkpoints)</summary>
            <table aria-label="Checkpoints"><thead><tr><th>Step</th><th>Next</th><th>State</th></tr></thead><tbody>{run.history.map((h, i) => <tr key={i}><td>{h.step}</td><td>{h.next.join(", ") || "–"}</td><td className="small">{JSON.stringify(h.state)}</td></tr>)}</tbody></table></details>
          <p className="small"><b>Final state:</b> <code>{JSON.stringify(run.final_state)}</code></p>
        </div>
      )}
    </section>
  );
}
