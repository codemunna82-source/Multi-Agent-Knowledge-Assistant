"""Chart specifications (JSON, rendered by the React UI) and server-side PNG rendering for reports (matplotlib, Agg backend)."""
from __future__ import annotations

import io
from typing import Optional

MAX_POINTS = 60


def spec(kind: str, title: str, labels: list, series: list[dict], x_label: str = "", y_label: str = "") -> dict:
    if kind not in ("bar", "line"):
        raise ValueError("chart type must be bar or line")
    return {"type": kind, "title": title, "x_label": x_label, "y_label": y_label, "labels": [str(x) for x in labels[:MAX_POINTS]],
            "series": [{"name": s["name"], "values": [None if v is None else float(v) for v in s["values"][:MAX_POINTS]]} for s in series], "truncated": len(labels) > MAX_POINTS}


def from_result(out: dict) -> Optional[dict]:
    """Chart for an analysis result (group totals, sorted rows, trends); None when the result has no natural chart."""
    kind, p = out.get("kind"), out.get("plan", {})
    if kind in ("grouped", "group_extreme") and out.get("groups"):
        g = out["groups"][:MAX_POINTS]
        op = out.get("grouped_op", "sum")
        return spec("bar", f"{op} of {p.get('column') or 'rows'} by {p.get('group_by')}", [x["group"] for x in g], [{"name": p.get("column") or "count", "values": [x["value"] for x in g]}], p.get("group_by") or "", p.get("column") or "count")
    if kind == "sorted" and out.get("rows"):
        col = p.get("column")
        lab = [next((str(v) for v in r["values"].values() if isinstance(v, str) and v), f"row {r['row']}") for r in out["rows"]]
        return spec("bar", f"Top {len(lab)} by {col}", lab, [{"name": col, "values": [r["values"].get(col) for r in out["rows"]]}], "", col)
    if kind == "trend":
        tr = out["trend"]
        name = tr["value_column"] or "rows"
        return spec("line", f"{tr['agg']} of {name} by {tr['freq_name']}", [x["period"] for x in tr["periods"]], [{"name": name, "values": [x["value"] for x in tr["periods"]]}], tr["freq_name"], name)
    if kind == "distinct" and out.get("values"):
        v = out["values"][:MAX_POINTS]
        return spec("bar", f"Distinct values of {p.get('column')}", [x["value"] for x in v], [{"name": "count", "values": [x["count"] for x in v]}], p.get("column") or "", "count")
    return None


def render_png(chart: dict, width: float = 7.0, height: float = 3.6, dpi: int = 130) -> bytes:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(width, height), dpi=dpi)
    try:
        labels, n = chart["labels"], len(chart["series"])
        xs = range(len(labels))
        if chart["type"] == "bar":
            w = 0.8 / max(n, 1)
            for i, s in enumerate(chart["series"]):
                ax.bar([x + i * w - 0.4 + w / 2 for x in xs], [v or 0 for v in s["values"]], w, label=s["name"], color=f"C{i}")
        else:
            for i, s in enumerate(chart["series"]):
                ax.plot(list(xs), [float("nan") if v is None else v for v in s["values"]], marker="o", label=s["name"], color=f"C{i}")
        step = max(1, len(labels) // 12)
        ax.set_xticks(list(xs)[::step])
        ax.set_xticklabels(labels[::step], rotation=35, ha="right", fontsize=8)
        ax.set_title(chart.get("title", ""), fontsize=11)
        ax.set_xlabel(chart.get("x_label", ""))
        ax.set_ylabel(chart.get("y_label", ""))
        ax.grid(axis="y", alpha=0.3)
        if n > 1:
            ax.legend(fontsize=8)
        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png")
        return buf.getvalue()
    finally:
        plt.close(fig)
