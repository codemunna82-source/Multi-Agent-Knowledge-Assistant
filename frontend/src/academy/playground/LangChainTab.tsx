import { useMemo, useState } from "react";
import { academy } from "../../api";
import { errText } from "../../ui";
import { Editor, Console } from "../CodeLab";
import type { LcRun, PgCaps, RunOut } from "../types";
import { Unavailable } from "./common";

const SAMPLE_CODE = `from langchain_core.prompts import ChatPromptTemplate
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.output_parsers import StrOutputParser

prompt = ChatPromptTemplate.from_messages([("system", "You are a {role}."), ("human", "{question}")])
model = FakeListChatModel(responses=["Paris is the capital of France."])
chain = prompt | model | StrOutputParser()

print(chain.invoke({"role": "teacher", "question": "Capital of France?"}))
# Try: change the reply, swap StrOutputParser for CommaSeparatedListOutputParser, or add a RunnableLambda step.
`;
const VARS = /\{([A-Za-z_][A-Za-z0-9_]*)\}/g;

/** LangChain playground: build prompt | model | parser pipelines and see each component's input and output, or edit and run real langchain-core code in the sandbox. */
export function LangChainPlayground({ ws: _ws, caps }: { ws: string; caps: PgCaps | null }) {
  const [tab, setTab] = useState<"build" | "code">("build");
  const [pattern, setPattern] = useState("sequence");
  const [system, setSystem] = useState("You are a {role}.");
  const [template, setTemplate] = useState("{question}");
  const [vars, setVars] = useState<Record<string, string>>({ role: "geography teacher", question: "What is the capital of France?" });
  const [model, setModel] = useState("fake");
  const [reply, setReply] = useState("Paris, France, Europe");
  const [parser, setParser] = useState("str");
  const [out, setOut] = useState<LcRun | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const names = useMemo(() => [...new Set([...system.matchAll(VARS), ...template.matchAll(VARS)].map((m) => m[1]))], [system, template]);
  const [code, setCode] = useState(SAMPLE_CODE);
  const [run, setRun] = useState<RunOut | null>(null);
  const [running, setRunning] = useState(false);

  async function go() {
    setBusy(true); setErr(null);
    try { setOut(await academy.pgLangchain({ pattern, system, template, variables: Object.fromEntries(names.map((n) => [n, vars[n] ?? ""])), model, fake_reply: reply, parser, temperature: 0, max_tokens: 200 })); } catch (e) { setErr(errText(e)); setOut(null); } finally { setBusy(false); }
  }
  async function exec() { setRunning(true); try { setRun(await academy.runCode({ language: "python", code, task: "scratch" })); } catch (e) { setErr(errText(e)); } finally { setRunning(false); } }
  return (
    <section aria-label="LangChain playground">
      <h2>LangChain playground</h2>
      <div className="seg" role="tablist" aria-label="LangChain playground mode"><button role="tab" aria-selected={tab === "build"} className={tab === "build" ? "on" : ""} onClick={() => setTab("build")}>Pipeline builder</button><button role="tab" aria-selected={tab === "code"} className={tab === "code" ? "on" : ""} onClick={() => setTab("code")}>Edit and run code</button></div>
      {tab === "build" && (
        <div>
          <p className="muted small">Real <code>langchain_core</code> objects run on the server. Placeholders look like <code>{"{name}"}</code>; every placeholder needs a value below.</p>
          <div className="viz-inputs">
            <div><label htmlFor="lc-pattern">Pattern</label><select id="lc-pattern" value={pattern} onChange={(e) => setPattern(e.target.value)}><option value="sequence">prompt | model | parser (RunnableSequence)</option><option value="parallel">RunnableParallel (chain + a lambda)</option></select></div>
            <div><label htmlFor="lc-sys">System template</label><input id="lc-sys" value={system} onChange={(e) => setSystem(e.target.value)} /></div>
            <div><label htmlFor="lc-tpl">Human template</label><textarea id="lc-tpl" rows={2} value={template} onChange={(e) => setTemplate(e.target.value)} /></div>
            {names.map((n) => <div key={n}><label htmlFor={`lc-v-${n}`}>Value of {`{${n}}`}</label><input id={`lc-v-${n}`} value={vars[n] ?? ""} onChange={(e) => setVars({ ...vars, [n]: e.target.value })} /></div>)}
            <div><label htmlFor="lc-model">Model</label><select id="lc-model" value={model} onChange={(e) => setModel(e.target.value)}><option value="fake">Fake model (canned reply, free)</option><option value="configured">The configured LLM{caps && !caps.llm.available ? " (not configured)" : ""}</option></select></div>
            {model === "fake" && <div><label htmlFor="lc-reply">Fake model reply</label><input id="lc-reply" value={reply} onChange={(e) => setReply(e.target.value)} /></div>}
            <div><label htmlFor="lc-parser">Output parser</label><select id="lc-parser" value={parser} onChange={(e) => setParser(e.target.value)}><option value="str">StrOutputParser (text)</option><option value="list">CommaSeparatedListOutputParser</option><option value="json">JsonOutputParser</option></select></div>
          </div>
          <button className="primary" disabled={busy} onClick={() => void go()}>{busy ? "Running…" : "▶ Run the chain"}</button>
          {err && <div className="error" role="alert">{err}</div>}
          {out && !out.available && <Unavailable what="A language model" setup={out.setup} />}
          {out?.available && (
            <div>
              <p className="small">Chain: <code>{out.chain?.join(" | ")}</code> · model {out.model} · {out.latency_ms} ms</p>
              <table aria-label="Components"><thead><tr><th>Component</th><th>Input</th><th>Output</th><th>ms</th></tr></thead>
                <tbody>{out.steps?.map((s, i) => <tr key={i}><td><b>{s.name}</b><div className="muted small">{s.kind}</div></td><td className="small">{s.input}</td><td className="small">{s.output}</td><td>{s.ms}</td></tr>)}</tbody></table>
              {out.error ? <div className="error" role="alert">{out.error}</div> : <div><b className="small">Final output</b><pre className="out" aria-label="Chain output">{typeof out.output === "string" ? out.output : JSON.stringify(out.output, null, 1)}</pre></div>}
            </div>
          )}
        </div>
      )}
      {tab === "code" && (
        <div>
          <p className="muted small">Edit the code and run it in the sandbox (no network, time and memory limits). <code>langchain_core</code> and <code>langgraph</code> are installed; provider packages such as <code>langchain-openai</code> are not.</p>
          <Editor value={code} onChange={setCode} language="python" label="LangChain sample code" />
          <div className="row ac-code-bar"><button className="primary small" disabled={running || caps?.code_runner.available === false} onClick={() => void exec()}>{running ? "Running…" : "▶ Run code"}</button><button className="small" onClick={() => { setCode(SAMPLE_CODE); setRun(null); }}>↺ Reset code</button></div>
          {caps?.code_runner.available === false && <p className="ac-setup small">The code runner is off on this server: {caps.code_runner.reason}</p>}
          {run && <Console out={run} />}
        </div>
      )}
    </section>
  );
}
