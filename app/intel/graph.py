"""Knowledge graph + Graph RAG over entity co-occurrence.

Nodes = entities found in chunks (computed at ingestion, stored in each source's graph.json). Edge weight = number of sentences
in which both entities occur. Everything is derived from, and links back to, verbatim chunks - answers are evidence, not
model-invented relations. (Relation *types* such as 'works for' would need an LLM triple extractor: not implemented.)"""
from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field

import networkx as nx

from ..storage import SessionStore
from .entities import norm


@dataclass
class Node:
    key: str
    name: str
    type: str
    chunks: list[str] = field(default_factory=list)


class KnowledgeGraph:
    def __init__(self, st: SessionStore, allowed: frozenset[str]):
        """Built ONLY from `allowed` sources, so entities / relations from documents a user may not see can never surface."""
        self.G = nx.Graph()
        self.nodes: dict[str, Node] = {}
        names: dict[str, str] = {}
        for meta in st.list_sources():
            if meta["id"] not in allowed:
                continue
            p = st.source_dir(meta["id"]) / "graph.json"
            if not p.exists():
                continue
            for cid, groups in json.loads(p.read_text(encoding="utf-8")).items():
                for ents in groups:  # one group per sentence
                    keys = []
                    for typ, v in ents[:12]:
                        k = f"{typ}:{norm(v)}"
                        n = self.nodes.setdefault(k, Node(k, v, typ))
                        if cid not in n.chunks:
                            n.chunks.append(cid)
                        names[k] = n.name
                        keys.append(k)
                    for i, a in enumerate(keys):
                        for b in keys[i + 1:]:
                            if a == b:
                                continue
                            if self.G.has_edge(a, b):
                                self.G[a][b]["weight"] += 1
                                if cid not in self.G[a][b]["chunks"] and len(self.G[a][b]["chunks"]) < 25:
                                    self.G[a][b]["chunks"].append(cid)
                            else:
                                self.G.add_edge(a, b, weight=1, chunks=[cid])
        for k in self.nodes:
            self.G.add_node(k)
        self._matchers = sorted(((re.compile(r"(?<!\w)" + r"\s+".join(map(re.escape, n.name.split())) + r"(?!\w)", re.I), k) for k, n in self.nodes.items()),
                                key=lambda x: -len(self.nodes[x[1]].name))

    def find(self, text: str, limit: int = 6) -> list[str]:
        """Entity nodes mentioned in `text` (longest names first; a shorter name inside an already matched longer name is skipped)."""
        found, spans = [], []
        for pat, k in self._matchers:
            for m in pat.finditer(text):
                if not any(m.start() < y and x < m.end() for x, y in spans):
                    spans.append((m.start(), m.end()))
                    if k not in found:
                        found.append(k)
                    break
            if len(found) >= limit:
                break
        return found

    def neighbors(self, key: str, k: int = 10) -> list[tuple[str, int]]:
        return sorted(((n, self.G[key][n]["weight"]) for n in self.G.neighbors(key)), key=lambda x: (-x[1], x[0]))[:k]

    def path(self, a: str, b: str) -> list[str] | None:
        try:
            return nx.shortest_path(self.G, a, b, weight=lambda u, v, d: 1.0 / d["weight"])
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None

    def top(self, k: int = 10) -> list[tuple[str, int]]:
        return sorted(((n, self.G.degree(n, weight="weight")) for n in self.G.nodes), key=lambda x: (-x[1], x[0]))[:k]

    def expand_chunks(self, query_keys: list[str], limit: int = 20) -> list[str]:
        """Graph RAG expansion: chunks that mention a query entity, then chunks that connect it to its strongest neighbours."""
        scored: dict[str, float] = {}
        for qk in query_keys:
            for c in self.nodes[qk].chunks:
                scored[c] = scored.get(c, 0.0) + 1.0
            for nb, w in self.neighbors(qk, 5):
                for c in self.G[qk][nb]["chunks"][:3]:
                    scored[c] = scored.get(c, 0.0) + 0.5
        return [c for c, _ in sorted(scored.items(), key=lambda x: -x[1])][:limit]


class GraphCache:
    def __init__(self):
        self._c: dict[str, tuple] = {}
        self._lock = threading.Lock()

    def get(self, st: SessionStore, allowed) -> KnowledgeGraph:
        allowed = frozenset(allowed)
        key = (st.session, allowed)
        ver = st.version()
        with self._lock:
            hit = self._c.get(key)
            if hit and hit[0] == ver:
                return hit[1]
        g = KnowledgeGraph(st, allowed)
        with self._lock:
            if len(self._c) > 64:
                self._c.clear()
            self._c[key] = (ver, g)
        return g
