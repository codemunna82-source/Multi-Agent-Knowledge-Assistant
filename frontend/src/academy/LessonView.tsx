import { useEffect, useMemo, useRef } from "react";
import { academy } from "../api";
import { CodeLab, TaskLab } from "./CodeLab";
import { QuizPanel } from "./QuizPanel";
import { RichText } from "./RichText";
import type { Lang, Lesson, LessonCard, Progress } from "./types";
import { VizHost } from "./VizHost";

export const SECTIONS = [
  ["intro", "What is it?"], ["analogy", "Real-life analogy"], ["technical", "How it works"], ["why", "Why we need it"], ["example", "Practical example"], ["visual", "See it move"],
  ["code", "Code"], ["interview", "Interview answer"], ["mistakes", "Common mistakes"], ["practice", "Practice"], ["quiz", "Quiz"],
] as const;

const LEVEL_LABEL = { beginner: "Beginner", intermediate: "Intermediate", advanced: "Advanced", production: "Production" };
const T = {
  en: { definition: "Simple definition", analogy: "Real-world analogy", technical: "Technical explanation", why: "Why do we need it?", example: "Practical example", interview: "Interview answer", mistakes: "Common mistakes", visual: "See it move", code: "Code", practice: "Practice", quiz: "Quiz", objectives: "You will learn", related: "Related", prereq: "Before this", next: "Next", sources: "Sources" },
  hi: { definition: "आसान परिभाषा", analogy: "रोज़मर्रा की मिसाल", technical: "तकनीकी समझ", why: "इसकी ज़रूरत क्यों?", example: "व्यावहारिक उदाहरण", interview: "Interview जवाब", mistakes: "आम गलतियाँ", visual: "चलते हुए देखें", code: "Code", practice: "अभ्यास", quiz: "Quiz", objectives: "आप सीखेंगे", related: "जुड़े विषय", prereq: "इससे पहले", next: "अगला", sources: "स्रोत" },
  hinglish: { definition: "Simple definition", analogy: "Real-life analogy", technical: "Technical explanation", why: "Iski zaroorat kyun?", example: "Practical example", interview: "Interview answer", mistakes: "Common mistakes", visual: "Chalte hue dekho", code: "Code", practice: "Practice", quiz: "Quiz", objectives: "Aap seekhoge", related: "Related topics", prereq: "Isse pehle", next: "Agla", sources: "Sources" },
} as const;

interface Props {
  lesson: Lesson; lang: Lang; progress: Progress | null; cards: Record<string, LessonCard>; order: string[];
  onTerm: (id: string) => void; onOpen: (id: string) => void; onChanged: () => void;
}

export function LessonView({ lesson, lang, progress, cards, order, onTerm, onOpen, onChanged }: Props) {
  const t = T[lang];
  const mine = progress?.lessons[lesson.id];
  const done = mine?.status === "done";
  const refs = useRef<Record<string, HTMLElement | null>>({});
  const reached = useRef(mine?.step ?? 0);
  const idx = order.indexOf(lesson.id);

  // resume where the learner stopped, and remember how far they have read (only ever forward)
  useEffect(() => {
    reached.current = mine?.step ?? 0;
    const start = mine?.step ?? 0;
    if (start > 0) refs.current[SECTIONS[Math.min(start, SECTIONS.length - 1)][0]]?.scrollIntoView?.({ block: "start" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lesson.id]);
  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (!e.isIntersecting) continue;
        const i = SECTIONS.findIndex(([id]) => id === (e.target as HTMLElement).dataset.sec);
        if (i > reached.current) {
          reached.current = i;
          clearTimeout(timer);
          timer = setTimeout(() => { void academy.setProgress(lesson.id, { step: i }).then(onChanged).catch(() => undefined); }, 900);
        }
      }
    }, { threshold: 0.4 });
    Object.values(refs.current).forEach((el) => el && io.observe(el));
    return () => { io.disconnect(); clearTimeout(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lesson.id]);

  const block = (id: string, title: string, body: React.ReactNode) => (
    <section key={id} ref={(el) => { refs.current[id] = el; }} data-sec={id} id={`sec-${id}`} className="ac-sec"><h2>{title}</h2>{body}</section>
  );
  const prereq = useMemo(() => lesson.prereq.filter((p) => cards[p]), [lesson.prereq, cards]);
  const rich = (s: string) => <p className="ac-p"><RichText text={s} onTerm={onTerm} /></p>;

  return (
    <article className="ac-lesson" aria-label={lesson.title.en}>
      <header>
        <h1>{lesson.title[lang]}</h1>
        <div className="row small">
          <span className="badge">{LEVEL_LABEL[lesson.level]}</span><span className="muted">~{lesson.minutes} min</span>
          <span className="grow" />
          <button className="small" aria-pressed={mine?.bookmarked ?? false} onClick={() => void academy.setProgress(lesson.id, { bookmarked: !mine?.bookmarked }).then(onChanged)}>{mine?.bookmarked ? "★ Bookmarked" : "☆ Bookmark"}</button>
          <button className={`small ${done ? "" : "primary"}`} onClick={() => void academy.setProgress(lesson.id, { status: done ? "in_progress" : "done" }).then(onChanged)}>{done ? "✓ Completed (undo)" : "Mark complete"}</button>
        </div>
        <div className="ac-meta">
          <div><b>{t.objectives}</b><ul>{lesson.objectives.map((o) => <li key={o}>{o}</li>)}</ul></div>
          {prereq.length > 0 && <div><b>{t.prereq}</b><div className="chips">{prereq.map((p) => <button key={p} onClick={() => onOpen(p)}>{cards[p].title[lang]}</button>)}</div></div>}
        </div>
      </header>

      {block("intro", t.definition, <>{rich(lesson.text.definition[lang])}{lang !== "en" && <details className="ac-en"><summary>English</summary>{rich(lesson.text.definition.en)}</details>}</>)}
      {block("analogy", t.analogy, rich(lesson.text.analogy[lang]))}
      {block("technical", t.technical, rich(lesson.text.technical[lang]))}
      {block("why", t.why, rich(lesson.text.why[lang]))}
      {block("example", t.example, rich(lesson.text.example[lang]))}
      {block("visual", t.visual, (lesson.viz?.length ?? 0) > 0 ? <VizHost ids={lesson.viz!} lang={lang} /> : <p className="muted small">This topic has no animation; use the code and practice sections.</p>)}
      {block("code", t.code, <>{lesson.code.map((c, i) => <CodeLab key={`${lesson.id}-${i}`} example={c} lessonId={lesson.id} index={i} />)}</>)}
      {block("interview", t.interview, <>{rich(lesson.text.interview[lang])}<details><summary>More interview questions</summary>{lesson.interview_questions.map((q) => <div key={q.q} className="ac-iq"><b>{q.q}</b><p>{q.a}</p></div>)}</details></>)}
      {block("mistakes", t.mistakes, <ul>{lesson.text.mistakes[lang].map((m, i) => <li key={i}><RichText text={m} onTerm={onTerm} /></li>)}</ul>)}
      {block("practice", t.practice, <>
        <TaskLab key={`${lesson.id}-ex`} task={lesson.exercise} kind="exercise" lessonId={lesson.id} title="Practical exercise" onResult={onChanged} />
        {lesson.debug && <TaskLab key={`${lesson.id}-dbg`} task={lesson.debug} kind="debug" lessonId={lesson.id} title="Debugging challenge" onResult={onChanged} />}
        <div className="ac-assign"><b>Mini assignment</b><p>{lesson.assignment}</p></div></>)}
      {block("quiz", t.quiz, <QuizPanel questions={lesson.quiz} onGraded={onChanged} label={`Quiz: ${lesson.title.en}`} />)}

      <footer className="ac-foot">
        {lesson.sources.length > 0 && <div className="small"><b>{t.sources}:</b> {lesson.sources.map((s) => <a key={s.url} href={s.url} target="_blank" rel="noopener noreferrer">{s.title}</a>).reduce<React.ReactNode[]>((a, x, i) => (i ? [...a, " · ", x] : [x]), [])}</div>}
        <div className="row">
          <button disabled={idx <= 0} onClick={() => onOpen(order[idx - 1])}>← Previous</button>
          <span className="grow" />
          <button className="primary" disabled={idx < 0 || idx >= order.length - 1} onClick={() => onOpen(order[idx + 1])}>{t.next} →</button>
        </div>
      </footer>
    </article>
  );
}
