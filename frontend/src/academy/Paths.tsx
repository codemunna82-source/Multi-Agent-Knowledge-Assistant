import { useState } from "react";
import type { Lang, LearningPath, LessonCard, Progress } from "./types";

const KEY = "mka_academy_path";
export const loadPath = (): string | null => { try { return localStorage.getItem(KEY); } catch { return null; } };
export const savePath = (id: string | null) => { try { if (id) localStorage.setItem(KEY, id); else localStorage.removeItem(KEY); } catch { /* ignore */ } };

/** Two questions -> one of the goal paths. Pure, so it is easy to test. */
export function recommendPath(experience: "new" | "some" | "dev", goal: "understand" | "chatbot" | "agents" | "production" | "interview"): string {
  if (experience === "new" && goal !== "interview") return "new-to-ai";            // a complete beginner starts with the basics whatever the goal
  return { understand: "new-to-ai", chatbot: "doc-chatbot", agents: "agent-builder", production: "go-live", interview: "interview-ready" }[goal];
}

const Q1: [string, "new" | "some" | "dev"][] = [["I am new to AI and programming", "new"], ["I know some Python, but not AI", "some"], ["I am a developer and want to build things", "dev"]];
const Q2: [string, "understand" | "chatbot" | "agents" | "production" | "interview"][] = [["Just understand what AI is", "understand"], ["Build a chatbot over my documents", "chatbot"], ["Build AI agents", "agents"], ["Take an AI app to production", "production"], ["Prepare for an interview", "interview"]];

export function pathProgress(p: LearningPath, progress: Progress | null) {
  const done = p.lessons.filter((l) => progress?.lessons[l]?.status === "done").length;
  const next = p.lessons.find((l) => progress?.lessons[l]?.status !== "done") ?? null;
  return { done, total: p.lessons.length, next };
}

export function Paths({ paths, chosen, onChoose, progress, cards, lang, onOpen }: {
  paths: LearningPath[]; chosen: string | null; onChoose: (id: string | null) => void; progress: Progress | null; cards: Record<string, LessonCard>; lang: Lang; onOpen: (id: string) => void;
}) {
  const [quiz, setQuiz] = useState(false);
  const [exp, setExp] = useState<"new" | "some" | "dev" | null>(null);
  const [rec, setRec] = useState<string | null>(null);
  const mine = paths.find((p) => p.id === chosen) ?? null;

  if (mine) {
    const pr = pathProgress(mine, progress);
    const next = pr.next ? cards[pr.next] : null;
    return (
      <section aria-label="Your learning path" className="ac-block ac-path">
        <div className="row"><h2 style={{ margin: 0 }}>{mine.icon} Your path: {mine.title[lang]}</h2><span className="grow" /><button className="small" onClick={() => onChoose(null)}>Change path</button></div>
        <p className="muted small">{mine.summary}</p>
        <progress max={pr.total} value={pr.done} aria-label="Path progress" /> <span className="muted small">{pr.done} of {pr.total} lessons done</span>
        <ol className="ac-pathlist">
          {mine.lessons.filter((l) => cards[l]).map((l) => {
            const st = progress?.lessons[l]?.status;
            return <li key={l} className={st === "done" ? "done" : l === pr.next ? "next" : ""}><button onClick={() => onOpen(l)}><span className="mark">{st === "done" ? "✓" : l === pr.next ? "▶" : "○"}</span> {cards[l].title[lang]} <span className="muted small">~{cards[l].minutes} min</span></button></li>;
          })}
        </ol>
        {next ? <button className="primary" onClick={() => onOpen(next.id)}>{pr.done ? "Next on your path" : "Start your path"}: {next.title[lang]} →</button> : <p><b>You finished this path. 🎉</b> Pick another one or try a project.</p>}
      </section>
    );
  }

  return (
    <section aria-label="Choose your learning path" className="ac-block ac-path">
      <h2>What do you want to learn?</h2>
      <p className="muted small">Pick a goal and the Academy shows the lessons in the best order. You can change it any time.</p>
      <div className="ac-pathcards">
        {paths.map((p) => <button key={p.id} className="ac-card" onClick={() => onChoose(p.id)}><b>{p.icon} {p.title[lang]}</b><span className="muted small">{p.summary}</span><span className="muted small">{p.lessons.length} lessons</span></button>)}
      </div>
      {!quiz ? <button className="small" onClick={() => setQuiz(true)}>Not sure? Answer 2 quick questions</button> : (
        <div className="ac-pathquiz" role="group" aria-label="Find my path">
          {!exp ? (<><b>1. Where are you now?</b><div className="chips">{Q1.map(([t, v]) => <button key={v} onClick={() => setExp(v)}>{t}</button>)}</div></>)
            : !rec ? (<><b>2. What do you want to do first?</b><div className="chips">{Q2.map(([t, v]) => <button key={v} onClick={() => setRec(recommendPath(exp, v))}>{t}</button>)}</div></>)
              : (<><b>We suggest: {paths.find((p) => p.id === rec)?.title[lang]}</b><div className="row"><button className="primary" onClick={() => onChoose(rec)}>Use this path</button><button className="small" onClick={() => { setExp(null); setRec(null); }}>Start again</button></div></>)}
        </div>
      )}
    </section>
  );
}
