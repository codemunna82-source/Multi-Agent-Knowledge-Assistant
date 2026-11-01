export function VizHost({ ids }: { ids: string[] }) { return ids.length ? <div className="muted small">Visualisations: {ids.join(", ")}</div> : null; }
