"""Follow-up question suggestions: LLM-written when available (validated), otherwise templated from real entities in the evidence."""
from __future__ import annotations


from ..core import ProviderError
from ..rag.steps import parse_json
from ..security.injection import SYSTEM_GUARD, wrap_untrusted


def _heuristic(state, draft) -> list[str]:
    route, term = draft.get("route", ""), state.get("term")
    out: list[str] = []
    cites = draft.get("citations", [])
    if route.startswith("exact") and term:
        if draft.get("details", {}).get("count"):
            out += [f'Show the surrounding text for each match of "{term}"', f'Does "{term}" appear in any other document?']
        else:
            out += [f'Search for a different spelling of "{term}"']
    elif route == "data":
        det = draft.get("details", {}).get("plan", {})
        col = det.get("column")
        if col:
            out += [f"Show the top 5 rows by {col}", f"What is the average {col}?"]
            if not det.get("group_by"):
                out += [f"Break down {col} by group"]
        out += ["Are there duplicate rows?"]
    elif cites:
        src = cites[0]["source"]
        from ..intel.entities import entities_in

        names = list(dict.fromkeys(v for c in cites[:3] for _, v in entities_in(c["excerpt"], ["NAME", "ORG"])))[:2]  # real people/organisations, not capitalised sentence starts
        out += [f"Summarize {src}"]
        out += [f"Tell me more about {n}" for n in names]
        if len({c["source"] for c in cites}) > 1:
            out += ["Compare what these documents say about this"]
    return out[:3]


def suggest_followups(k, ctx, state, draft) -> list[str]:
    if draft.get("needs_input") or not draft.get("verified", True):
        return []
    if k.llm.available and draft.get("citations") and draft.get("route") in ("semantic", "document_search", "web", "summarize"):
        ev = "\n".join(f"- {c['excerpt'][:200]}" for c in draft["citations"][:4])
        sys = f'Suggest 3 short follow-up questions the user could ask next, answerable from the same documents. JSON only: {{"questions": ["..."]}}. {SYSTEM_GUARD}'
        try:
            j = parse_json(k.llm.complete(sys, f"Question: {state['question'][:300]}\nAnswer: {draft['answer'][:500]}\n{wrap_untrusted(ev, 'evidence')}"))
            qs = (j or {}).get("questions") if isinstance(j, dict) else None
            if isinstance(qs, list):
                good = [q.strip() for q in qs if isinstance(q, str) and 5 <= len(q.strip()) <= 160 and q.strip().endswith("?")]
                if good:
                    return good[:3]
        except ProviderError:
            pass
    return _heuristic(state, draft)
