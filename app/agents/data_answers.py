"""Turn a pandas plan result into a user-facing answer with row-level citations."""
from __future__ import annotations

from ..schemas import Citation
from .common import fmt, result


def _cite(r: dict) -> Citation:
    loc = (f"sheet '{r['sheet']}', " if "sheet" in r else "") + f"row {r['row']}"
    return Citation(source_id=r["source_id"], source=r["source"], location=loc, excerpt="; ".join(f"{k}: {v}" for k, v in r["values"].items() if v is not None),
                    loc={**({"sheet": r["sheet"]} if "sheet" in r else {}), "row": r["row"]})


def _label(r: dict) -> str:
    for k, v in r["values"].items():
        if isinstance(v, str) and v:
            return f"{k} = {v}"
    return f"row {r['row']}"


def format_data_answer(out: dict) -> dict:
    p, tb = out["plan"], out["table"]
    col, grp = p.get("column"), p.get("group_by")
    flt = "; ".join(f"{f['column']} {f['op']} {f['value']}" for f in p.get("filters", []))
    where = f" where {flt}" if flt else ""
    src = tb["source"] + (f" / {tb['sheet']}" if tb.get("sheet") else "")
    cites = [_cite(r) for r in out.get("rows", [])]
    kind = out["kind"]
    word = {"max": "highest", "min": "lowest", "sum": "total", "mean": "average", "count": "count", "median": "median"}.get(p["op"], p["op"])
    lim = ["Computed with pandas over the full table; row numbers are spreadsheet rows (header = row 1)."]
    details = {"plan": p, "result": {k: v for k, v in out.items() if k in ("value", "groups", "winners", "rows_considered", "matching_rows", "columns", "duplicate_groups", "diff")}}
    conf = "high"
    if kind == "empty":
        ans = f"No rows in {src} matched{where or ' the question'}, so no figure can be calculated."
    elif kind == "scalar":
        ans = (f"{fmt(out['value'])} row(s) in {src}{where}." if p["op"] == "count"
               else f"The {word} of {col} in {src}{where} is {fmt(out['value'])} (over {out['rows_considered']} rows).")
    elif kind == "row_extreme":
        rows = out["rows"]
        who = "; ".join(_label(r) + f" (row {r['row']})" for r in rows[:5])
        ans = f"The {word} {col} in {src}{where} is {fmt(out['value'])}: {who}" + (f" (+{out['matching_rows'] - 5} more tied)" if out["matching_rows"] > 5 else "") + "."
    elif kind == "group_extreme":
        top = ", ".join(f"{g['group']}: {fmt(g['value'])}" for g in out["groups"][:5])
        ans = f"By {grp}, {', '.join(out['winners'])} has the {word} total {col} ({fmt(out['value'])}) in {src}{where}. Ranking: {top}."
        lim.append("Groups are ranked by the sum of the column.")
    elif kind == "grouped":
        op = out["grouped_op"]
        top = "; ".join(f"{g['group']}: {fmt(g['value'])}" for g in out["groups"][:15])
        ans = f"{op.capitalize()}{' of ' + col if col else ''} by {grp} in {src}{where}: {top}."
    elif kind == "distinct":
        vals = ", ".join(f"{v['value']} ({v['count']})" for v in out["values"][:20])
        ans = f"{out['value']} distinct value(s) of {col} in {src}{where}: {vals}" + (" …" if out["value"] > 20 else "") + "."
    elif kind == "sorted":
        lines = "\n".join(f"{i}. row {r['row']}: " + "; ".join(f"{k}: {v}" for k, v in r["values"].items() if v is not None) for i, r in enumerate(out["rows"], 1))
        ans = f"{src}{where} sorted by {col} ({'ascending' if p.get('ascending') else 'descending'}), top {len(out['rows'])}:\n{lines}"
    elif kind == "duplicates":
        by = ", ".join(out["columns"])
        if not out["duplicate_groups"]:
            ans = f"No duplicate rows found in {src} (compared on: {by})."
        else:
            ex = "; ".join(f"{g['key']} ×{g['count']} (rows {', '.join(map(str, g['rows'][:6]))})" for g in out["duplicate_groups"][:8])
            ans = f"{len(out['duplicate_groups'])} duplicated value group(s) in {src} on [{by}], {out['matching_rows']} rows involved: {ex}."
    elif kind == "compare":
        d = out["diff"]
        ans = (f"Comparison of {d['left']} vs {d['right']} (key: {d['key']}): {d['only_left_count']} row(s) only in the first, {d['only_right_count']} only in the second, "
               f"{d['changed_count']} with different values, {d['same_count']} identical." + (f" Columns only in first: {', '.join(d['cols_only_left'])}." if d["cols_only_left"] else "")
               + (f" Columns only in second: {', '.join(d['cols_only_right'])}." if d["cols_only_right"] else ""))
        for ch in d["changed"][:5]:
            ans += f"\n- {ch['key']}: " + "; ".join(f"{c}: {a} → {b}" for c, (a, b) in ch["diff"].items())
    else:
        ans, conf = "Done.", "medium"
    if out.get("matching_rows", 0) > len(cites) and cites:
        lim.append(f"Showing {len(cites)} of {out['matching_rows']} contributing rows as citations.")
    return result("data", ans, confidence=conf, citations=cites, limitations=lim, details=details)
