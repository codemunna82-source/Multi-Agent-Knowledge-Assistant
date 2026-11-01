import { useEffect, useState } from "react";
import type { Lang, Lesson, LessonCard, Progress, Term } from "./types";

const loadNote = (id: string) => { try { return localStorage.getItem(`mka_ac_note_${id}`) ?? ""; } catch { return ""; } };

interface Props { lang: Lang; term: Term | null; termId: string | null; lesson: Lesson | null; progress: Progress | null; cards: Record<string, LessonCard>; onOpen: (id: string) => void; onClose: () => void }

/** Right panel: the definition of the term you clicked (all three languages on demand), this lesson's progress, private notes and related topics. */
export function SidePanel({ lang, term, termId, lesson, progress, cards, onOpen, onClose }: Props) {
  const [note, setNote] = useState("");
  const [showAll, setShowAll] = useState(false);
  useEffect(() => { setNote(lesson ? loadNote(lesson.id) : ""); }, [lesson?.id]);  // eslint-disable-line react-hooks/exhaustive-deps
  const save = (v: string) => { setNote(v); if (lesson) { try { localStorage.setItem(`mka_ac_note_${lesson.id}`, v); } catch { /* storage may be unavailable */ } } };
  const q = lesson ? progress?.quiz[lesson.id] : undefined;
  const ex = lesson ? progress?.exercises[`${lesson.id}:exercise`] : undefined;
  const related = lesson ? [...lesson.prereq, ...lesson.next].filter((r) => cards[r]) : [];
  return (
    <aside className="ac-side" aria-label="Definitions, notes and progress">
      {term && termId && (
        <section className="ac-term" aria-label={`Definition of ${term.term}`}>
          <div className="row"><h3 style={{ margin: 0 }}>{term.term}</h3><span className="grow" /><button className="small" aria-label="Close definition" onClick={onClose}>×</button></div>
          <p>{term[lang]}</p>
          <button className="small" onClick={() => setShowAll(!showAll)} aria-expanded={showAll}>{showAll ? "Hide other languages" : "Show all languages"}</button>
          {showAll && <div className="small"><p><b>English:</b> {term.en}</p><p><b>हिंदी:</b> {term.hi}</p><p><b>Hinglish:</b> {term.hinglish}</p></div>}
        </section>
      )}
      {lesson && (
        <section aria-label="This lesson">
          <h3>This lesson</h3>
          <ul className="ac-checks">
            <li>{progress?.lessons[lesson.id]?.status === "done" ? "✓" : "○"} Lesson {progress?.lessons[lesson.id]?.status === "done" ? "completed" : "in progress"}</li>
            <li>{q ? (q.percent >= 70 ? "✓" : "•") : "○"} Quiz {q ? `${q.correct}/${q.total} (${q.percent}%)` : "not taken"}</li>
            <li>{ex?.passed ? "✓" : "○"} Exercise {ex ? (ex.passed ? "passed" : `${ex.attempts} attempt(s)`) : "not tried"}</li>
          </ul>
          <label htmlFor="ac-note">My notes (saved in this browser only)</label>
          <textarea id="ac-note" rows={4} value={note} onChange={(e) => save(e.target.value)} placeholder="Write what you want to remember…" />
        </section>
      )}
      {related.length > 0 && (
        <section aria-label="Related topics"><h3>Related topics</h3><div className="col">{related.map((r) => <button key={r} className="small" onClick={() => onOpen(r)}>{cards[r].title[lang]}</button>)}</div></section>
      )}
      {!term && !lesson && <p className="muted small">Click any underlined term in a lesson to see its definition here.</p>}
    </aside>
  );
}
