"""CLI:  python -m app.eval run --sample [--compare] [--out report.html]   |   python -m app.eval run --dataset cases.json --scope tenant/workspace"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from ..agents import Assistant
from ..config import Settings
from ..rag import RetrievalOptions
from ..service import Knowledge
from ..storage import Scope
from .dataset import EvalDataset
from .report import html_report, markdown
from .runner import compare_strategies, run_eval

STRATEGIES = {
    "semantic": RetrievalOptions(mode="semantic", reranker="none", compression=False, parent_child=False, corrective=False),
    "keyword (BM25)": RetrievalOptions(mode="keyword", reranker="none", compression=False, parent_child=False, corrective=False),
    "hybrid": RetrievalOptions(mode="hybrid", reranker="none", compression=False, parent_child=False, corrective=False),
    "hybrid + lexical rerank": RetrievalOptions(mode="hybrid", reranker="lexical", compression=False, parent_child=False, corrective=False),
    "hybrid + rerank + parent-child + corrective": RetrievalOptions(mode="hybrid", reranker="lexical", compression=True, parent_child=True, corrective=True),
    "hybrid + multi-query + graph": RetrievalOptions(mode="hybrid", reranker="lexical", multi_query=True, graph=True, corrective=True),
}


def build_sample(settings: Settings, workdir: Path):
    from .sample import corpus, dataset

    k = Knowledge(settings)
    a = Assistant(k)
    scope = Scope("eval", "sample")
    for name, data in corpus().items():
        p = workdir / name
        p.write_bytes(data)
        r = k.ingest_file(scope, p, name)
        assert r["status"] == "ready", r
    return a, scope, dataset()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.eval")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--sample", action="store_true", help="ingest the built-in synthetic corpus into a throw-away data dir and evaluate it")
    r.add_argument("--dataset", help="JSON/JSONL dataset file (evaluates the existing workspace given by --scope)")
    r.add_argument("--scope", default="default/default", help="tenant/workspace for --dataset")
    r.add_argument("--compare", action="store_true", help="also compare retrieval strategies")
    r.add_argument("--out", default="eval_report", help="output path prefix (writes .json, .md, .html)")
    a = ap.parse_args(argv)
    with tempfile.TemporaryDirectory() as td:
        if a.sample:
            settings = Settings(data_dir=td + "/data", _env_file=None)
            assistant, scope, ds = build_sample(settings, Path(td))
        else:
            settings = Settings()
            assistant, ds = Assistant(Knowledge(settings)), EvalDataset.load(a.dataset)
            t, w = a.scope.split("/")
            scope = Scope(t, w)
        from ..security.auth import ANONYMOUS

        rep = run_eval(assistant, scope, ANONYMOUS, ds, None, name="default strategy")
        if a.compare:
            cmp = compare_strategies(assistant, scope, ANONYMOUS, ds, STRATEGIES)
            rep["comparison"] = cmp["comparison"]
    out = Path(a.out)
    out.with_suffix(".json").write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding="utf-8")
    out.with_suffix(".md").write_text(markdown(rep), encoding="utf-8")
    out.with_suffix(".html").write_text(html_report(rep), encoding="utf-8")
    print(markdown(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
