"""Optional RAGAS integration (faithfulness, answer relevancy, context precision/recall judged by an LLM).

Status: the adapter builds the RAGAS dataset from our report and parses its result. It has only been exercised against a stub of the
`ragas` module (plumbing test); it has NOT been run against the real library here because that needs `pip install ragas` plus LLM
credentials. The built-in proxy metrics in app.eval.metrics do not depend on it."""
from __future__ import annotations

from typing import Optional


def ragas_scores(report: dict, contexts_by_case: dict[str, list[str]], ground_truth: dict[str, str]) -> Optional[dict]:
    try:
        from datasets import Dataset  # type: ignore
        from ragas import evaluate  # type: ignore
        from ragas.metrics import answer_relevancy, context_precision, context_recall, faithfulness  # type: ignore
    except ImportError:
        return None
    rows = [c for c in report["cases"] if c["id"] in contexts_by_case and c.get("verified")]
    if not rows:
        return {}
    ds = Dataset.from_dict({"question": [r["question"] for r in rows], "answer": [r["answer"] for r in rows], "contexts": [contexts_by_case[r["id"]] for r in rows],
                            "ground_truth": [ground_truth.get(r["id"], "") for r in rows]})
    res = evaluate(ds, metrics=[faithfulness, answer_relevancy, context_precision, context_recall])
    return {k: float(v) for k, v in dict(res).items()}
