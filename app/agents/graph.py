"""LangGraph StateGraph wiring.

    START -> supervisor --(route)--> exact | data ------------------------------------------> final
                          \\-------> semantic | document_search | web | summarize -> verify --pass/fail--> final
                                          ^                                           |
                                          +------------------ retry (bounded) -------+
    semantic --(abstained + web fallback enabled)--> web

Conditional edges decide the path; `verify` bounds retries with settings.max_retries."""
from __future__ import annotations

from langgraph.graph import END, StateGraph

from .nodes import Agents
from .state import AgentState

GENERATIVE = ("semantic", "document_search", "web", "summarize")
DETERMINISTIC = ("exact", "data")


def build_graph(agents: Agents, checkpointer=None):
    s = agents.k.settings
    g = StateGraph(AgentState)
    m = agents.metered
    g.add_node("supervisor", m(agents.supervisor))
    for name in DETERMINISTIC + GENERATIVE:
        g.add_node(name, m(getattr(agents, name)))
    g.add_node("verify", m(agents.verify))
    g.add_node("final", m(agents.final))
    g.set_entry_point("supervisor")
    g.add_conditional_edges("supervisor", lambda st: st["route"], {r: r for r in DETERMINISTIC + GENERATIVE})
    g.add_edge("exact", "final")
    g.add_conditional_edges("data", lambda st: "semantic" if st.get("route") == "semantic" else "final", {"semantic": "semantic", "final": "final"})

    def after_semantic(st: AgentState) -> str:
        d = st.get("draft") or {}
        can_web = s.web_fallback and s.web_search_provider != "none" and s.web_enabled and not (st.get("plan") or {}).get("web_tried")
        return "web" if d.get("abstained") and can_web else "verify"

    g.add_conditional_edges("semantic", after_semantic, {"web": "web", "verify": "verify"})
    for r in ("document_search", "web", "summarize"):
        g.add_edge(r, "verify")

    def after_verify(st: AgentState) -> str:
        v = st.get("verification") or {}
        return st["route"] if v.get("status") == "retry" else "final"

    g.add_conditional_edges("verify", after_verify, {**{r: r for r in GENERATIVE}, "final": "final"})
    g.add_edge("final", END)
    return g.compile(checkpointer=checkpointer)
