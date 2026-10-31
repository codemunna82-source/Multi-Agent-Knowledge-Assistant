import type { GraphInfo } from "./types";

const W = 132, H = 34, GX = 56, GY = 18;

/** Dependency-free layered drawing of the compiled LangGraph. Dashed edges are conditional; highlighted nodes ran in the last trace. */
export function GraphDiagram({ info, visited = [] }: { info: GraphInfo; visited?: string[] }) {
  const ids = info.nodes.map((n) => n.id);
  const depth: Record<string, number> = { __start__: 0 };
  const queue = ["__start__"];
  while (queue.length) {   // longest path from the start, ignoring edges that go back (the verify → retry loop)
    const cur = queue.shift() as string;
    for (const e of info.edges) {
      if (e.source !== cur || e.target === "__start__") continue;
      const d = depth[cur] + 1;
      if (depth[e.target] === undefined || (d > depth[e.target] && d <= ids.length)) {
        const back = depth[e.target] !== undefined && depth[e.target] <= depth[cur];
        if (!back) { depth[e.target] = d; queue.push(e.target); }
      }
    }
  }
  const layers: string[][] = [];
  ids.forEach((id) => { const d = depth[id] ?? 1; (layers[d] ??= []).push(id); });
  const pos: Record<string, { x: number; y: number }> = {};
  const maxRows = Math.max(...layers.map((l) => (l ?? []).length));
  layers.forEach((l, i) => (l ?? []).forEach((id, j) => { pos[id] = { x: 10 + i * (W + GX), y: 10 + j * (H + GY) + ((maxRows - l.length) * (H + GY)) / 2 }; }));
  const width = 20 + layers.length * (W + GX), height = 20 + maxRows * (H + GY);
  return (
    <div className="scroll">
      <svg viewBox={`0 0 ${width} ${height}`} width={width} height={height} role="img" aria-label={`Agent graph with ${ids.length} nodes and ${info.edges.length} edges`} className="graph">
        <defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" className="arrow" /></marker></defs>
        {info.edges.map((e, i) => {
          const a = pos[e.source], b = pos[e.target];
          if (!a || !b) return null;
          const back = b.x <= a.x;
          const x1 = back ? a.x + W / 2 : a.x + W, y1 = a.y + H / 2, x2 = back ? b.x + W / 2 : b.x, y2 = b.y + H / 2;
          const d = back ? `M${x1},${a.y + H} C${x1},${a.y + H + 40} ${x2},${b.y + H + 40} ${x2},${b.y + H}` : `M${x1},${y1} C${x1 + GX / 2},${y1} ${x2 - GX / 2},${y2} ${x2},${y2}`;
          return <path key={i} d={d} className={`edge ${e.conditional ? "cond" : ""}`} markerEnd="url(#arr)" fill="none"><title>{`${e.source} → ${e.target}${e.conditional ? " (conditional)" : ""}`}</title></path>;
        })}
        {info.nodes.map((n) => {
          const p = pos[n.id];
          const ran = visited.includes(n.id);
          return (
            <g key={n.id} transform={`translate(${p.x},${p.y})`} className={`gnode ${ran ? "ran" : ""} ${n.id.startsWith("__") ? "end" : ""}`}>
              <rect width={W} height={H} rx={8} /><text x={W / 2} y={H / 2 + 4} textAnchor="middle">{n.id.replace(/__/g, "")}</text><title>{n.description || n.id}</title>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
