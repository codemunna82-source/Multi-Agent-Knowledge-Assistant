import { lazy, Suspense, useEffect, useState } from "react";
import { academy } from "../api";
import { errText } from "../ui";
import type { CodeExample, CodeStatus, RunOut, Task } from "./types";

const CodeEditor = lazy(() => import("./CodeEditor"));
let statusPromise: Promise<CodeStatus> | null = null;
export const resetCodeStatus = () => { statusPromise = null; };
const useCodeStatus = () => {
  const [s, setS] = useState<CodeStatus | null>(null);
  useEffect(() => { (statusPromise ??= academy.codeStatus()).then(setS).catch(() => { statusPromise = null; setS(null); }); }, []);
  return s;
};

/** The editor: lazy CodeMirror, with a plain textarea while it loads (or if it cannot load). */
export function Editor({ value, onChange, language, label }: { value: string; onChange: (v: string) => void; language: "python" | "javascript"; label: string }) {
  return (
    <Suspense fallback={<textarea className="cm-fallback" aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} rows={Math.min(14, value.split("\n").length + 1)} spellCheck={false} />}>
      <CodeEditor value={value} onChange={onChange} language={language} label={label} />
    </Suspense>
  );
}

async function copy(t: string): Promise<boolean> { try { await navigator.clipboard.writeText(t); return true; } catch { return false; } }

export function Console({ out, expected }: { out: RunOut; expected?: string }) {
  if (out.unavailable) return <div className="ac-console warn" role="status"><b>The code runner is not available on this server.</b><p className="small">{out.unavailable}</p></div>;
  return (
    <div className="ac-console" role="region" aria-label="Output console">
      <div className="small muted">exit code {out.exit_code ?? "–"} · {out.ms} ms{out.timed_out ? " · stopped: time limit" : ""}{out.truncated ? " · output was cut" : ""}</div>
      {out.stdout && <pre className="out">{out.stdout}</pre>}
      {out.stderr && <pre className="err">{out.stderr}</pre>}
      {!out.stdout && !out.stderr && <pre className="out muted">(no output)</pre>}
      {(out.notes ?? []).map((n) => <div key={n} className="warn small">{n}</div>)}
      {out.timed_out && <div className="warn small">The program ran longer than the time limit. Look for an endless loop.</div>}
      {out.error_help && <div className="ac-help" role="note"><b>What this error means:</b> {out.error_help}</div>}
      {out.passed === true && <div className="ok" role="status">✓ The output matches the expected output.</div>}
      {out.passed === false && expected !== undefined && !out.error_help && <div className="bad" role="status">✗ Not yet. The output differs from the expected output below.</div>}
    </div>
  );
}

/** A lesson's code example: editable, runnable in the sandbox, with reset/copy, expected output and a line-by-line explanation. */
export function CodeLab({ example, lessonId, index }: { example: CodeExample; lessonId: string; index: number }) {
  const [code, setCode] = useState(example.code);
  const [out, setOut] = useState<RunOut | null>(null);
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [explain, setExplain] = useState(false);
  const status = useCodeStatus();
  useEffect(() => { setCode(example.code); setOut(null); }, [example.code]);
  async function run() {
    setRunning(true); setErr(null);
    try { setOut(await academy.runCode({ language: example.language, code, lesson_id: lessonId, task: code === example.code ? "example" : "scratch", example: index })); } catch (e) { setErr(errText(e)); } finally { setRunning(false); }
  }
  const edited = code !== example.code;
  return (
    <div className="ac-code">
      <div className="row"><b>{example.title}</b><span className="grow" /><span className="badge">{example.language}</span></div>
      <Editor value={code} onChange={setCode} language={example.language} label={`Code: ${example.title}`} />
      <div className="row ac-code-bar">
        {example.runnable ? <button className="primary small" disabled={running || status?.available === false} onClick={() => void run()}>{running ? "Running…" : "▶ Run code"}</button> : null}
        <button className="small" disabled={!edited} onClick={() => { setCode(example.code); setOut(null); }}>↺ Reset code</button>
        <button className="small" onClick={async () => { setCopied(await copy(code)); setTimeout(() => setCopied(false), 1500); }}>{copied ? "✓ Copied" : "Copy code"}</button>
        <button className="small" aria-expanded={explain} onClick={() => setExplain(!explain)}>{explain ? "Hide" : "Line-by-line explanation"}</button>
      </div>
      {!example.runnable && <div className="ac-setup" role="note"><b>Not run here.</b> {example.setup}</div>}
      {example.runnable && status && !status.available && <div className="ac-setup" role="note"><b>The code runner is off on this server.</b> {status.reason} Copy the code and run it on your own machine; the expected output is shown below.</div>}
      {err && <div className="error" role="alert">{err}</div>}
      {out && <Console out={out} expected={example.expected_output} />}
      {example.runnable && <details open={!out}><summary className="small">Expected output</summary><pre className="out">{example.expected_output}</pre>{edited && <p className="muted small">You changed the code, so your output can differ.</p>}</details>}
      {example.runnable === false && <p className="muted small">The text this program prints varies per run or needs credentials, so no expected output is shown.</p>}
      {explain && <ol className="ac-explain">{example.explain.map((e, i) => <li key={i}><code>lines {e.lines}</code> {e.text}</li>)}</ol>}
    </div>
  );
}

/** A graded practice task (exercise or debugging challenge): run, compare with the expected output, hint, and a solution unlocked after one attempt. */
export function TaskLab({ task, kind, lessonId, title, onResult }: { task: Task; kind: "exercise" | "debug"; lessonId: string; title: string; onResult?: () => void }) {
  const [code, setCode] = useState(task.starter);
  const [out, setOut] = useState<RunOut | null>(null);
  const [running, setRunning] = useState(false);
  const [hint, setHint] = useState(false);
  const [sol, setSol] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const status = useCodeStatus();
  async function run() {
    setRunning(true); setMsg(null);
    try { setOut(await academy.runCode({ language: "python", code, lesson_id: lessonId, task: kind })); onResult?.(); } catch (e) { setMsg(errText(e)); } finally { setRunning(false); }
  }
  async function showSolution() {
    setMsg(null);
    try { setSol((await academy.solution(lessonId, kind)).solution); } catch (e) { setMsg(errText(e)); }
  }
  return (
    <div className="ac-code ac-task" role="group" aria-label={title}>
      <div className="row"><b>{title}</b></div>
      <p className="ac-p">{task.prompt}</p>
      <Editor value={code} onChange={setCode} language="python" label={`${title} code`} />
      <div className="row ac-code-bar">
        <button className="primary small" disabled={running || status?.available === false} onClick={() => void run()}>{running ? "Checking…" : "▶ Run and check"}</button>
        <button className="small" onClick={() => { setCode(task.starter); setOut(null); }}>↺ Reset code</button>
        <button className="small" aria-expanded={hint} onClick={() => setHint(!hint)}>Hint</button>
        <button className="small" onClick={() => void showSolution()}>Show solution</button>
      </div>
      {status && !status.available && <div className="ac-setup" role="note"><b>The code runner is off on this server.</b> You can still work on the task in your own editor; the expected output is below.</div>}
      {hint && <div className="ac-help" role="note"><b>Hint:</b> {task.hint}</div>}
      {msg && <div className="warn small" role="alert">{msg}</div>}
      {out && <Console out={out} expected={task.expected_output} />}
      <details><summary className="small">Expected output</summary><pre className="out">{task.expected_output}</pre></details>
      {sol && <div><b className="small">Reference solution</b><Editor value={sol} onChange={() => undefined} language="python" label={`${title} solution`} /></div>}
    </div>
  );
}
