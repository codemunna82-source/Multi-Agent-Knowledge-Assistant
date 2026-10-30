"""Embedding and LLM providers. Keys come from settings/environment only."""
from __future__ import annotations

import hashlib
import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator, Optional

import httpx
import numpy as np

from .config import Settings
from .core import ProviderError, tokenize

log = logging.getLogger("mka.providers")


# ----------------------------------------------------------------------------- usage / cost metering (per request, via contextvar)
@dataclass
class Usage:
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    embed_tokens: int = 0
    cost_usd: float = 0.0
    estimated: bool = False  # True when token counts came from a chars/4 estimate rather than the provider's usage field

    def as_dict(self) -> dict:
        return {k: (round(v, 6) if isinstance(v, float) else v) for k, v in self.__dict__.items()}


_usage: ContextVar[Optional[Usage]] = ContextVar("mka_usage", default=None)
_PRICES: dict[str, tuple[float, float]] = {}


def set_price_table(spec: str) -> None:
    _PRICES.clear()
    for part in filter(None, (x.strip() for x in spec.split(","))):
        name, _, pr = part.partition("=")
        a, _, b = pr.partition(":")
        try:
            _PRICES[name.strip()] = (float(a), float(b or 0))
        except ValueError:
            log.warning("bad price entry %r", part)


@contextmanager
def track_usage() -> Iterator[Usage]:
    u = Usage()
    tok = _usage.set(u)
    try:
        yield u
    finally:
        _usage.reset(tok)


def est_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def record_llm(model: str, prompt_tokens: Optional[int], completion_tokens: Optional[int], prompt_text: str = "", out_text: str = "") -> None:
    u = _usage.get()
    if u is None:
        return
    est = prompt_tokens is None or completion_tokens is None
    pt = prompt_tokens if prompt_tokens is not None else est_tokens(prompt_text)
    ct = completion_tokens if completion_tokens is not None else est_tokens(out_text)
    pin, pout = _PRICES.get(model.split(":", 1)[-1], (0.0, 0.0))
    u.llm_calls += 1
    u.prompt_tokens += pt
    u.completion_tokens += ct
    u.cost_usd += (pt * pin + ct * pout) / 1_000_000
    u.estimated = u.estimated or est


def record_embed(model: str, tokens: int) -> None:
    u = _usage.get()
    if u is None:
        return
    pin, _ = _PRICES.get(model.split(":", 1)[-1], (0.0, 0.0))
    u.embed_tokens += tokens
    u.cost_usd += tokens * pin / 1_000_000
    u.estimated = True


# ----------------------------------------------------------------------------- embeddings
class Embedder:
    name: str = "base"
    dim: int = 0

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        raise NotImplementedError

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_documents([text])[0]


class HashEmbedder(Embedder):
    """Offline feature-hashing embedder (unigrams + bigrams). Lexical rather than truly semantic:
    good for development/tests and as a no-key fallback; use openai/gemini for real semantic recall."""

    def __init__(self, dim: int = 1024):
        self.dim = dim
        self.name = f"hash:v1:{dim}"

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        toks = tokenize(text)
        feats = toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]
        for f in feats:
            h = int.from_bytes(hashlib.blake2b(f.encode(), digest_size=8).digest(), "big")
            v[h % self.dim] += 1.0 if (h >> 63) & 1 else -1.0
        v = np.sign(v) * np.log1p(np.abs(v))
        n = np.linalg.norm(v)
        return v / n if n else v

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.vstack([self._vec(t) for t in texts])


def _post_json(url: str, *, headers: dict, payload: dict, timeout: float, retries: int = 3) -> dict:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            r = httpx.post(url, headers=headers, json=payload, timeout=timeout)
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(2**attempt)
                continue
            if r.status_code >= 400:
                raise ProviderError(f"Provider returned HTTP {r.status_code}: {r.text[:200]}")
            return r.json()
        except httpx.HTTPError as e:
            last = e
            if attempt < retries - 1:
                time.sleep(2**attempt)
    raise ProviderError(f"Provider request failed: {last}")


def _normalise(out: list[list[float]]) -> np.ndarray:
    arr = np.asarray(out, dtype=np.float32)
    if not arr.size:
        return arr
    return arr / np.maximum(np.linalg.norm(arr, axis=1, keepdims=True), 1e-9)


class OpenAIEmbedder(Embedder):
    def __init__(self, s: Settings):
        if not s.openai_api_key:
            raise ProviderError("OPENAI_API_KEY is not set")
        self.s, self.model = s, s.openai_embedding_model
        self.name = f"openai:{self.model}"

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        record_embed(self.name, sum(est_tokens(t) for t in texts))
        out: list[list[float]] = []
        for i in range(0, len(texts), self.s.embed_batch):
            batch = [t[:8000] or " " for t in texts[i : i + self.s.embed_batch]]
            data = _post_json(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {self.s.secret('openai_api_key')}"},
                payload={"model": self.model, "input": batch},
                timeout=self.s.llm_timeout,
            )
            out.extend(d["embedding"] for d in sorted(data["data"], key=lambda d: d["index"]))
        return _normalise(out)


class GeminiEmbedder(Embedder):
    def __init__(self, s: Settings):
        if not s.gemini_api_key:
            raise ProviderError("GEMINI_API_KEY is not set")
        self.s, self.model = s, s.gemini_embedding_model
        self.name = f"gemini:{self.model}"

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        record_embed(self.name, sum(est_tokens(t) for t in texts))
        out: list[list[float]] = []
        step = min(self.s.embed_batch, 100)
        for i in range(0, len(texts), step):
            batch = texts[i : i + step]
            data = _post_json(
                f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:batchEmbedContents",
                headers={"x-goog-api-key": self.s.secret('gemini_api_key')},
                payload={"requests": [{"model": f"models/{self.model}", "content": {"parts": [{"text": t[:8000] or " "}]}} for t in batch]},
                timeout=self.s.llm_timeout,
            )
            out.extend(e["values"] for e in data["embeddings"])
        return _normalise(out)


def make_embedder(s: Settings) -> Embedder:
    set_price_table(s.price_table)
    p = s.embedding_provider.lower()
    if p == "hash":
        return HashEmbedder()
    if p == "openai":
        return OpenAIEmbedder(s)
    if p == "gemini":
        return GeminiEmbedder(s)
    raise ProviderError(f"Unknown embedding provider '{s.embedding_provider}'")


# ----------------------------------------------------------------------------- LLM
class LLM:
    available = False
    name = "none"
    calls = 0

    def complete(self, system: str, user: str) -> str:
        raise ProviderError("No LLM provider configured")

    def describe_image(self, data: bytes, mime: str, prompt: str) -> str:
        raise ProviderError("No vision-capable LLM configured")

    def _meter(self, system: str, user: str, out: str, ptok: Optional[int] = None, ctok: Optional[int] = None) -> None:
        record_llm(self.name, ptok, ctok, system + user, out)


class OpenAILLM(LLM):
    available = True

    def __init__(self, s: Settings):
        if not s.openai_api_key:
            raise ProviderError("OPENAI_API_KEY is not set")
        self.s, self.name = s, f"openai:{s.openai_chat_model}"

    def complete(self, system: str, user: str) -> str:
        self.calls += 1
        data = _post_json(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.s.secret('openai_api_key')}"},
            payload={"model": self.s.openai_chat_model, "temperature": 0, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
            timeout=self.s.llm_timeout,
        )
        return data["choices"][0]["message"]["content"].strip()


    def describe_image(self, data: bytes, mime: str, prompt: str) -> str:
        import base64

        self.calls += 1
        uri = f"data:{mime};base64,{base64.b64encode(data).decode()}"
        out = _post_json(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.s.secret('openai_api_key')}"},
            payload={"model": self.s.openai_chat_model, "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": uri}}]}]},
            timeout=self.s.llm_timeout,
        )
        return out["choices"][0]["message"]["content"].strip()


class GeminiLLM(LLM):
    available = True

    def __init__(self, s: Settings):
        if not s.gemini_api_key:
            raise ProviderError("GEMINI_API_KEY is not set")
        self.s, self.name = s, f"gemini:{s.gemini_chat_model}"

    def complete(self, system: str, user: str) -> str:
        self.calls += 1
        data = _post_json(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.s.gemini_chat_model}:generateContent",
            headers={"x-goog-api-key": self.s.secret('gemini_api_key')},
            payload={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"temperature": 0},
            },
            timeout=self.s.llm_timeout,
        )
        try:
            out = "".join(p["text"] for p in data["candidates"][0]["content"]["parts"]).strip()
        except (KeyError, IndexError) as e:
            raise ProviderError(f"Unexpected Gemini response: {str(data)[:200]}") from e
        u = data.get("usageMetadata") or {}
        self._meter(system, user, out, u.get("promptTokenCount"), u.get("candidatesTokenCount"))
        return out


def _gemini_image(self, data: bytes, mime: str, prompt: str) -> str:
    import base64

    self.calls += 1
    out = _post_json(
        f"https://generativelanguage.googleapis.com/v1beta/models/{self.s.gemini_chat_model}:generateContent",
        headers={"x-goog-api-key": self.s.secret("gemini_api_key")},
        payload={"contents": [{"role": "user", "parts": [{"text": prompt}, {"inlineData": {"mimeType": mime, "data": base64.b64encode(data).decode()}}]}]},
        timeout=self.s.llm_timeout,
    )
    return "".join(p["text"] for p in out["candidates"][0]["content"]["parts"]).strip()


GeminiLLM.describe_image = _gemini_image


def make_llm(s: Settings) -> LLM:
    p = s.llm_provider.lower()
    if p in ("none", ""):
        return LLM()
    if p == "openai":
        return OpenAILLM(s)
    if p == "gemini":
        return GeminiLLM(s)
    raise ProviderError(f"Unknown LLM provider '{s.llm_provider}'")
