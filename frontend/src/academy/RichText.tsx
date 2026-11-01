import { Fragment } from "react";

const TERM = /\{\{([a-z0-9-]+)\|([^}]+)\}\}/g;

/** Text with {{term-id|label}} markers: every marker becomes a button that opens the term's definition (English, Hindi, Hinglish) in the side panel. */
export function RichText({ text, onTerm }: { text: string; onTerm: (id: string) => void }) {
  const out: React.ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(TERM)) {
    out.push(<Fragment key={`t${last}`}>{text.slice(last, m.index)}</Fragment>);
    out.push(<button key={`b${m.index}`} className="term" onClick={() => onTerm(m[1])} title="Show definition">{m[2]}</button>);
    last = (m.index ?? 0) + m[0].length;
  }
  out.push(<Fragment key="end">{text.slice(last)}</Fragment>);
  return <>{out}</>;
}

/** Plain text of a RichText string (labels only), e.g. for search or copying. */
export const plain = (text: string) => text.replace(TERM, "$2");
