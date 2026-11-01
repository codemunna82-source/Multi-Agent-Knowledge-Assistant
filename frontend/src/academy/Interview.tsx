import { useMemo, useState } from "react";
import { academy } from "../api";
import { errText, useLoad } from "../ui";

export function Interview({ categories }: { categories: Record<string, string> }) {
  const all = useLoad(() => academy.interview(), []);
  const [cat, setCat] = useState("");
  const [level, setLevel] = useState("");
  const [text, setText] = useState("");
  const items = useMemo(() => (all.data ?? []).filter((i) => (!cat || i.category === cat) && (!level || i.level === level) && (!text || (i.q + " " + i.a).toLowerCase().includes(text.toLowerCase()))), [all.data, cat, level, text]);
  const cats = useMemo(() => [...new Set((all.data ?? []).map((i) => i.category))], [all.data]);
  return (
    <div className="ac-block">
      <h1>Interview preparation</h1>
      <p className="muted">Short, spoken-style answers. Read the question, say your answer aloud, then compare.</p>
      <div className="row">
        <label>Topic <select value={cat} onChange={(e) => setCat(e.target.value)}><option value="">All</option>{cats.map((c) => <option key={c} value={c}>{categories[c] ?? c}</option>)}</select></label>
        <label>Level <select value={level} onChange={(e) => setLevel(e.target.value)}><option value="">All</option><option value="beginner">Beginner</option><option value="intermediate">Intermediate</option><option value="advanced">Advanced</option></select></label>
        <label>Search <input value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. chunking" /></label>
      </div>
      {all.error && <div className="error" role="alert">{errText(all.error)}</div>}
      <p className="muted small">{items.length} question{items.length === 1 ? "" : "s"}</p>
      {items.map((i, n) => (
        <details key={n} className="ac-qa"><summary>{i.q} <span className="muted small">· {i.level}</span></summary><p>{i.a}</p></details>
      ))}
    </div>
  );
}
