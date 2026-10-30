import type { ChartSpec } from "./types";

const W = 640, H = 300, L = 56, R = 16, T = 34, B = 62;
const nf = (v: number) => (Math.abs(v) >= 1000 ? v.toLocaleString(undefined, { maximumFractionDigits: 0 }) : String(+v.toPrecision(4)));

/** Dependency-free SVG chart (bar / line). Accessible: role="img" with a text summary, per-point <title> tooltips. */
export function Chart({ spec }: { spec: ChartSpec }) {
  const vals = spec.series.flatMap((s) => s.values).filter((v): v is number => v !== null);
  if (!spec.labels.length || !vals.length) return <div className="muted small">No data to chart.</div>;
  const lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
  const span = hi - lo || 1;
  const pw = W - L - R, ph = H - T - B;
  const y = (v: number) => T + ph - ((v - lo) / span) * ph;
  const n = spec.labels.length;
  const band = pw / n;
  const x = (i: number) => L + band * i + band / 2;
  const step = Math.max(1, Math.ceil(n / 12));
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => lo + span * f);
  const summary = `${spec.type} chart "${spec.title}": ${spec.series.map((s) => s.name).join(", ")} over ${n} ${spec.x_label || "points"}, from ${nf(Math.min(...vals))} to ${nf(Math.max(...vals))}`;
  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={summary} width="100%">
        <text x={W / 2} y={18} textAnchor="middle" className="ct">{spec.title}</text>
        {ticks.map((t) => (
          <g key={t}><line x1={L} x2={W - R} y1={y(t)} y2={y(t)} className="grid" /><text x={L - 6} y={y(t) + 4} textAnchor="end" className="ax">{nf(t)}</text></g>
        ))}
        {spec.labels.map((lab, i) => (i % step === 0 ? <text key={i} x={x(i)} y={H - B + 14} textAnchor="end" className="ax" transform={`rotate(-35 ${x(i)} ${H - B + 14})`}>{lab.length > 14 ? lab.slice(0, 13) + "…" : lab}</text> : null))}
        {spec.type === "bar" && spec.series.map((s, si) => {
          const bw = (band * 0.8) / spec.series.length;
          return s.values.map((v, i) => v === null ? null : (
            <rect key={`${si}-${i}`} x={L + band * i + band * 0.1 + bw * si} y={Math.min(y(v), y(0))} width={bw} height={Math.abs(y(v) - y(0))} className={`s${si % 6}`}><title>{`${spec.labels[i]}: ${nf(v)} (${s.name})`}</title></rect>
          ));
        })}
        {spec.type === "line" && spec.series.map((s, si) => {
          const pts = s.values.map((v, i) => (v === null ? null : [x(i), y(v)] as const));
          const path = pts.reduce((d, p, i) => (p ? d + `${i && pts[i - 1] ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)} ` : d), "");
          return (
            <g key={si}><path d={path} className={`ln s${si % 6}`} fill="none" />
              {pts.map((p, i) => p && <circle key={i} cx={p[0]} cy={p[1]} r={3} className={`s${si % 6}`}><title>{`${spec.labels[i]}: ${nf(s.values[i] as number)} (${s.name})`}</title></circle>)}</g>
          );
        })}
        <line x1={L} x2={L} y1={T} y2={T + ph} className="axis" /><line x1={L} x2={W - R} y1={y(0)} y2={y(0)} className="axis" />
        {spec.y_label && <text x={12} y={T + ph / 2} className="ax" transform={`rotate(-90 12 ${T + ph / 2})`} textAnchor="middle">{spec.y_label}</text>}
      </svg>
      {spec.series.length > 1 && <figcaption className="small">{spec.series.map((s, i) => <span key={s.name} className="legend"><i className={`s${i % 6}`} />{s.name}</span>)}</figcaption>}
      {spec.truncated && <figcaption className="small muted">Showing the first 60 points.</figcaption>}
    </figure>
  );
}
