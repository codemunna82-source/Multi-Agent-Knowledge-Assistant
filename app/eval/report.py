"""Markdown and self-contained HTML evaluation reports (no external assets)."""
from __future__ import annotations

import html


def _f(v, nd=3) -> str:
    return "—" if v is None else (f"{v:.{nd}f}" if isinstance(v, float) else str(v))


def _pct(v) -> str:
    return "—" if v is None else f"{100 * v:.1f}%"


def kpis(rep: dict) -> list[tuple[str, str, str]]:
    m = rep["metrics"]
    r, a, lat = m["retrieval"], m["answers"], m["latency_ms"]
    return [("Recall@5", _pct(r["recall@5"]), "share of gold passages found in the top 5"), ("Precision@5", _pct(r["precision@5"]), "relevant results in the top 5 (÷5)"),
            ("MRR", _f(r["mrr"]), "mean reciprocal rank of the first relevant result"), ("Faithfulness*", _pct(a["faithfulness_lexical (proxy)"]), "lexical proxy (not RAGAS)"),
            ("Answer relevancy*", _pct(a["answer_relevancy_embedding (proxy)"]), "embedding proxy (not RAGAS)"), ("Latency p50 / p95", f"{_f(lat['p50'], 0)} / {_f(lat['p95'], 0)} ms", "end-to-end per question"),
            ("Tokens / query", _f(m["tokens"]["per_query"], 0), "estimated" if m["tokens"]["estimated"] else "provider-reported"), ("Est. cost / query", f"${m['cost_usd']['per_query']:.5f}", "from MKA_PRICE_TABLE")]


def markdown(rep: dict) -> str:
    m = rep["metrics"]
    L = [f"# Evaluation report — {rep['name']}", "", f"*Dataset:* `{rep['dataset']}` · *cases:* {m['cases']} · *run:* {rep['created']} · *duration:* {rep['duration_s']}s", "",
         f"*Embedder:* `{rep['config']['embedder']}` · *LLM:* `{rep['config']['llm']}` · *vector store:* `{rep['config']['vector_store']}`", "", "## Headline metrics", "", "| Metric | Value | Meaning |", "|---|---|---|"]
    L += [f"| {a} | {b} | {c} |" for a, b, c in kpis(rep)]
    L += ["", "## Retrieval", "", "| K | Recall@K | Precision@K | nDCG@K |", "|---|---|---|---|"]
    L += [f"| {k} | {_pct(m['retrieval'][f'recall@{k}'])} | {_pct(m['retrieval'][f'precision@{k}'])} | {_f(m['retrieval'][f'ndcg@{k}'])} |" for k in (1, 3, 5)]
    L += ["", f"MRR: **{_f(m['retrieval']['mrr'])}** over {m['retrieval']['cases_with_gold']} cases with gold passages.", "", "## Answers", "", "| Metric | Value |", "|---|---|"]
    L += [f"| {k} | {_pct(v)} |" for k, v in m["answers"].items()]
    L += ["", "## By question type", "", "| Type | Cases | Correct | Recall@5 | MRR | Route accuracy | p50 ms |", "|---|---|---|---|---|---|---|"]
    L += [f"| {t} | {d['cases']} | {_pct(d['correct'])} | {_pct(d['recall@5'])} | {_f(d['mrr'])} | {_pct(d['route_accuracy'])} | {_f(d['latency_p50_ms'], 1)} |" for t, d in m["by_type"].items()]
    if rep.get("comparison"):
        L += ["", "## Strategy comparison", "", "| Strategy | Recall@5 | Precision@5 | MRR | nDCG@5 | p50 ms | p95 ms | $/query |", "|---|---|---|---|---|---|---|---|"]
        L += [f"| {c['strategy']} | {_pct(c['recall@5'])} | {_pct(c['precision@5'])} | {_f(c['mrr'])} | {_f(c['ndcg@5'])} | {_f(c['p50_ms'], 1)} | {_f(c['p95_ms'], 1)} | {c['cost_per_query']:.5f} |" for c in rep["comparison"]]
    L += ["", f"## Failures ({len(rep['failures'])})", ""]
    L += [f"- `{f['id']}` {f['question']} — {', '.join(f['why'])}" for f in rep["failures"]] or ["None."]
    L += ["", "## Notes", ""] + [f"- {n}" for n in rep["notes"]]
    return "\n".join(L) + "\n"


CSS = """body{font:14px/1.5 system-ui,sans-serif;margin:0;background:#f6f7f9;color:#1d2330}main{max-width:1100px;margin:auto;padding:24px}
h1{font-size:22px}h2{font-size:16px;margin-top:28px}.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}
.tile{background:#fff;border:1px solid #e2e5ec;border-radius:10px;padding:12px}.tile b{display:block;font-size:22px}.tile span{color:#6b7385;font-size:12px}
table{border-collapse:collapse;width:100%;background:#fff;border:1px solid #e2e5ec}th,td{padding:6px 10px;border-bottom:1px solid #e2e5ec;text-align:left;font-size:13px}th{background:#f0f2f6}
.bar{background:#e8ebf2;border-radius:4px;height:8px;width:120px;display:inline-block;vertical-align:middle}.bar i{display:block;height:8px;border-radius:4px;background:#3b5bdb}
.bad{color:#c92a2a}.ok{color:#2b8a3e}.muted{color:#6b7385}code{background:#eceff5;padding:1px 5px;border-radius:4px}
@media (prefers-color-scheme:dark){body{background:#14171f;color:#e6e9f0}.tile,table{background:#1d222d;border-color:#2c3342}th{background:#252b38}th,td{border-color:#2c3342}.bar{background:#2c3342}}"""


def _bar(v) -> str:
    return "—" if v is None else f'<span class="bar"><i style="width:{max(0, min(1, v)) * 100:.0f}%"></i></span> {100 * v:.1f}%'


def html_report(rep: dict) -> str:
    e = html.escape
    m = rep["metrics"]
    t = [f"<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>Evaluation report</title><style>{CSS}</style><main>",
         f"<h1>Evaluation report — {e(rep['name'])}</h1><p class=muted>Dataset <code>{e(rep['dataset'])}</code> · {m['cases']} cases · {e(rep['created'])} · {rep['duration_s']}s · "
         f"embedder <code>{e(rep['config']['embedder'])}</code> · LLM <code>{e(rep['config']['llm'])}</code> · vector store <code>{e(rep['config']['vector_store'])}</code></p>",
         "<div class=tiles>" + "".join(f"<div class=tile><span>{e(a)}</span><b>{e(b)}</b><span>{e(c)}</span></div>" for a, b, c in kpis(rep)) + "</div>",
         "<h2>Retrieval</h2><table><tr><th>K<th>Recall@K<th>Precision@K<th>nDCG@K</tr>"]
    for k in (1, 3, 5):
        r = m["retrieval"]
        t.append(f"<tr><td>{k}<td>{_bar(r[f'recall@{k}'])}<td>{_bar(r[f'precision@{k}'])}<td>{_f(r[f'ndcg@{k}'])}</tr>")
    t.append(f"</table><p>MRR <b>{_f(m['retrieval']['mrr'])}</b> over {m['retrieval']['cases_with_gold']} cases with gold passages.</p><h2>Answers</h2><table><tr><th>Metric<th>Value</tr>")
    t += [f"<tr><td>{e(k)}<td>{_bar(v)}</tr>" for k, v in m["answers"].items()]
    t.append("</table><h2>By question type</h2><table><tr><th>Type<th>Cases<th>Correct<th>Recall@5<th>MRR<th>Route acc.<th>p50 ms</tr>")
    t += [f"<tr><td>{e(k)}<td>{d['cases']}<td>{_bar(d['correct'])}<td>{_bar(d['recall@5'])}<td>{_f(d['mrr'])}<td>{_bar(d['route_accuracy'])}<td>{_f(d['latency_p50_ms'], 1)}</tr>" for k, d in m["by_type"].items()]
    t.append("</table>")
    if rep.get("comparison"):
        t.append("<h2>Strategy comparison</h2><table><tr><th>Strategy<th>Recall@5<th>Precision@5<th>MRR<th>nDCG@5<th>p50 ms<th>p95 ms<th>$/query</tr>")
        t += [f"<tr><td>{e(c['strategy'])}<td>{_bar(c['recall@5'])}<td>{_bar(c['precision@5'])}<td>{_f(c['mrr'])}<td>{_f(c['ndcg@5'])}<td>{_f(c['p50_ms'], 1)}<td>{_f(c['p95_ms'], 1)}<td>{c['cost_per_query']:.5f}</tr>" for c in rep["comparison"]]
        t.append("</table>")
    t.append(f"<h2>Failures ({len(rep['failures'])})</h2><ul>" + ("".join(f"<li><code>{e(f['id'])}</code> {e(f['question'])} — <span class=bad>{e(', '.join(f['why']))}</span>" for f in rep["failures"]) or "<li>None") + "</ul>")
    t.append("<h2>All cases</h2><table><tr><th>ID<th>Type<th>Route<th>Verified<th>Recall@5<th>RR<th>ms<th>Question</tr>")
    for c in rep["cases"]:
        t.append(f"<tr><td>{e(c['id'])}<td>{e(c['type'])}<td>{e(c['route'])}<td class={'ok' if c['verified'] else 'muted'}>{'yes' if c['verified'] else 'no'}<td>{_f(c.get('recall@5'), 2)}<td>{_f(c.get('mrr'), 2)}<td>{c['latency_ms']:.0f}<td>{e(c['question'])}</tr>")
    t.append("</table><h2>Notes</h2><ul>" + "".join(f"<li>{e(n)}</li>" for n in rep["notes"]) + "</ul></main>")
    return "".join(t)
