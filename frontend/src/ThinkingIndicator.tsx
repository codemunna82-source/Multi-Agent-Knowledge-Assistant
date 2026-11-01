import { useEffect, useState } from "react";

/** Generic waiting messages: they make no claim about what the system is doing, so they are safe whenever no real stage is known. */
const GENERIC = ["Thinking…", "Understanding your question…", "Analyzing your request…", "Preparing the response…"];
const LONG_WAIT = "Almost there…";          // only after a long wait, so it is never shown for a quick answer
const EVERY_MS = 2800;
const LONG_AFTER_MS = 12000;

/** Shown from the moment a question is sent until the first token arrives. If the server reports a real stage ("Searching documents") that
 *  text is shown; otherwise one generic message at a time rotates with a fade/slide transition. No percentages, no fake progress. */
export function ThinkingIndicator({ stage }: { stage?: string | null }) {
  const [i, setI] = useState(0);
  const [long, setLong] = useState(false);
  useEffect(() => {
    if (stage) return;
    const rot = setInterval(() => setI((v) => (v + 1) % GENERIC.length), EVERY_MS);
    const lw = setTimeout(() => setLong(true), LONG_AFTER_MS);
    return () => { clearInterval(rot); clearTimeout(lw); };
  }, [stage]);
  const label = stage ? `${stage}…` : long ? LONG_WAIT : GENERIC[i];
  return (
    <div className="thinking-ind" role="status" aria-live="polite" aria-label="Assistant is working">
      <span className="dots" aria-hidden="true"><i /><i /><i /></span>
      <span key={label} className="think-text">{label}</span>
    </div>
  );
}
