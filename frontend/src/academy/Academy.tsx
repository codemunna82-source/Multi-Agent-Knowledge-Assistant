import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { academy } from "../api";
import { errText, useLoad } from "../ui";
import { Dashboard } from "./Dashboard";
import { LessonView } from "./LessonView";
import { Playground } from "./Playground";
import { QuizPanel } from "./QuizPanel";
import { SidePanel } from "./SidePanel";
import type { Lang, Level, LessonCard } from "./types";

type View = { kind: "dashboard" | "roadmap" | "playground" | "projects" | "interview" | "daily" } | { kind: "lesson"; id: string };
const LANG_KEY = "mka_academy_lang";
const loadLang = (): Lang => { try { const v = localStorage.getItem(LANG_KEY); if (v === "en" || v === "hi" || v === "hinglish") return v; } catch { /* ignore */ } return "en"; };
const LANGS: [Lang, string][] = [["en", "English"], ["hi", "हिंदी"], ["hinglish", "Hinglish"]];
const NAV: [Exclude<View["kind"], "lesson">, string][] = [["dashboard", "Dashboard"], ["roadmap", "Roadmap"], ["playground", "Playground"], ["projects", "Projects"], ["interview", "Interview prep"], ["daily", "Daily practice"]];

export function Academy({ workspace }: { workspace: string }) {
  const catalog = useLoad(() => academy.catalog(), []);
  const progress = useLoad(() => academy.progress(), []);
  const glossary = useLoad(() => academy.glossary(), []);
  const [view, setView] = useState<View>({ kind: "dashboard" });
  const [lang, setLangState] = useState<Lang>(loadLang);
  const [termId, setTermId] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Awaited<ReturnType<typeof academy.search>>>([]);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [showSide, setShowSide] = useState(false);
  const setLang = (l: Lang) => { setLangState(l); try { localStorage.setItem(LANG_KEY, l); } catch { /* ignore */ } };   // progress lives on the server; changing language never touches it

  const cards = useMemo(() => Object.fromEntries((catalog.data?.categories ?? []).flatMap((c) => c.lessons).map((l) => [l.id, l])) as Record<string, LessonCard>, [catalog.data]);
  const order = useMemo(() => (catalog.data?.categories ?? []).flatMap((c) => c.lessons.map((l) => l.id)), [catalog.data]);
  const lessonId = view.kind === "lesson" ? view.id : null;
  const lesson = useLoad(() => (lessonId ? academy.lesson(lessonId) : Promise.resolve(null)), [lessonId]);
  const daily = useLoad(() => (view.kind === "daily" ? academy.daily() : Promise.resolve(null)), [view.kind]);

  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => {
    clearTimeout(timer.current);
    if (q.trim().length < 2) { setHits([]); return; }
    timer.current = setTimeout(() => { academy.search(q.trim()).then(setHits).catch(() => setHits([])); }, 250);
    return () => clearTimeout(timer.current);
  }, [q]);

  const openLesson = useCallback((id: string) => {
    setView({ kind: "lesson", id }); setQ(""); setShowSide(false);
    void academy.setProgress(id, {}).then(() => progress.reload()).catch(() => undefined);   // opening a lesson starts it
    document.getElementById("ac-top")?.scrollIntoView?.({ block: "start" });
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps
  const go = (k: Exclude<View["kind"], "lesson">) => { setView({ kind: k }); setShowSide(false); };

  const cat = lessonId ? catalog.data?.categories.find((c) => c.id === cards[lessonId]?.category) : null;
  const status = (id: string) => progress.data?.lessons[id]?.status;
  const term = termId ? glossary.data?.[termId] ?? null : null;

  if (catalog.error) return <div className="card"><div className="error" role="alert">{catalog.error}</div><button onClick={() => void catalog.reload()}>Retry</button></div>;
  if (!catalog.data) return <div className="card muted">Loading the Academy…</div>;

  return (
    <div className={`ac ${showSide ? "show-side" : ""}`}>
      <nav className="ac-nav" aria-label="Academy navigation">
        <input type="search" aria-label="Search lessons" placeholder="Search lessons and terms…" value={q} onChange={(e) => setQ(e.target.value)} />
        {q.trim().length >= 2 && (
          <div className="ac-hits" role="listbox" aria-label="Search results">
            {hits.length === 0 && <span className="muted small">No match</span>}
            {hits.map((h, i) => h.glossary ? <button key={i} onClick={() => { setTermId(h.glossary!); setQ(""); setShowSide(true); }}>📖 {h.term}</button> : <button key={h.id} onClick={() => openLesson(h.id)}>{h.title[lang]}</button>)}
          </div>
        )}
        <div className="ac-menu">{NAV.map(([k, label]) => <button key={k} className={view.kind === k ? "on" : ""} aria-current={view.kind === k ? "page" : undefined} onClick={() => go(k)}>{label}</button>)}</div>
        <h3>Learning categories</h3>
        {catalog.data.categories.map((c) => (
          <details key={c.id} open={open[c.id] ?? c.lessons.some((l) => l.id === lessonId)} onToggle={(e) => setOpen({ ...open, [c.id]: (e.target as HTMLDetailsElement).open })}>
            <summary>{c.title[lang === "hi" ? "hi" : "en"]} <span className="muted small">{c.lessons.filter((l) => status(l.id) === "done").length}/{c.lessons.length}</span></summary>
            <ul>{c.lessons.map((l) => <li key={l.id}><button className={l.id === lessonId ? "on" : ""} aria-current={l.id === lessonId ? "page" : undefined} onClick={() => openLesson(l.id)}>{status(l.id) === "done" ? "✓ " : status(l.id) ? "• " : "○ "}{l.title[lang]}</button></li>)}
              {c.lessons.length === 0 && <li className="muted small">Lessons coming soon</li>}</ul>
          </details>
        ))}
      </nav>

      <main className="ac-main">
        <div className="ac-top" id="ac-top">
          <nav aria-label="Breadcrumb" className="ac-crumbs small">
            <button className="link" onClick={() => go("dashboard")}>AI Learning Academy</button>
            {cat && <> › <span>{cat.title.en}</span></>}
            {lessonId && cards[lessonId] && <> › <b>{cards[lessonId].title.en}</b></>}
            {view.kind !== "dashboard" && view.kind !== "lesson" && <> › <b>{NAV.find(([k]) => k === view.kind)?.[1]}</b></>}
          </nav>
          <span className="grow" />
          <div className="seg" role="group" aria-label="Explanation language">{LANGS.map(([l, label]) => <button key={l} aria-pressed={lang === l} className={lang === l ? "on" : ""} onClick={() => setLang(l)}>{label}</button>)}</div>
          <button className="small ac-side-toggle" aria-expanded={showSide} onClick={() => setShowSide(!showSide)}>Notes &amp; terms</button>
        </div>

        {view.kind === "dashboard" && <Dashboard catalog={catalog.data} progress={progress.data} cards={cards} lang={lang} onOpen={openLesson} go={(k) => go(k)} />}
        {view.kind === "roadmap" && <Roadmap catalog={catalog.data} progress={progress.data} cards={cards} lang={lang} onOpen={openLesson} />}
        {view.kind === "lesson" && (lesson.error ? <div className="error" role="alert">{lesson.error}</div> : lesson.data
          ? <LessonView lesson={lesson.data} lang={lang} progress={progress.data} cards={cards} order={order} onTerm={(id) => { setTermId(id); setShowSide(true); }} onOpen={openLesson} onChanged={() => void progress.reload()} />
          : <div className="muted">Loading lesson…</div>)}
        {view.kind === "daily" && (
          <div className="ac-block"><h1>Daily practice</h1><p className="muted">Five questions picked for today. Questions from topics you found hard come first.</p>
            {daily.error && <div className="error" role="alert">{errText(daily.error)}</div>}
            {daily.data && <QuizPanel questions={daily.data.questions} label="Daily practice" onGraded={() => void progress.reload()} />}</div>
        )}
        {view.kind === "playground" && <Playground workspace={workspace} />}
        {(view.kind === "projects" || view.kind === "interview") && <div className="muted">This section is coming in the next phase.</div>}
      </main>

      <SidePanel lang={lang} term={term} termId={termId} lesson={lesson.data} progress={progress.data} cards={cards} onOpen={openLesson} onClose={() => setTermId(null)} />
    </div>
  );
}

const LV: Record<Level, string> = { beginner: "Beginner", intermediate: "Intermediate", advanced: "Advanced", production: "Production" };
function Roadmap({ catalog, progress, cards, lang, onOpen }: { catalog: NonNullable<ReturnType<typeof useLoad<import("./types").Catalog>>["data"]>; progress: import("./types").Progress | null; cards: Record<string, LessonCard>; lang: Lang; onOpen: (id: string) => void }) {
  return (
    <div className="ac-block"><h1>Beginner to Production roadmap</h1>
      <p className="muted">Follow the levels in order. Topics marked <i>planned</i> are on the roadmap but do not have a full lesson yet.</p>
      {(Object.keys(LV) as Level[]).map((lv) => (
        <section key={lv} aria-label={LV[lv]}><h2>{LV[lv]}</h2>
          <ol className="ac-roadlist">{catalog.roadmap[lv].map((t) => (
            <li key={t.title}>{t.lesson && cards[t.lesson]
              ? <button className="link" onClick={() => onOpen(t.lesson!)}>{progress?.lessons[t.lesson]?.status === "done" ? "✓ " : ""}{t.title}<span className="muted small"> - {cards[t.lesson].title[lang]} · {cards[t.lesson].minutes} min</span></button>
              : <span className="muted">{t.title} <i>(planned)</i></span>}</li>
          ))}</ol>
        </section>
      ))}
    </div>
  );
}
