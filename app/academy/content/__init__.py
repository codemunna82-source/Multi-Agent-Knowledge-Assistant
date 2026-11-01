"""Lesson content. Each module in this package exports LESSONS (list of dicts); glossary, projects and extra interview questions have their own modules."""
from __future__ import annotations

import importlib

MODULES = ["c01_fundamentals", "c02_llm", "c03_prompting", "c04_embeddings", "c05_langchain", "c06_rag", "c07_adv_rag", "c08_langgraph", "c09_agentic", "c10_to_c15_production", "c10b_production"]


def T(en: str, hi: str, hinglish: str) -> dict:
    """A text in the three supported languages."""
    return {"en": en, "hi": hi, "hinglish": hinglish}


def load_lessons() -> list[dict]:
    out: list[dict] = []
    for m in MODULES:
        try:
            out.extend(importlib.import_module(f"{__name__}.{m}").LESSONS)
        except ModuleNotFoundError as e:       # content is added module by module
            if e.name != f"{__name__}.{m}":
                raise
    return out
