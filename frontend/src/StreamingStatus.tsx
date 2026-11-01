/** One short operational line under a streaming answer (e.g. "Checking the answer against the sources…"). Never shows reasoning. */
export function StreamingStatus({ label }: { label?: string | null }) {
  if (!label) return null;
  return <div className="stream-status" role="status" aria-live="polite"><span className="pulse" aria-hidden="true" />{label}…</div>;
}
