import type { Catalog, Lang, LessonCard, Level, Progress } from "./types";

const LEVELS: Level[] = ["beginner", "intermediate", "advanced", "production"];
const LEVEL_TITLE: Record<Level, string> = { beginner: "Beginner", intermediate: "Intermediate", advanced: "Advanced", production: "Production" };

interface Props {
  catalog: Catalog; progress: Progress | null; cards: Record<string, LessonCard>; lang: Lang;
  onOpen: (id: string) => void; go: (v: "roadmap" | "playground" | "projects" | "interview" | "daily") => void;
}

export function Dashboard({ catalog, progress, cards, lang, onOpen, go }: Props) {
  const cont = progress?.continue?.lesson ? cards[progress.continue.lesson] : null;
  const started = progress && Object.keys(progress.lessons).length > 0;
  return (
    <div className="ac-dash">
      <h1>AI Learning Academy</h1>
      <p className="muted">Learn LLMs, RAG, LangChain, LangGraph and agents step by step: simple explanations in English, Hindi and Hinglish, animations you can control, and code you can run.</p>

      <section aria-label="Continue learning" className="ac-block">
        <h2>Continue learning</h2>
        {cont ? (
          <div className="row"><div><b>{cont.title[lang]}</b><div className="muted small">{started ? "Pick up where you left off" : "A good place to start"} · ~{cont.minutes} min</div></div><span className="grow" /><button className="primary" onClick={() => onOpen(cont.id)}>{started ? "Resume" : "Start"} →</button></div>
        ) : <p className="muted">You have finished every available lesson. Try a project or daily practice.</p>}
      </section>

      <section aria-label="My learning progress" className="ac-block">
        <h2>My learning progress</h2>
        <div className="ac-stats">
          <div><b>{progress?.done ?? 0}</b><span>of {progress?.total ?? 0} lessons done</span></div>
          <div><b>{progress?.streak ?? 0}</b><span>day streak</span></div>
          <div><b>{progress?.bookmarks.length ?? 0}</b><span>bookmarked</span></div>
          <div><b>{Object.values(progress?.quiz ?? {}).reduce((a, q) => a + q.correct, 0)}/{Object.values(progress?.quiz ?? {}).reduce((a, q) => a + q.total, 0)}</b><span>quiz answers right</span></div>
        </div>
        <div className="ac-bars">
          {(progress?.categories ?? catalog.categories.map((c) => ({ id: c.id, title: c.title.en, lessons: c.lessons.length, done: 0, percent: 0 }))).map((c) => (
            <div key={c.id} className="ac-bar">
              <span>{catalog.categories.find((x) => x.id === c.id)?.title[lang === "hi" ? "hi" : "en"] ?? c.title}</span>
              <progress max={100} value={c.percent} aria-label={`${c.title} progress`} /><span className="muted small">{c.done}/{c.lessons}</span>
            </div>
          ))}
        </div>
        {progress && progress.weak.length > 0 && (
          <div className="ac-weak"><b>Topics to revise</b><div className="chips">{progress.weak.filter((w) => cards[w]).map((w) => <button key={w} onClick={() => onOpen(w)}>{cards[w].title[lang]}</button>)}</div></div>
        )}
      </section>

      <section aria-label="Recommended lessons" className="ac-block">
        <h2>Recommended lessons</h2>
        <div className="ac-reco">{(progress?.recommended ?? []).filter((r) => cards[r]).map((r) => (
          <button key={r} className="ac-card" onClick={() => onOpen(r)}><b>{cards[r].title[lang]}</b><span className="muted small">{cards[r].summary}</span></button>
        ))}</div>
      </section>

      <section aria-label="Beginner to advanced roadmap" className="ac-block">
        <h2>Beginner to Advanced roadmap</h2>
        <div className="ac-road">{LEVELS.map((lv) => {
          const items = catalog.roadmap[lv];
          const ids = [...new Set(items.map((i) => i.lesson).filter(Boolean) as string[])];
          const done = ids.filter((i) => progress?.lessons[i]?.status === "done").length;
          return <button key={lv} className="ac-card" onClick={() => go("roadmap")}><b>{LEVEL_TITLE[lv]}</b><span className="muted small">{done}/{ids.length} lessons · {items.filter((i) => i.planned).length} planned</span></button>;
        })}</div>
      </section>

      <section className="ac-tiles" aria-label="Practice and projects">
        <button className="ac-card" onClick={() => go("playground")}><b>Interactive AI Playground</b><span className="muted small">Try prompts, embeddings, RAG, LangChain, LangGraph and agents with real backend calls.</span></button>
        <button className="ac-card" onClick={() => go("projects")}><b>Practical projects</b><span className="muted small">Ten guided builds, from a PDF chatbot to a production agent.</span></button>
        <button className="ac-card" onClick={() => go("interview")}><b>Interview preparation</b><span className="muted small">Questions with concise model answers.</span></button>
        <button className="ac-card" onClick={() => go("daily")}><b>Daily practice</b><span className="muted small">Five questions a day, weak topics first.</span></button>
      </section>
    </div>
  );
}
