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
        if self.script:
            out = self.script(system, user)
            if out is not None:
                return out
        return "OK"

    def describe_image(self, data: bytes, mime: str, prompt: str) -> str:
        self.calls += 1
        return self.image_caption
