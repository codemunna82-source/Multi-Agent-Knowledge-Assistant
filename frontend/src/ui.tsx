import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";

export const pct = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${(v * 100).toFixed(1)}%`);
export const num = (v: number | null | undefined, d = 3) => (v === null || v === undefined ? "—" : v.toFixed(d));

export function Bar({ value }: { value: number | null | undefined }) {
  if (value === null || value === undefined) return <span>—</span>;
  return (
    <span>
      <span className="bar" role="img" aria-label={pct(value)}><i style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }} /></span>
      {pct(value)}
    </span>
  );
}

export function Badge({ children, kind }: { children: ReactNode; kind?: string }) {
  return <span className={`badge ${kind ?? ""}`}>{children}</span>;
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal" role="dialog" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <div className="row"><h2 style={{ margin: 0 }}>{title}</h2><span className="grow" /><button className="small" onClick={onClose}>Close</button></div>
        {children}
      </div>
    </div>
  );
}

/** Runs an async loader on mount / when deps change, exposing loading + error + manual reload. */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const reload = useCallback(async () => {
    setLoading(true);
    try { setData(await fnRef.current()); setError(null); } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setLoading(false); }
  }, []);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { void reload(); }, deps);
  return { data, error, loading, reload };
}

export function Pager({ total, limit, offset, onChange }: { total: number; limit: number; offset: number; onChange: (offset: number) => void }) {
  if (total <= limit) return null;
  const page = Math.floor(offset / limit) + 1, pages = Math.ceil(total / limit);
  return (
    <nav className="row small" aria-label="Pagination">
      <button className="small" disabled={offset <= 0} onClick={() => onChange(Math.max(0, offset - limit))}>‹ Prev</button>
      <span>Page {page} of {pages} · {total} total</span>
      <button className="small" disabled={offset + limit >= total} onClick={() => onChange(offset + limit)}>Next ›</button>
    </nav>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange, label }: { tabs: [T, string][]; value: T; onChange: (t: T) => void; label: string }) {
  return (
    <div className="subtabs" role="tablist" aria-label={label}>
      {tabs.map(([k, name]) => <button key={k} role="tab" aria-selected={value === k} className={value === k ? "on" : ""} onClick={() => onChange(k)}>{name}</button>)}
    </div>
  );
}

export const errText = (e: unknown, fallback = "Failed") => (e instanceof Error ? e.message : fallback);

/** Table of arbitrary rows (analysis results). Cells are rendered as text only. */
export function DataTable({ columns, rows }: { columns: string[]; rows: unknown[][] }) {
  return (
    <div className="scroll"><table><thead><tr>{columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
      <tbody>{rows.map((r, i) => <tr key={i}>{r.map((v, j) => <td key={j}>{v === null || v === undefined ? "" : typeof v === "number" ? v.toLocaleString(undefined, { maximumFractionDigits: 4 }) : String(v)}</td>)}</tr>)}</tbody></table></div>
  );
}
