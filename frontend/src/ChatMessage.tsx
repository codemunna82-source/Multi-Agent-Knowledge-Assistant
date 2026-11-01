import { memo, useState } from "react";
import { api, saveBlob } from "./api";
import { Chart } from "./Chart";
import { StreamingMessage } from "./StreamingMessage";
import { StreamingStatus } from "./StreamingStatus";
import { ThinkingIndicator } from "./ThinkingIndicator";
import type { AskResponse, Citation } from "./types";
import { Badge } from "./ui";

export type TurnStatus = "pending" | "streaming" | "done" | "stopped" | "error";
export interface Turn {
  role: "user" | "assistant"; text: string; resp?: Partial<AskResponse>; status?: TurnStatus;
  stage?: string | null;          // label of the pipeline stage that is running right now (from the server)
  error?: string; corrected?: boolean;
}

export function CitationList({ citations, onOpen }: { citations: Citation[]; onOpen?: (c: Citation) => void }) {
  if (!citations.length) return null;
  return (
    <details className="cites" open={citations.length <= 3}>
      <summary>{citations.length} citation{citations.length > 1 ? "s" : ""}</summary>
      {citations.map((c, i) => (
        <div className="cite" key={i}>
          <b>[{i + 1}] {c.source} — {c.location}</b> {c.origin === "web" && <Badge kind="low">web</Badge>}{c.version ? <span className="muted small"> v{c.version}</span> : null}
          <div>{c.excerpt}</div>
          {onOpen && <button className="small" aria-label={`Open citation ${i + 1} in context`} onClick={() => onOpen(c)}>{c.origin === "web" ? "Details" : "View in context"}</button>}
        </div>
      ))}
    </details>
  );
}

function AutoPick({ resp }: { resp: Partial<AskResponse> }) {
  const a = (resp.details?.plan as { auto_strategy?: { chosen: string; why: string; candidates: { name: string; why: string; grade: string; hits: number; ms: number; score: number }[] } } | undefined)?.auto_strategy;
  if (!a) return null;
  return (
    <details className="autopick">
      <summary>✨ Auto picked <b>{a.chosen}</b> — {a.why}</summary>
      <table><thead><tr><th>Candidate</th><th>Grade</th><th>Passages</th><th>Score</th><th>ms</th></tr></thead>
        <tbody>{a.candidates.map((c) => <tr key={c.name} className={c.name === a.chosen ? "picked" : ""}><td>{c.name}{c.name === a.chosen ? " ✓" : ""}<div className="muted small">{c.why}</div></td><td>{c.grade}</td><td>{c.hits}</td><td>{c.score}</td><td>{c.ms}</td></tr>)}</tbody></table>
    </details>
  );
}

export function FeedbackBar({ workspace, question, resp }: { workspace: string; question: string; resp: Partial<AskResponse> }) {
  const [state, setState] = useState<"idle" | "form" | "sent">("idle");
  const [expected, setExpected] = useState("");
  const [comment, setComment] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  async function exportReport() {
    setExporting(true); setErr(null);
    try {
      const r = await api.createReport(workspace, { kind: "research", format: "pdf", params: { questions: [question], title: question.slice(0, 80) } });
      saveBlob(await api.downloadReport(workspace, r.id), "answer-report.pdf");
    } catch (e) { setErr(e instanceof Error ? e.message : "Export failed"); } finally { setExporting(false); }
  }
  const sources = (resp.citations ?? []).slice(0, 5).map((c) => ({ source: c.source, location: c.location }));
  async function send(rating: 1 | -1) {
    try {
      await api.sendFeedback(workspace, rating === 1 ? { rating, route: resp.route } : { rating, route: resp.route, question, answer: resp.answer, expected: expected || undefined, comment: comment || undefined, sources });
      setState("sent");
    } catch (e) { setErr(e instanceof Error ? e.message : "Could not send"); }
  }
  if (state === "sent") return <div className="muted small" role="status">Thanks — feedback saved.</div>;
  return (
    <div className="fb">
      <div className="row small">
        <button className="icon" aria-label="Good answer" title="Good answer" onClick={() => void send(1)}>👍</button>
        <button className="icon" aria-label="Export this answer as a report" title="Export as a PDF report with sources" disabled={exporting} onClick={() => void exportReport()}>{exporting ? "…" : "⬇"}</button>
        <button className="icon" aria-label="Bad answer" title="Bad answer" aria-expanded={state === "form"} onClick={() => setState(state === "form" ? "idle" : "form")}>👎</button>
      </div>
      {state === "form" && (
        <form className="col" onSubmit={(e) => { e.preventDefault(); void send(-1); }}>
          <label htmlFor="fbexp">What should the answer contain? (optional — lets this become a regression test)</label>
          <input id="fbexp" type="text" value={expected} onChange={(e) => setExpected(e.target.value)} placeholder="e.g. 25 days" />
          <label htmlFor="fbcom">Comment (optional)</label>
          <input id="fbcom" type="text" value={comment} onChange={(e) => setComment(e.target.value)} />
          <p className="muted small" style={{ margin: 0 }}>Sends this question and answer to your organisation's feedback list.</p>
          <div className="row"><button className="small primary">Send feedback</button></div>
        </form>
      )}
      {err && <div className="error small" role="alert">{err}</div>}
    </div>
  );
}

async function copyText(t: string): Promise<boolean> {
  try { await navigator.clipboard.writeText(t); return true; } catch { /* fall through to the legacy path */ }
  try {
    const ta = document.createElement("textarea");
    ta.value = t; ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    return ok;
  } catch { return false; }
}

export function CopyButton({ text }: { text: string }) {
  const [state, setState] = useState<"idle" | "ok" | "fail">("idle");
  async function go() { setState((await copyText(text)) ? "ok" : "fail"); setTimeout(() => setState("idle"), 1800); }
  return <button className="icon act" aria-label="Copy answer" title="Copy answer" onClick={() => void go()}>{state === "ok" ? "✓ Copied" : state === "fail" ? "Copy failed" : "⧉ Copy"}</button>;
}

interface Props {
  turn: Turn; question: string; workspace: string; isLast: boolean; busy: boolean;
  onOpenCitation: (c: Citation) => void; onFollowup: (q: string) => void; onRegenerate: () => void; onRetry: () => void;
}

/** One chat bubble. memo: while the last answer streams, every other message keeps its identity and is not re-rendered. */
export const ChatMessage = memo(function ChatMessage({ turn: t, question, workspace, isLast, busy, onOpenCitation, onFollowup, onRegenerate, onRetry }: Props) {
  if (t.role === "user") return <div className="msg user"><div className="bubble">{t.text}</div></div>;
  const waiting = t.status === "pending";
  const streaming = t.status === "streaming";
  const finished = !waiting && !streaming;
  return (
    <div className="msg assistant">
      <div className="avatar" aria-hidden="true">AI</div>
      <div className="bubble">
        {t.resp && finished && (
          <div className="row small badges">
            {t.resp.confidence && <Badge kind={t.resp.confidence}>confidence: {t.resp.confidence}</Badge>}
            {t.resp.route && <Badge>{t.resp.route}</Badge>}
            {t.resp.verified === false && <Badge kind="none">not verified</Badge>}
            {t.resp.details?.citation_check && t.resp.details.citation_check.accuracy !== null && <Badge kind={t.resp.details.citation_check.accuracy === 1 ? "high" : "low"}>citations checked: {Math.round(t.resp.details.citation_check.accuracy * 100)}%</Badge>}
            {t.resp.details?.private === true && <Badge>incognito</Badge>}
          </div>
        )}
        {waiting && <ThinkingIndicator stage={t.stage} />}
        {t.text && <div className="text"><StreamingMessage text={t.text} streaming={streaming} /></div>}
        {streaming && <StreamingStatus label={t.stage} />}
        {t.corrected && finished && <div className="muted small" role="note">The answer was adjusted after it was checked against your documents.</div>}
        {t.status === "stopped" && <div className="muted small" role="status">Generation stopped.</div>}
        {t.status === "error" && (
          <div className="error stream-error" role="alert">{t.error ?? "Something went wrong."}
            {isLast && <button className="small" onClick={onRetry} disabled={busy}>Try again</button>}</div>
        )}
        {finished && t.resp && <AutoPick resp={t.resp} />}
        {finished && t.resp?.details?.chart && <Chart spec={t.resp.details.chart} />}
        {finished && t.resp?.citations && <CitationList citations={t.resp.citations} onOpen={onOpenCitation} />}
        {finished && t.resp?.limitations && t.resp.limitations.length > 0 && <div className="muted small" style={{ marginTop: 6 }}>ℹ {t.resp.limitations.join(" • ")}</div>}
        {finished && t.resp?.followups && t.resp.followups.length > 0 && isLast && !busy && (
          <div className="chips" aria-label="Follow-up questions">{t.resp.followups.map((f) => <button key={f} onClick={() => onFollowup(f)}>{f}</button>)}</div>
        )}
        {finished && t.text && (
          <div className="row small msg-actions">
            <CopyButton text={t.text} />
            {isLast && <button className="icon act" aria-label="Regenerate answer" title="Regenerate answer" disabled={busy} onClick={onRegenerate}>↻ Regenerate</button>}
            {t.status === "done" && t.resp && !t.resp.details?.private && <FeedbackBar workspace={workspace} question={question} resp={t.resp} />}
          </div>
        )}
        {finished && t.resp?.usage && t.resp.latency_ms && (
          <div className="muted small" style={{ marginTop: 6 }}>
            {t.resp.latency_ms.toFixed(0)} ms · {(t.resp.usage.prompt_tokens ?? 0) + (t.resp.usage.completion_tokens ?? 0) + (t.resp.usage.embed_tokens ?? 0)} tokens · ${(t.resp.usage.cost_usd ?? 0).toFixed(5)}
          </div>
        )}
      </div>
    </div>
  );
});
