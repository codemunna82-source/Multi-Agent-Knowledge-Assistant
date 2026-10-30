import { useEffect, useState } from "react";
import { api, saveBlob } from "./api";
import { Chart } from "./Chart";
import type { Anomalies, AskResponse, ChartSpec, Profile, SourceInfo, SqlResult, SqlTable, Trend } from "./types";
import { Badge, DataTable, Tabs, errText, useLoad } from "./ui";

type Tab = "ask" | "profile" | "anomalies" | "trend" | "sql";

export function Analyst({ workspace }: { workspace: string }) {
  const sources = useLoad(() => api.sources(workspace, { limit: 200 }), [workspace]);
  const sheets = (sources.data?.items ?? []).filter((s) => s.tabular);
  const [sid, setSid] = useState("");
  const [sheet, setSheet] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("ask");
  const src: SourceInfo | undefined = sheets.find((s) => s.id === sid);
  useEffect(() => { if (!sid && sheets[0]) setSid(sheets[0].id); }, [sheets, sid]);
  useEffect(() => { setSheet(src?.tables?.[0]?.sheet ?? null); }, [src]);

  if (sources.loading) return <div className="muted">Loading…</div>;
  if (!sheets.length) return <div className="card"><h2 style={{ marginTop: 0 }}>Data analyst</h2><p>Upload a CSV or Excel file to analyse it: profile, outliers, trends, charts and read-only SQL.</p></div>;
  const table = src?.tables?.find((t) => t.sheet === sheet) ?? src?.tables?.[0];
  return (
    <div>
      <div className="card">
        <div className="row"><h2 style={{ margin: 0 }}>Data analyst</h2><span className="grow" />
          <select aria-label="Spreadsheet" value={sid} onChange={(e) => setSid(e.target.value)}>{sheets.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>
          {(src?.tables?.length ?? 0) > 1 && <select aria-label="Sheet" value={sheet ?? ""} onChange={(e) => setSheet(e.target.value)}>{src?.tables?.map((t) => <option key={t.sheet ?? ""} value={t.sheet ?? ""}>{t.sheet}</option>)}</select>}
        </div>
        <Tabs label="Analysis" value={tab} onChange={setTab} tabs={[["ask", "Ask"], ["profile", "Profile"], ["anomalies", "Outliers"], ["trend", "Trends"], ["sql", "SQL"]]} />
      </div>
      {src && tab === "ask" && <AskPanel workspace={workspace} sid={src.id} />}
      {src && tab === "profile" && <ProfilePanel workspace={workspace} sid={src.id} sheet={sheet} />}
      {src && tab === "anomalies" && <AnomalyPanel workspace={workspace} sid={src.id} sheet={sheet} columns={table?.columns ?? []} />}
      {src && tab === "trend" && <TrendPanel workspace={workspace} sid={src.id} sheet={sheet} columns={table?.columns ?? []} />}
      {src && tab === "sql" && <SqlPanel workspace={workspace} />}
    </div>
  );
}

function ChartBox({ workspace, spec }: { workspace: string; spec: ChartSpec }) {
  return (<div><Chart spec={spec} /><button className="small" onClick={async () => saveBlob(await api.chartPng(workspace, spec), "chart.png")}>Download PNG</button></div>);
}

function AskPanel({ workspace, sid }: { workspace: string; sid: string }) {
  const [q, setQ] = useState("");
  const [res, setRes] = useState<AskResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const examples = ["What is the total of each numeric column?", "Show the top 5 rows by the first numeric column", "Are there duplicate rows?", "Are there any outliers?", "Show the monthly trend"];
  async function run(question: string) {
    setBusy(true); setErr(null);
    try { setRes(await api.analyticsAsk(workspace, question, [sid])); } catch (e) { setErr(errText(e)); setRes(null); } finally { setBusy(false); }
  }
  return (
    <div className="card">
      <form className="row" onSubmit={(e) => { e.preventDefault(); if (q.trim()) void run(q); }}>
        <input type="text" aria-label="Question about the data" placeholder="Ask a question about this table…" value={q} onChange={(e) => setQ(e.target.value)} style={{ flex: 1 }} />
        <button className="primary" disabled={busy || !q.trim()}>Ask</button>
      </form>
      <div className="chips">{examples.map((x) => <button key={x} onClick={() => { setQ(x); void run(x); }}>{x}</button>)}</div>
      {err && <div className="error" role="alert">{err}</div>}
      {res && (
        <div aria-label="Answer"><h3>Answer <Badge kind={res.confidence}>{res.confidence}</Badge></h3>
          <pre className="answer">{res.answer}</pre>
          {res.details.chart && <ChartBox workspace={workspace} spec={res.details.chart} />}
          {res.citations.length > 0 && <details><summary>{res.citations.length} source row(s)</summary>{res.citations.map((c, i) => <div className="cite" key={i}><b>{c.location}</b> {c.excerpt}</div>)}</details>}
          {res.limitations.length > 0 && <p className="muted small">ℹ {res.limitations.join(" • ")}</p>}
        </div>
      )}
    </div>
  );
}

function ProfilePanel({ workspace, sid, sheet }: { workspace: string; sid: string; sheet: string | null }) {
  const p = useLoad<Profile>(() => api.profile(workspace, sid, sheet), [workspace, sid, sheet]);
  if (p.error) return <div className="error" role="alert">{p.error}</div>;
  if (!p.data) return <div className="muted">Loading…</div>;
  const d = p.data;
  return (
    <div className="card">
      <div className="tiles"><div className="tile"><b>{d.rows.toLocaleString()}</b><span>rows</span></div><div className="tile"><b>{d.columns.length}</b><span>columns</span></div><div className="tile"><b>{d.duplicate_rows}</b><span>duplicate rows</span></div>
        <div className="tile"><b>{d.columns.reduce((n, c) => n + c.missing, 0)}</b><span>missing cells</span></div></div>
      <DataTable columns={["Column", "Type", "Missing", "Distinct", "Min", "Max", "Mean", "Top values"]}
        rows={d.columns.map((c) => [c.name, c.type, `${c.missing} (${c.missing_pct}%)`, c.unique, c.min ?? "", c.max ?? "", c.mean ?? "", (c.top_values ?? []).slice(0, 3).map((v) => `${v.value} ×${v.count}`).join(", ")])} />
      {d.duplicate_row_numbers.length > 0 && <p className="small">Duplicate rows (spreadsheet row numbers): {d.duplicate_row_numbers.join(", ")}</p>}
    </div>
  );
}

function AnomalyPanel({ workspace, sid, sheet, columns }: { workspace: string; sid: string; sheet: string | null; columns: string[] }) {
  const [col, setCol] = useState("");
  const [method, setMethod] = useState("iqr");
  const [res, setRes] = useState<Anomalies | null>(null);
  const [err, setErr] = useState<string | null>(null);
  async function run() { setErr(null); try { setRes(await api.anomalies(workspace, sid, col, method, sheet)); } catch (e) { setErr(errText(e)); setRes(null); } }
  return (
    <div className="card">
      <div className="row">
        <select aria-label="Column" value={col} onChange={(e) => setCol(e.target.value)}><option value="">Column…</option>{columns.map((c) => <option key={c}>{c}</option>)}</select>
        <select aria-label="Method" value={method} onChange={(e) => setMethod(e.target.value)}><option value="iqr">IQR rule</option><option value="zscore">z-score</option></select>
        <button className="primary" disabled={!col} onClick={() => void run()}>Find outliers</button>
      </div>
      {err && <div className="error" role="alert">{err}</div>}
      {res && (
        <div aria-label="Outliers">
          <p>{res.note ?? `${res.count} outlier(s)${res.bounds ? `; normal range ${res.bounds.low.toLocaleString()} to ${res.bounds.high.toLocaleString()}` : ""}.`}</p>
          {res.rows.length > 0 && <DataTable columns={["Row", "Value", "Score", "Record"]} rows={res.rows.map((r) => [r.row, r.value, r.score, Object.entries(r.values ?? {}).map(([k, v]) => `${k}: ${v}`).join("; ")])} />}
          <p className="muted small">Statistical flags only — check the rows before treating them as errors.</p>
        </div>
      )}
    </div>
  );
}

function TrendPanel({ workspace, sid, sheet, columns }: { workspace: string; sid: string; sheet: string | null; columns: string[] }) {
  const [dateCol, setDateCol] = useState("");
  const [valCol, setValCol] = useState("");
  const [freq, setFreq] = useState("M");
  const [agg, setAgg] = useState("sum");
  const [res, setRes] = useState<Trend | null>(null);
  const [err, setErr] = useState<string | null>(null);
  async function run() { setErr(null); try { setRes(await api.trend(workspace, sid, { date_column: dateCol, value_column: valCol || undefined, freq, agg, sheet })); } catch (e) { setErr(errText(e)); setRes(null); } }
  return (
    <div className="card">
      <div className="row">
        <select aria-label="Date column" value={dateCol} onChange={(e) => setDateCol(e.target.value)}><option value="">Date column…</option>{columns.map((c) => <option key={c}>{c}</option>)}</select>
        <select aria-label="Value column" value={valCol} onChange={(e) => setValCol(e.target.value)}><option value="">Value column…</option>{columns.map((c) => <option key={c}>{c}</option>)}</select>
        <select aria-label="Period" value={freq} onChange={(e) => setFreq(e.target.value)}><option value="M">Month</option><option value="Q">Quarter</option><option value="Y">Year</option></select>
        <select aria-label="Aggregate" value={agg} onChange={(e) => setAgg(e.target.value)}>{["sum", "mean", "count", "min", "max", "median"].map((a) => <option key={a}>{a}</option>)}</select>
        <button className="primary" disabled={!dateCol} onClick={() => void run()}>Show trend</button>
      </div>
      {err && <div className="error" role="alert">{err}</div>}
      {res && (
        <div aria-label="Trend">
          <p>Direction: <b>{res.direction}</b> · peak {res.best.period} ({res.best.value.toLocaleString()}) · low {res.worst.period} ({res.worst.value.toLocaleString()}){res.total_change_pct !== null && <> · overall {res.total_change_pct > 0 ? "+" : ""}{res.total_change_pct}%</>}</p>
          <ChartBox workspace={workspace} spec={res.chart} />
          {res.yoy.length > 0 && <><h3>Compared with the same period a year earlier</h3><DataTable columns={["Period", "Versus", "Change", "Change %"]} rows={res.yoy.slice(-12).map((y) => [y.period, y.vs, y.change, y.change_pct ?? ""])} /></>}
        </div>
      )}
    </div>
  );
}

function SqlPanel({ workspace }: { workspace: string }) {
  const schema = useLoad<{ tables: SqlTable[] }>(() => api.analyticsTables(workspace), [workspace]);
  const [sql, setSql] = useState("SELECT * FROM ");
  const [res, setRes] = useState<SqlResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  async function run() { setErr(null); try { setRes(await api.sql(workspace, sql)); } catch (e) { setErr(errText(e)); setRes(null); } }
  return (
    <div className="card">
      <p className="muted small">One read-only SELECT (or WITH … SELECT). Executed in a sandbox with a 3 second limit and a 200 row preview; nothing can be modified.</p>
      <textarea rows={4} aria-label="SQL query" value={sql} onChange={(e) => setSql(e.target.value)} spellCheck={false} style={{ fontFamily: "ui-monospace,monospace" }} />
      <div className="row"><button className="primary" onClick={() => void run()}>Run query</button></div>
      {err && <div className="error" role="alert">{err}</div>}
      {res && <div aria-label="Query result"><p className="small">{res.row_count} row(s){res.truncated ? " (truncated)" : ""}</p><DataTable columns={res.columns} rows={res.rows} /></div>}
      <details><summary>Tables and columns</summary>
        {(schema.data?.tables ?? []).map((t) => <div key={t.table}><b>{t.table}</b> <span className="muted small">({t.source}{t.sheet ? ` / ${t.sheet}` : ""}, {t.rows} rows)</span>
          <div className="small">{t.columns.map((c) => <code key={c.name} style={{ marginRight: 6 }} title={c.original}>{c.name}</code>)}</div></div>)}
      </details>
    </div>
  );
}
