import { useEffect, useMemo, useRef, useState } from "react";
import { academy } from "../api";
import { CodeLab, TaskLab } from "./CodeLab";
import { QuizPanel } from "./QuizPanel";
import { plain, RichText } from "./RichText";
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

/** Simple mode: the 11 sections regrouped into 5 small steps. `map` is the section index stored as progress, so Simple and Full view share one resume point. */
export const SIMPLE_STEPS = [
  { id: "understand", secs: ["intro", "analogy"], map: 0 }, { id: "see", secs: ["example", "visual"], map: 4 }, { id: "code", secs: ["code"], map: 6 },
  { id: "practice", secs: ["practice"], map: 9 }, { id: "check", secs: ["quiz"], map: 10 },
] as const;
const SIMPLE_UI = {
  en: { steps: { understand: "Understand it", see: "See an example", code: "Try the code", practice: "Practice", check: "Check yourself" }, oneLine: "In one line", back: "← Back", next: "Next:", finish: "You finished the steps", full: "Show full lesson", simple: "Simple steps", deeper: "Go deeper: how it works and why", deeper2: "Go deeper: interview answer and common mistakes", step: "Step", of: "of", nextLesson: "Next lesson →" },
  hi: { steps: { understand: "समझें", see: "उदाहरण देखें", code: "Code आज़माएँ", practice: "अभ्यास", check: "खुद जाँचें" }, oneLine: "एक लाइन में", back: "← पीछे", next: "अगला:", finish: "आपने सारे steps पूरे किए", full: "पूरा lesson दिखाएँ", simple: "आसान steps", deeper: "और गहराई में: यह कैसे चलता है और क्यों", deeper2: "और गहराई में: interview जवाब और आम गलतियाँ", step: "Step", of: "/", nextLesson: "अगला lesson →" },
  hinglish: { steps: { understand: "Samjho", see: "Example dekho", code: "Code try karo", practice: "Practice", check: "Khud jaancho" }, oneLine: "Ek line mein", back: "← Peeche", next: "Agla:", finish: "Aapne saare steps poore kiye", full: "Poora lesson dikhao", simple: "Aasan steps", deeper: "Aur gehraai mein: yeh kaise chalta hai aur kyun", deeper2: "Aur gehraai mein: interview jawab aur aam galtiyan", step: "Step", of: "/", nextLesson: "Agla lesson →" },
} as const;

/** First sentence of the definition, without glossary markers: the 'in one line' summary. */
export function oneLine(definition: string): string {
  const t = plain(definition).replace(/`/g, "").trim();
  const m = /^(.+?[.!?।])(\s|$)/.exec(t);
  const first = (m ? m[1] : t).trim();
  return first.length > 220 ? first.slice(0, 217).replace(/\s+\S*$/, "") + "…" : first;
}

interface Props {
  lesson: Lesson; lang: Lang; progress: Progress | null; cards: Record<string, LessonCard>; order: string[];
  onTerm: (id: string) => void; onOpen: (id: string) => void; onChanged: () => void;
  simple?: boolean; onSimple?: (simple: boolean) => void;
}

export function LessonView({ lesson, lang, progress, cards, order, onTerm, onOpen, onChanged, simple = false, onSimple }: Props) {
  const t = T[lang];
  const u = SIMPLE_UI[lang];
  const mine = progress?.lessons[lesson.id];
  const done = mine?.status === "done";
  const refs = useRef<Record<string, HTMLElement | null>>({});
  const reached = useRef(mine?.step ?? 0);
  const topRef = useRef<HTMLDivElement | null>(null);
  const idx = order.indexOf(lesson.id);
  const startStep = useMemo(() => SIMPLE_STEPS.reduce((acc, st, n) => ((mine?.step ?? 0) >= st.map ? n : acc), 0), [mine?.step]);
  const [stepNo, setStepNo] = useState(0);
  useEffect(() => { setStepNo(simple ? startStep : 0); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [lesson.id, simple]);
  const goStep = (n: number) => {
    const i = Math.max(0, Math.min(SIMPLE_STEPS.length - 1, n));
    setStepNo(i);
    if (SIMPLE_STEPS[i].map > reached.current) { reached.current = SIMPLE_STEPS[i].map; void academy.setProgress(lesson.id, { step: SIMPLE_STEPS[i].map }).then(onChanged).catch(() => undefined); }
    topRef.current?.scrollIntoView?.({ block: "start" });
  };

  // resume where the learner stopped, and remember how far they have read (only ever forward)
  useEffect(() => {
    reached.current = mine?.step ?? 0;
    const start = mine?.step ?? 0;
    if (start > 0) refs.current[SECTIONS[Math.min(start, SECTIONS.length - 1)][0]]?.scrollIntoView?.({ block: "start" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lesson.id]);
  useEffect(() => {
    if (simple || typeof IntersectionObserver === "undefined") return;
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
  }, [lesson.id, simple]);

  const block = (id: string, title: string, body: React.ReactNode) => (
    <section key={id} ref={(el) => { refs.current[id] = el; }} data-sec={id} id={`sec-${id}`} className="ac-sec"><h2>{title}</h2>{body}</section>
  );
  const prereq = useMemo(() => lesson.prereq.filter((p) => cards[p]), [lesson.prereq, cards]);
  const rich = (s: string) => <p className="ac-p"><RichText text={s} onTerm={onTerm} /></p>;
  const body: Record<string, { title: string; node: React.ReactNode }> = {
    intro: { title: t.definition, node: <>{rich(lesson.text.definition[lang])}{lang !== "en" && <details className="ac-en"><summary>English</summary>{rich(lesson.text.definition.en)}</details>}</> },
    analogy: { title: t.analogy, node: rich(lesson.text.analogy[lang]) },
    technical: { title: t.technical, node: rich(lesson.text.technical[lang]) },
    why: { title: t.why, node: rich(lesson.text.why[lang]) },
    example: { title: t.example, node: rich(lesson.text.example[lang]) },
    visual: { title: t.visual, node: (lesson.viz?.length ?? 0) > 0 ? <VizHost ids={lesson.viz!} lang={lang} /> : <p className="muted small">This topic has no animation; use the code and practice sections.</p> },
    code: { title: t.code, node: <>{lesson.code.map((c, i) => <CodeLab key={`${lesson.id}-${i}`} example={c} lessonId={lesson.id} index={i} />)}</> },
    interview: { title: t.interview, node: <>{rich(lesson.text.interview[lang])}<details><summary>More interview questions</summary>{lesson.interview_questions.map((q) => <div key={q.q} className="ac-iq"><b>{q.q}</b><p>{q.a}</p></div>)}</details></> },
    mistakes: { title: t.mistakes, node: <ul>{lesson.text.mistakes[lang].map((m, i) => <li key={i}><RichText text={m} onTerm={onTerm} /></li>)}</ul> },
    practice: { title: t.practice, node: <>
      <TaskLab key={`${lesson.id}-ex`} task={lesson.exercise} kind="exercise" lessonId={lesson.id} title="Practical exercise" onResult={onChanged} />
      {lesson.debug && <TaskLab key={`${lesson.id}-dbg`} task={lesson.debug} kind="debug" lessonId={lesson.id} title="Debugging challenge" onResult={onChanged} />}
      <div className="ac-assign"><b>Mini assignment</b><p>{lesson.assignment}</p></div></> },
    quiz: { title: t.quiz, node: <QuizPanel questions={lesson.quiz} onGraded={onChanged} label={`Quiz: ${lesson.title.en}`} /> },
  };
  const sectionOf = (id: string) => <section key={id} data-sec={id} id={`sec-${id}`} className="ac-sec"><h2>{body[id].title}</h2>{body[id].node}</section>;
  const step = SIMPLE_STEPS[stepNo];
  const stepName = (i: number) => u.steps[SIMPLE_STEPS[i].id];

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

      <div ref={topRef} />
      {simple && <p className="ac-oneline" aria-label={u.oneLine}><b>{u.oneLine}:</b> {oneLine(lesson.text.definition[lang])}</p>}
      {onSimple && <div className="ac-modebar"><div className="seg" role="group" aria-label="Lesson view">
        <button aria-pressed={simple} className={simple ? "on" : ""} onClick={() => onSimple(true)}>{u.simple}</button>
        <button aria-pressed={!simple} className={!simple ? "on" : ""} onClick={() => onSimple(false)}>{u.full}</button></div></div>}

      {!simple && <>
        {block("intro", body.intro.title, body.intro.node)}{block("analogy", body.analogy.title, body.analogy.node)}{block("technical", body.technical.title, body.technical.node)}{block("why", body.why.title, body.why.node)}
        {block("example", body.example.title, body.example.node)}{block("visual", body.visual.title, body.visual.node)}{block("code", body.code.title, body.code.node)}{block("interview", body.interview.title, body.interview.node)}
        {block("mistakes", body.mistakes.title, body.mistakes.node)}{block("practice", body.practice.title, body.practice.node)}{block("quiz", body.quiz.title, body.quiz.node)}
      </>}

      {simple && (
        <div className="ac-steps-wrap">
          <ol className="ac-stepper" aria-label="Lesson steps">
            {SIMPLE_STEPS.map((st, i) => (
              <li key={st.id}><button className={i === stepNo ? "on" : i < stepNo ? "done" : ""} aria-current={i === stepNo ? "step" : undefined} onClick={() => goStep(i)}><span className="num">{i < stepNo ? "✓" : i + 1}</span><span className="lbl">{stepName(i)}</span></button></li>
            ))}
          </ol>
          <p className="muted small" aria-live="polite">{u.step} {stepNo + 1} {u.of} {SIMPLE_STEPS.length}</p>
          <div className="ac-step" key={`${lesson.id}-${step.id}`}>
            {step.secs.map((id) => sectionOf(id))}
            {step.id === "understand" && <details className="ac-deeper"><summary>{u.deeper}</summary>{sectionOf("technical")}{sectionOf("why")}</details>}
            {step.id === "check" && <details className="ac-deeper"><summary>{u.deeper2}</summary>{sectionOf("interview")}{sectionOf("mistakes")}</details>}
          </div>
          <div className="row ac-stepnav">
            <button disabled={stepNo === 0} onClick={() => goStep(stepNo - 1)}>{u.back}</button>
            <span className="grow" />
            {stepNo < SIMPLE_STEPS.length - 1
              ? <button className="primary" onClick={() => goStep(stepNo + 1)}>{u.next} {stepName(stepNo + 1)} →</button>
              : <><span className="muted small">{u.finish}</span><button className={done ? "" : "primary"} onClick={() => void academy.setProgress(lesson.id, { status: "done" }).then(onChanged)}>{done ? "✓ Completed" : "Mark complete"}</button></>}
          </div>
        </div>
      )}

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
