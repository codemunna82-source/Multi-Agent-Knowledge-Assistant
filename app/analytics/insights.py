"""Deterministic table insights computed with pandas: profile, anomalies (IQR / z-score), period trends and year-over-year change."""
from __future__ import annotations

import re
from typing import Optional

import numpy as np
import pandas as pd

from ..tools.tabular import PlanError, Table, _match_column, _qwords

FREQ = {"M": "month", "Q": "quarter", "Y": "year"}
LAG = {"M": 12, "Q": 4, "Y": 1}
INTENT_PROFILE = re.compile(r"\b(profile|data quality|missing values?|null values?|missing data|summary statistics|describe the (?:data|table|sheet)|overview of the (?:data|table|sheet))\b", re.I)
INTENT_ANOMALY = re.compile(r"\b(anomal\w+|outliers?|unusual|abnormal|suspicious values?)\b", re.I)
INTENT_TREND = re.compile(r"\b(trends?|over time|monthly|quarterly|yearly|annual(?:ly)?|year[- ]over[- ]year|yoy|month[- ]over[- ]month|growth|by (?:month|quarter|year)|per (?:month|quarter|year))\b", re.I)


def _py(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    return v.item() if hasattr(v, "item") else v


def clean(o):
    """Recursively turn numpy scalars into Python values (agent state is checkpointed with msgpack)."""
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    return _py(o)


def date_columns(t: Table, dayfirst: bool = False) -> dict[str, pd.Series]:
    """Text columns where >=90% of the non-blank cells parse as dates -> parsed series (NaT where blank/unparseable)."""
    out: dict[str, pd.Series] = {}
    for c in t.text:
        s = t.df[c].astype(str).str.strip()
        nonblank = s[s != ""]
        # a date has digits and is longer than a month name ("May" must not become a date)
        if nonblank.empty or not nonblank.str.contains(r"\d").all() or (nonblank.str.len() < 6).any():
            continue
        parsed = pd.to_datetime(s.where(s != ""), errors="coerce", format="mixed", dayfirst=dayfirst)
        if parsed.notna().sum() / len(nonblank) >= 0.9:
            out[c] = parsed
    return out


def column_types(t: Table) -> dict[str, str]:
    dates = date_columns(t)
    return {c: "number" if c in t.numeric else "date" if c in dates else "text" for c in t.df.columns}


def profile(t: Table, max_dups: int = 20) -> dict:
    df, types = t.df, column_types(t)
    cols = []
    for c in df.columns:
        s = df[c]
        blank = s.isna() | (s.astype(str).str.strip() == "")
        info = {"name": c, "type": types[c], "missing": int(blank.sum()), "missing_pct": round(100 * blank.mean(), 2) if len(df) else 0.0, "unique": int(s[~blank].astype(str).nunique())}
        if types[c] == "number":
            n = s.dropna()
            info.update(min=_py(n.min()), max=_py(n.max()), mean=_py(round(float(n.mean()), 4)), median=_py(n.median()), std=_py(round(float(n.std(ddof=1)), 4)) if len(n) > 1 else None)
        else:
            top = s[~blank].astype(str).str.strip().value_counts().head(5)
            info["top_values"] = [{"value": k, "count": int(v)} for k, v in top.items()]
        cols.append(info)
    norm = df.astype(str).apply(lambda x: x.str.strip().str.lower())
    dup = norm.duplicated(keep=False) & ~(norm == "").all(axis=1)
    return {"rows": int(len(df)), "columns": cols, "duplicate_rows": int(dup.sum()), "duplicate_row_numbers": [int(i) for i in df.index[dup][:max_dups]]}


def anomalies(t: Table, column: str, method: str = "iqr", threshold: Optional[float] = None) -> dict:
    if column not in t.numeric:
        raise PlanError(f"'{column}' is not a numeric column")
    if method not in ("iqr", "zscore"):
        raise PlanError("method must be iqr or zscore")
    s = t.df[column].dropna()
    res = {"column": column, "method": method, "count": 0, "rows": [], "values_considered": int(len(s))}
    if len(s) < 4:
        return {**res, "note": "Fewer than 4 values: too few to judge outliers", "bounds": None}
    if method == "iqr":
        k = 1.5 if threshold is None else float(threshold)
        q1, q3 = float(s.quantile(0.25)), float(s.quantile(0.75))
        iqr = q3 - q1
        lo, hi = q1 - k * iqr, q3 + k * iqr
        mask = (s < lo) | (s > hi)
        score = ((s - s.median()).abs() / iqr) if iqr else s * 0
        res.update(bounds={"low": round(lo, 6), "high": round(hi, 6), "q1": q1, "q3": q3, "k": k})
    else:
        z_t = 3.0 if threshold is None else float(threshold)
        std = float(s.std(ddof=1))
        if std == 0:
            return {**res, "note": "All values are identical", "bounds": None}
        mean = float(s.mean())
        score = (s - mean).abs() / std
        mask = score > z_t
        res.update(bounds={"low": round(mean - z_t * std, 6), "high": round(mean + z_t * std, 6), "mean": mean, "std": std, "z": z_t})
    hits = s[mask]
    ordered = hits.reindex(score[mask].sort_values(ascending=False, kind="stable").index)
    res["count"] = int(len(hits))
    res["rows"] = [{"row": int(i), "value": _py(v), "score": round(float(score[i]), 3)} for i, v in ordered.head(50).items()]
    return res


def _period(dates: pd.Series, freq: str) -> pd.Series:
    if freq == "M":
        return dates.dt.strftime("%Y-%m")
    if freq == "Q":
        return dates.dt.year.astype("Int64").astype(str) + "-Q" + dates.dt.quarter.astype("Int64").astype(str)
    return dates.dt.strftime("%Y")


def trend(t: Table, date_col: str, value_col: Optional[str], freq: str = "M", agg: str = "sum", dayfirst: bool = False) -> dict:
    if freq not in FREQ or agg not in ("sum", "mean", "count", "min", "max", "median"):
        raise PlanError("Unsupported frequency or aggregate")
    dates = date_columns(t, dayfirst).get(date_col)
    if dates is None:
        raise PlanError(f"'{date_col}' is not a date column")
    if value_col is None and agg != "count":
        raise PlanError("Which numeric column should I use?")
    if value_col is not None and value_col not in t.numeric:
        raise PlanError(f"'{value_col}' is not a numeric column")
    df = pd.DataFrame({"d": dates, "v": t.df[value_col] if value_col else 1}).dropna(subset=["d"])
    if df.empty:
        raise PlanError("No rows have a usable date")
    df["p"] = _period(df["d"], freq)
    g = df.groupby("p")["v"]
    ser = (g.size() if agg == "count" else getattr(g, agg)()).sort_index()
    vals = ser.astype(float)
    periods = []
    for i, (p, v) in enumerate(vals.items()):
        prev = vals.iloc[i - 1] if i else None
        periods.append({"period": p, "value": float(v), "rows": int(g.size()[p]),
                        "change": None if prev is None else float(v - prev), "change_pct": None if prev in (None, 0) else round(float((v - prev) / abs(prev) * 100), 2)})
    lag = LAG[freq]
    yoy = [{"period": periods[i]["period"], "vs": periods[i - lag]["period"], "change": periods[i]["value"] - periods[i - lag]["value"],
            "change_pct": None if periods[i - lag]["value"] == 0 else round((periods[i]["value"] - periods[i - lag]["value"]) / abs(periods[i - lag]["value"]) * 100, 2)}
           for i in range(lag, len(periods))] if freq != "Y" or len(periods) > 1 else []
    slope = float(np.polyfit(np.arange(len(vals)), vals.values, 1)[0]) if len(vals) >= 2 else 0.0
    rel = abs(slope) / (abs(float(vals.mean())) or 1)
    direction = "flat" if len(vals) < 2 or rel < 0.01 else "up" if slope > 0 else "down"
    best, worst = vals.idxmax(), vals.idxmin()
    sample = {p: [int(i) for i in df.index[df["p"] == p][:3]] for p in {best, worst}}
    return {"date_column": date_col, "value_column": value_col, "freq": freq, "freq_name": FREQ[freq], "agg": agg, "periods": periods, "yoy": yoy,
            "direction": direction, "slope_per_period": round(slope, 4), "best": {"period": best, "value": float(vals[best])}, "worst": {"period": worst, "value": float(vals[worst])},
            "total_change_pct": None if vals.iloc[0] == 0 else round(float((vals.iloc[-1] - vals.iloc[0]) / abs(vals.iloc[0]) * 100), 2), "sample_rows": sample,
            "undated_rows": int(len(t.df) - len(df))}


def detect_intent(question: str) -> Optional[str]:
    for name, pat in (("profile", INTENT_PROFILE), ("anomalies", INTENT_ANOMALY), ("trend", INTENT_TREND)):
        if pat.search(question):
            return name
    return None


def run_intent(intent: str, question: str, t: Table) -> Optional[dict]:
    out = _run_intent(intent, question, t)
    return None if out is None else clean(out)


def _run_intent(intent: str, question: str, t: Table) -> Optional[dict]:
    """-> a result dict shaped like tabular.execute(), or None when the table cannot serve the intent (caller falls back to the normal plan)."""
    qw, ql = _qwords(question), question.lower()
    table = {"source": t.source, "sheet": t.sheet}
    base = {"table": table, "rows_considered": int(len(t.df)), "value": None}
    if intent == "profile":
        return {**base, "kind": "profile", "plan": {"op": "profile"}, "profile": profile(t), "rows": []}
    metric = _match_column(qw, t.numeric) or (t.numeric[0] if len(t.numeric) == 1 else None)
    if intent == "anomalies":
        if metric is None:
            raise PlanError(f"Which numeric column should I check for outliers? Available: {', '.join(t.numeric) or 'none'}")
        method = "zscore" if re.search(r"z[- ]?score|standard deviation", ql) else "iqr"
        a = anomalies(t, metric, method)
        rows = [{"source_id": t.source_id, "source": t.source, "row": r["row"], "values": {k: _py(v) for k, v in t.df.loc[r["row"]].items()}, **({"sheet": t.sheet} if t.sheet is not None else {})}
                for r in a["rows"][:20]]
        return {**base, "kind": "anomalies", "plan": {"op": "anomalies", "column": metric, "method": method}, "anomalies": a, "rows": rows, "matching_rows": a["count"]}
    dates = date_columns(t)
    if not dates:
        return None
    dcol = _match_column(qw, list(dates)) or next(iter(dates))
    freq = "Q" if re.search(r"quarter", ql) else "Y" if re.search(r"year|annual", ql) and not re.search(r"year[- ]over[- ]year|yoy", ql) else "M"
    agg = "mean" if re.search(r"\b(average|mean|avg)\b", ql) else "count" if re.search(r"\b(how many|count|number of)\b", ql) else "sum"
    if metric is None and agg != "count":
        raise PlanError(f"Which numeric column should I trend? Available: {', '.join(t.numeric) or 'none'}")
    tr = trend(t, dcol, metric, freq, agg)
    rows = [{"source_id": t.source_id, "source": t.source, "row": rn, "values": {k: _py(v) for k, v in t.df.loc[rn].items()}, **({"sheet": t.sheet} if t.sheet is not None else {})}
            for rn in sorted({r for rs in tr["sample_rows"].values() for r in rs})[:6]]
    return {**base, "kind": "trend", "plan": {"op": "trend", "column": metric, "date_column": dcol, "freq": freq, "agg": agg}, "trend": tr, "rows": rows, "matching_rows": len(rows)}
