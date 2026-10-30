"""LangGraph StateGraph wiring.

    START -> supervisor --(route)--> exact | data ------------------------------------------> final
                          \\-------> semantic | document_search | web | summarize | compare -> verify --pass/fail--> final
                                          ^                                           |
                                          +------------------ retry (bounded) -------+
    semantic --(abstained + web fallback enabled)--> web
    supervisor --(compound question)--> Send x N -> branch (agent + verification, concurrently) -> merge -> final

Conditional edges decide the path; `verify` bounds retries with settings.max_retries."""
from __future__ import annotations

from langgraph.graph import END, StateGraph
from langgraph.types import Send

from .nodes import Agents
from .state import AgentState

GENERATIVE = ("semantic", "document_search", "web", "summarize", "compare")
DETERMINISTIC = ("exact", "data")


def build_graph(agents: Agents, checkpointer=None):
    s = agents.k.settings
    g = StateGraph(AgentState)
    m = agents.metered
    g.add_node("supervisor", m(agents.supervisor))
    for name in DETERMINISTIC + GENERATIVE:
        g.add_node(name, m(getattr(agents, name)))
    g.add_node("branch", agents.branch)  # runs one sub-question through its agent (+ verification); metered per inner node
    g.add_node("merge", m(agents.merge))
    g.add_node("verify", m(agents.verify))
    g.add_node("final", m(agents.final))
    g.set_entry_point("supervisor")
    def after_supervisor(st: AgentState):
        if st["route"] == "parallel":  # compound question: fan out, one branch per sub-question, executed concurrently
            return [Send("branch", {**st, "branch": {**b, "i": i}}) for i, b in enumerate(st["plan"]["branches"])]
        return st["route"]

    g.add_conditional_edges("supervisor", after_supervisor, {**{r: r for r in DETERMINISTIC + GENERATIVE}, "branch": "branch"})
    g.add_edge("branch", "merge")
    g.add_edge("merge", "final")
    g.add_edge("exact", "final")
    g.add_conditional_edges("data", lambda st: "semantic" if st.get("route") == "semantic" else "final", {"semantic": "semantic", "final": "final"})

    def after_semantic(st: AgentState) -> str:
        d = st.get("draft") or {}
        can_web = s.web_fallback and s.web_search_provider != "none" and s.web_enabled and not (st.get("plan") or {}).get("web_tried")
        return "web" if d.get("abstained") and can_web else "verify"

    g.add_conditional_edges("semantic", after_semantic, {"web": "web", "verify": "verify"})
    for r in ("document_search", "web", "summarize", "compare"):
        g.add_edge(r, "verify")

    def after_verify(st: AgentState) -> str:
        v = st.get("verification") or {}
        return st["route"] if v.get("status") == "retry" else "final"

    g.add_conditional_edges("verify", after_verify, {**{r: r for r in GENERATIVE}, "final": "final"})
    g.add_edge("final", END)
    return g.compile(checkpointer=checkpointer)
