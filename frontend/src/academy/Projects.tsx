import { useState } from "react";
import { academy } from "../api";
import { errText, useLoad } from "../ui";
import type { Project, ProjectCard } from "./types";

/** Left-to-right layers: loop-back edges (found by DFS) are ignored, then each node sits one layer after its deepest predecessor. */
export function layers(nodes: string[], edges: [string, string][]): string[][] {
  const state: Record<string, 0 | 1 | 2> = {};
  const fwd: [string, string][] = [];
  const dfs = (n: string) => {
    state[n] = 1;
    for (const [a, b] of edges) {
      if (a !== n) continue;
      if (state[b] === 1) continue;           // back edge = a loop, not a layer
      fwd.push([a, b]);
      if (!state[b]) dfs(b);
    }
    state[n] = 2;
  };
  nodes.forEach((n) => { if (!state[n]) dfs(n); });
  const level: Record<string, number> = {};
  const depth = (n: string): number => (level[n] ??= Math.max(-1, ...fwd.filter(([, b]) => b === n).map(([a]) => depth(a))) + 1);
  nodes.forEach((n) => depth(n));
  const out: string[][] = [];
  nodes.forEach((n) => { (out[level[n]] ??= []).push(n); });
  return out.filter(Boolean);
}

function Architecture({ nodes, edges }: { nodes: string[]; edges: [string, string][] }) {
  const cols = layers(nodes, edges);
  return (
    <figure className="ac-arch" aria-label="Architecture diagram">
      <div className="ac-arch-cols">{cols.map((c, i) => <div key={i} className="ac-arch-col">{c.map((n) => <div key={n} className="ac-arch-node">{n}</div>)}</div>)}</div>
      <figcaption className="muted small">Connections: {edges.map(([a, b]) => `${a} → ${b}`).join(" · ")}</figcaption>
    </figure>
  );
}

function CodeBlock({ name, code }: { name: string; code: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => { try { await navigator.clipboard.writeText(code); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* clipboard unavailable */ } };
  return (
    <div className="ac-code">
      <div className="row"><b>{name}</b><span className="grow" /><button className="small" onClick={() => void copy()}>{copied ? "Copied" : "Copy"}</button></div>
      <pre tabIndex={0}><code>{code}</code></pre>
    </div>
  );
}

function ProjectDetail({ id, onBack, onChanged }: { id: string; onBack: () => void; onChanged: () => void }) {
  const d = useLoad(() => academy.project(id), [id]);
  const [done, setDone] = useState<number[] | null>(null);
  const [file, setFile] = useState<string | null>(null);
  const p = d.data as (Project & { steps: { title: string; detail: string; file?: string }[]; files: Record<string, string>; api_tests: { title: string; command: string }[]; deploy: string; interview: string; prereq: string[] }) | null;
  if (d.error) return <div className="error" role="alert">{errText(d.error)}</div>;
  if (!p) return <div className="muted">Loading project…</div>;
  const ticks = done ?? p.done_steps ?? [];
  const toggle = (i: number) => {
    const next = ticks.includes(i) ? ticks.filter((x) => x !== i) : [...ticks, i];
    setDone(next);
    academy.setProject(id, next).then(onChanged).catch(() => setDone(ticks));
  };
  const names = Object.keys(p.files);
  const shown = file && p.files[file] !== undefined ? file : names[0];
  return (
    <article className="ac-block">
      <button className="small" onClick={onBack}>← All projects</button>
      <h1>{p.title}</h1>
      <p>{p.summary}</p>
      <p className="muted">{p.level} · about {p.hours} h · {p.stack.join(", ")}</p>
      <h2>Architecture</h2><Architecture nodes={p.architecture.nodes} edges={p.architecture.edges} />
      <h2>Folder structure</h2><pre tabIndex={0}><code>{p.folders}</code></pre>
      <h2>Steps <span className="muted small">({ticks.length}/{p.steps.length} done)</span></h2>
      <ol className="ac-steps">
        {p.steps.map((s, i) => (
          <li key={i}>
            <label><input type="checkbox" checked={ticks.includes(i)} onChange={() => toggle(i)} /> <b>{s.title}</b></label>
            <div>{s.detail}</div>
            {s.file && <button className="small" onClick={() => setFile(s.file!)}>Show {s.file}</button>}
          </li>
        ))}
      </ol>
      <h2>Complete code</h2>
      <div className="seg" role="tablist" aria-label="Project files">{names.map((n) => <button key={n} role="tab" aria-selected={n === shown} className={n === shown ? "on" : ""} onClick={() => setFile(n)}>{n}</button>)}</div>
      <CodeBlock name={shown} code={p.files[shown]} />
      <h2>Test the API</h2>
      {p.api_tests.map((t) => <CodeBlock key={t.title} name={t.title} code={t.command} />)}
      <h2>Deploy</h2><pre className="ac-wrap">{p.deploy}</pre>
      <h2>How to explain it in an interview</h2><blockquote>{p.interview}</blockquote>
    </article>
  );
}

export function Projects({ onChanged }: { onChanged: () => void }) {
  const list = useLoad<ProjectCard[]>(() => academy.projects(), []);
  const [open, setOpen] = useState<string | null>(null);
  if (open) return <ProjectDetail id={open} onBack={() => { setOpen(null); void list.reload(); }} onChanged={onChanged} />;
  return (
    <div className="ac-block">
      <h1>Guided projects</h1>
      <p className="muted">Ten projects from a PDF chatbot to a production-ready agent. Every project ships complete files and tests that run offline; each says where to plug in a real model.</p>
      {list.error && <div className="error" role="alert">{errText(list.error)}</div>}
      <div className="ac-grid">
        {(list.data ?? []).map((p) => (
          <button key={p.id} className="ac-card" onClick={() => setOpen(p.id)}>
            <b>{p.title}</b><span>{p.summary}</span>
            <span className="muted small">{p.level} · {p.hours} h · {p.done}/{p.steps} steps</span>
          </button>
        ))}
      </div>
    </div>
  );
}
