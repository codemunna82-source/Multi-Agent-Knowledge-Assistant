import { useEffect, useState } from "react";
import { academy } from "../../api";
import { errText } from "../../ui";
import type { AgentRun, PgCaps } from "../types";

const TASKS = ["What is 15% of 48000?", "Which documents do I have?", "How long is parental leave?", 'How many times does "leave" appear?', "Delete all my files"];
const LABEL: Record<string, string> = { plan: "Plan", tool_selected: "Tool chosen", tool_blocked: "Blocked", tool_result: "Tool result", reflection: "Check", final: "Final answer", error: "Problem" };

/** Agentic AI playground: give the agent a task and an explicit tool allow-list, then read the operational steps: which tool, with what input, what came back. */
export function AgentPlayground({ caps }: { ws: string; caps: PgCaps | null }) {
  const [tools, setTools] = useState<Record<string, string>>({});
  const [on, setOn] = useState<string[]>(["calculator", "search_documents", "list_documents"]);
  const [task, setTask] = useState(TASKS[0]);
  const [maxSteps, setMaxSteps] = useState(4);
  const [out, setOut] = useState<AgentRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { academy.pgAgentTools().then(setTools).catch((e) => setErr(errText(e))); }, []);
  async function go() { setBusy(true); setErr(null); try { setOut(await academy.pgAgent({ task, tools: on, max_steps: maxSteps })); } catch (e) { setErr(errText(e)); setOut(null); } finally { setBusy(false); } }
  return (
    <section aria-label="Agentic AI playground">
      <h2>Agentic AI playground</h2>
      <p className="muted small">The agent can only use the tools you tick; the application, not the prompt, enforces that. {caps?.llm.available ? `The model (${caps.llm.name}) chooses each step.` : "No LLM is configured, so a simple rule-based planner picks the tool - the loop, allow-list and trace are the same."}</p>
      <div className="chips">{TASKS.map((t) => <button key={t} className="small" onClick={() => setTask(t)}>{t}</button>)}</div>
      <label htmlFor="ag-task">Task</label><input id="ag-task" value={task} onChange={(e) => setTask(e.target.value)} maxLength={500} />
      <fieldset className="ac-tools"><legend>Allowed tools</legend>
        {Object.entries(tools).map(([n, d]) => <label key={n} className="check"><input type="checkbox" checked={on.includes(n)} onChange={(e) => setOn(e.target.checked ? [...on, n] : on.filter((x) => x !== n))} /><b>{n}</b> <span className="muted small">{d.split(" Input:")[0]}</span></label>)}</fieldset>
      <div className="viz-controls"><label className="row" style={{ margin: 0 }}>Step limit {maxSteps}<input type="range" aria-label="Step limit" min={1} max={6} value={maxSteps} onChange={(e) => setMaxSteps(Number(e.target.value))} /></label><button className="primary" disabled={busy || !task.trim()} onClick={() => void go()}>{busy ? "Running…" : "▶ Run the agent"}</button></div>
      {err && <div className="error" role="alert">{err}</div>}
      {out && (
        <div aria-label="Agent trace">
          <p className="muted small">Policy: {out.policy} · {out.ms} ms</p>
          <ol className="ac-trace">{out.steps.map((s) => (
            <li key={s.n} className={`t-${s.type}`}><span className="badge">{LABEL[s.type] ?? s.type}</span>{s.tool && <> <code>{s.tool}{s.input && Object.keys(s.input).length ? `(${JSON.stringify(s.input)})` : "()"}</code></>} <span>{s.text}</span>{s.ms !== undefined && <span className="muted small"> · {s.ms} ms</span>}</li>
          ))}</ol>
          <div className="ac-output" aria-label="Final answer">{out.final}</div>
          <p className="muted small">{out.note}</p>
        </div>
      )}
    </section>
  );
}
