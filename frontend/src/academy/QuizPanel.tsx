import { useState } from "react";
import { academy } from "../api";
import type { QuizOut, QuizQuestion } from "./types";
import { errText } from "../ui";

type Q = QuizQuestion & { lesson?: string };

/** Multiple-choice practice. Answers are graded on the server, which also explains why the right option is right and why each other option is wrong. */
export function QuizPanel({ questions, title, onGraded, label = "Quiz" }: { questions: Q[]; title?: string; onGraded?: (r: QuizOut) => void; label?: string }) {
  const [picked, setPicked] = useState<Record<string, number>>({});
  const [out, setOut] = useState<QuizOut | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const graded = Object.fromEntries((out?.results ?? []).map((r) => [r.id, r]));
  async function submit() {
    setBusy(true);
    try { const r = await academy.submitQuiz(picked); setOut(r); setErr(null); onGraded?.(r); } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  if (!questions.length) return null;
  return (
    <section className="ac-quiz" aria-label={label}>
      {title && <h3>{title}</h3>}
      {questions.map((q, n) => {
        const r = graded[q.id];
        return (
          <fieldset key={q.id} disabled={Boolean(r)}>
            <legend><b>{n + 1}.</b> {q.q} {q.kind === "scenario" && <span className="badge">scenario</span>}</legend>
            {q.options.map((o, i) => (
              <label key={i} className={`opt ${r ? (i === r.answer ? "right" : i === r.selected ? "wrong" : "") : ""}`}>
                <input type="radio" name={q.id} checked={picked[q.id] === i} onChange={() => setPicked({ ...picked, [q.id]: i })} />{o}
                {r && i === r.answer && <span className="why"> ✓ Correct. {r.why}</span>}
                {r && i !== r.answer && <span className="why"> {r.why_not[String(i)]}</span>}
              </label>
            ))}
            {r && <div role="status" className={r.correct ? "ok small" : "bad small"}>{r.correct ? "Correct" : "Not quite"}</div>}
          </fieldset>
        );
      })}
      {err && <div className="error" role="alert">{err}</div>}
      {!out ? <button className="primary" disabled={busy || Object.keys(picked).length === 0} onClick={() => void submit()}>Submit answers</button> : (
        <div className="row"><b role="status">Score: {out.score} / {out.total} ({out.percent}%)</b><button onClick={() => { setOut(null); setPicked({}); }}>Try again</button></div>
      )}
    </section>
  );
}
