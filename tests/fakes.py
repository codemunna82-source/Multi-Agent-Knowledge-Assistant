"""Deterministic test doubles. They exercise OUR orchestration (routing, retries, grading, verification, guards); they say
nothing about the quality of a real LLM."""
from __future__ import annotations

from typing import Callable, Optional

from app.core import ProviderError
from app.providers import LLM


class FakeLLM(LLM):
    available = True
    name = "fake"

    def __init__(self, script: Optional[Callable[[str, str], Optional[str]]] = None, image_caption: str = "", fail: bool = False):
        self.script, self.image_caption, self.fail = script, image_caption, fail
        self.calls = 0
        self.log: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.calls += 1
        self.log.append((system, user))
        if self.fail:
            raise ProviderError("simulated outage")
        out = self.script(system, user) if self.script else None
        out = "OK" if out is None else out
        self._meter(system, user, out)
        return out

    def describe_image(self, data: bytes, mime: str, prompt: str) -> str:
        self.calls += 1
        return self.image_caption


class ConceptEmbedder:
    """Tiny controllable embedder: synonyms share an axis, so we can prove semantic (non-lexical) retrieval works."""

    GROUPS = [{"car", "automobile", "vehicle"}, {"warranty", "guarantee"}, {"quit", "resign", "resignation", "leave"}, {"salary", "pay", "wage", "compensation"}]

    def __init__(self, dim: int = 64):
        import numpy as np

        self.np, self.dim, self.name = np, dim, f"concept:{dim}"

    def _vec(self, text: str):
        import zlib

        from app.core import tokenize

        v = self.np.zeros(self.dim, dtype=self.np.float32)
        for t in tokenize(text):
            g = next((i for i, grp in enumerate(self.GROUPS) if t in grp), None)
            if g is not None:
                v[g] += 1.0
            else:
                v[8 + zlib.crc32(t.encode()) % (self.dim - 8)] += 0.35
        n = self.np.linalg.norm(v)
        return v / n if n else v

    def embed_documents(self, texts):
        return self.np.vstack([self._vec(t) for t in texts]) if texts else self.np.zeros((0, self.dim), dtype=self.np.float32)

    def embed_query(self, text):
        return self._vec(text)
