import { useEffect, useState } from "react";
import { academy } from "../api";
import { errText } from "../ui";
import type { Lang, Term } from "./types";

// ----------------------------------------------------------------------------- reading preferences (text size, dyslexia-friendly font)
const PREFS_KEY = "mka_academy_prefs";
export interface Prefs { size: 0 | 1 | 2; dyslexia: boolean }
export const loadPrefs = (): Prefs => {
  try { const v = JSON.parse(localStorage.getItem(PREFS_KEY) ?? "{}"); return { size: [0, 1, 2].includes(v.size) ? v.size : 0, dyslexia: v.dyslexia === true }; } catch { return { size: 0, dyslexia: false }; }
};
export const savePrefs = (p: Prefs) => { try { localStorage.setItem(PREFS_KEY, JSON.stringify(p)); } catch { /* ignore */ } };
export const prefsClass = (p: Prefs) => `ac-size-${p.size}${p.dyslexia ? " ac-dyslexia" : ""}`;

export function PrefsBar({ prefs, onChange }: { prefs: Prefs; onChange: (p: Prefs) => void }) {
  return (
    <div className="seg ac-prefs" role="group" aria-label="Reading options">
      <button aria-label="Smaller text" disabled={prefs.size === 0} onClick={() => onChange({ ...prefs, size: (prefs.size - 1) as Prefs["size"] })}>A−</button>
      <button aria-label="Larger text" disabled={prefs.size === 2} onClick={() => onChange({ ...prefs, size: (prefs.size + 1) as Prefs["size"] })}>A+</button>
      <button aria-pressed={prefs.dyslexia} className={prefs.dyslexia ? "on" : ""} title="Wider letter and line spacing, easier to read for many people" onClick={() => onChange({ ...prefs, dyslexia: !prefs.dyslexia })}>Easy-read</button>
    </div>
  );
}

// ----------------------------------------------------------------------------- listen (the browser's own speech synthesis: nothing is sent anywhere)
const VOICE_LANG: Record<Lang, string> = { en: "en-IN", hi: "hi-IN", hinglish: "en-IN" };
export const canSpeak = () => typeof window !== "undefined" && "speechSynthesis" in window && typeof SpeechSynthesisUtterance !== "undefined";

export function ListenButton({ text, lang }: { text: string; lang: Lang }) {
  const [on, setOn] = useState(false);
  useEffect(() => () => { if (canSpeak()) window.speechSynthesis.cancel(); }, []);
  useEffect(() => { if (canSpeak()) window.speechSynthesis.cancel(); setOn(false); }, [text, lang]);
  if (!canSpeak()) return null;
  const toggle = () => {
    const synth = window.speechSynthesis;
    if (on) { synth.cancel(); setOn(false); return; }
    const u = new SpeechSynthesisUtterance(text.replace(/\{\{[a-z0-9-]+\|([^}]+)\}\}/g, "$1").replace(/[`*#]/g, ""));
    u.lang = VOICE_LANG[lang];
    u.onend = () => setOn(false);
    u.onerror = () => setOn(false);
    synth.cancel();
    synth.speak(u);
    setOn(true);
  };
  return <button className="small" aria-pressed={on} onClick={toggle} title="Reads this step aloud with your browser's voice">{on ? "■ Stop" : "🔊 Listen"}</button>;
}

// ----------------------------------------------------------------------------- 'was this helpful?'
const STEP_LABEL: [string, string][] = [["understand", "Understand it"], ["see", "The example"], ["code", "The code"], ["practice", "Practice"], ["check", "The quiz"]];

export function FeedbackBox({ lessonId }: { lessonId: string }) {
  const [state, setState] = useState<"ask" | "why" | "sent">("ask");
  const [step, setStep] = useState("");
  const [comment, setComment] = useState("");
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { setState("ask"); setStep(""); setComment(""); setErr(null); }, [lessonId]);
  async function send(helpful: boolean) {
    try { await academy.feedback({ lesson_id: lessonId, helpful, step: step || undefined, comment: comment.trim() || undefined }); setState("sent"); setErr(null); } catch (e) { setErr(errText(e)); }
  }
  if (state === "sent") return <p className="ac-feedback muted" role="status">Thank you. Your feedback helps improve this lesson.</p>;
  return (
    <div className="ac-feedback" role="group" aria-label="Lesson feedback">
      {state === "ask" ? (
        <div className="row"><b>Was this lesson helpful?</b>
          <button className="small" onClick={() => void send(true)}>👍 Yes</button>
          <button className="small" onClick={() => setState("why")}>👎 Not really</button></div>
      ) : (
        <div>
          <b>Sorry about that. What was confusing?</b>
          <div className="chips" role="radiogroup" aria-label="Confusing part">{STEP_LABEL.map(([id, label]) => <button key={id} role="radio" aria-checked={step === id} className={step === id ? "on" : ""} onClick={() => setStep(id)}>{label}</button>)}</div>
          <textarea aria-label="Tell us more (optional)" rows={2} maxLength={500} placeholder="Tell us more (optional)" value={comment} onChange={(e) => setComment(e.target.value)} />
          <div className="row"><button className="primary small" onClick={() => void send(false)}>Send feedback</button><button className="small" onClick={() => setState("ask")}>Back</button></div>
        </div>
      )}
      {err && <div className="error" role="alert">{err}</div>}
    </div>
  );
}

// ----------------------------------------------------------------------------- glossary page
export function Glossary({ glossary, lang, onTerm }: { glossary: Record<string, Term>; lang: Lang; onTerm: (id: string) => void }) {
  const [q, setQ] = useState("");
  const items = Object.entries(glossary).filter(([, t]) => !q.trim() || (t.term + " " + t[lang] + " " + t.en).toLowerCase().includes(q.trim().toLowerCase())).sort((a, b) => a[1].term.localeCompare(b[1].term));
  return (
    <div className="ac-block">
      <h1>Glossary</h1>
      <p className="muted">Every term used in the lessons, explained in simple words. Pick your language at the top.</p>
      <input type="search" aria-label="Search the glossary" placeholder="Search terms…" value={q} onChange={(e) => setQ(e.target.value)} />
      <p className="muted small">{items.length} term{items.length === 1 ? "" : "s"}</p>
      <dl className="ac-glossary">
        {items.map(([id, t]) => <div key={id}><dt><button className="term" onClick={() => onTerm(id)}>{t.term}</button></dt><dd>{t[lang]}</dd></div>)}
      </dl>
    </div>
  );
}
