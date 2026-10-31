"""Provider token streaming: SSE parsing is tested against httpx.MockTransport (no network, no keys). What this proves is OUR parsing,
metering, fallback and verification behaviour - not the quality or latency of a real provider."""
import json

import httpx
import pytest

from app import providers
from app.config import Settings
from app.core import ProviderError

from .fakes import FakeLLM
from .test_agents import H, app_with, upload


def _client_for(handler):
    return lambda timeout: httpx.Client(transport=httpx.MockTransport(handler), timeout=timeout)


def _sse(*events, done=True):
    body = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + ("data: [DONE]\n\n" if done else "")
    return httpx.Response(200, content=body.encode(), headers={"content-type": "text/event-stream"})


def test_openai_stream_yields_deltas_and_meters_usage(monkeypatch):
    seen = {}

    def handler(req):
        seen["payload"] = json.loads(req.content)
        return _sse({"choices": [{"delta": {"role": "assistant"}}]}, {"choices": [{"delta": {"content": "Hel"}}]}, {"choices": [{"delta": {"content": "lo"}}]},
                    {"choices": [], "usage": {"prompt_tokens": 11, "completion_tokens": 2}})

    monkeypatch.setattr(providers, "_http_client", _client_for(handler))
    llm = providers.OpenAILLM(Settings(openai_api_key="sk-test", _env_file=None))
    with providers.track_usage() as u:
        assert list(llm.stream("sys", "usr")) == ["Hel", "lo"]
    assert seen["payload"]["stream"] is True and u.prompt_tokens == 11 and u.completion_tokens == 2


def test_gemini_stream_yields_text_parts(monkeypatch):
    def handler(req):
        assert "streamGenerateContent" in str(req.url) and req.headers["x-goog-api-key"] == "g-test"
        return _sse({"candidates": [{"content": {"parts": [{"text": "Ab"}]}}]}, {"candidates": [{"content": {"parts": [{"text": "cd"}]}}], "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 2}}, done=False)

    monkeypatch.setattr(providers, "_http_client", _client_for(handler))
    llm = providers.GeminiLLM(Settings(gemini_api_key="g-test", _env_file=None))
    with providers.track_usage() as u:
        assert "".join(llm.stream("s", "u")) == "Abcd"
    assert u.prompt_tokens == 5 and u.completion_tokens == 2


def test_stream_http_errors_and_garbage_lines(monkeypatch):
    monkeypatch.setattr(providers, "_http_client", _client_for(lambda r: httpx.Response(429, text="slow down")))
    llm = providers.OpenAILLM(Settings(openai_api_key="sk-test", _env_file=None))
    with pytest.raises(ProviderError, match="429"):
        list(llm.stream("s", "u"))
    raw = b': keep-alive\n\ndata: not-json\n\ndata: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n'
    monkeypatch.setattr(providers, "_http_client", _client_for(lambda r: httpx.Response(200, content=raw)))
    assert list(llm.stream("s", "u")) == ["ok"]


def test_base_llm_stream_falls_back_to_one_piece():
    assert list(FakeLLM(lambda s, u: "whole answer").stream("s", "u")) == ["whole answer"]


class StreamingFake(FakeLLM):
    def stream(self, system, user):
        out = self.complete(system, user)
        for i in range(0, len(out), 5):
            yield out[i:i + 5]


def _events(c, body):
    with c.stream("POST", "/ask/stream", json=body, headers=H) as r:
        ev, cur = [], None
        for line in r.iter_lines():
            if line.startswith("event:"):
                cur = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                ev.append((cur, json.loads(line.split(":", 1)[1])))
    return ev


def test_endpoint_streams_draft_tokens_then_verified_final(tmp_path):
    def script(sy, u):
        return "Employees get 25 days of annual leave per year [1]." if "Answer using ONLY" in sy or "Question:" in u else None

    c, k, s = app_with(tmp_path, llm=StreamingFake(script))
    upload(c, "a.txt", b"Employees accrue 25 days of annual leave per year. " * 3)
    ev = _events(c, {"question": "How many days of annual leave?"})
    kinds = [e[0] for e in ev]
    drafts = "".join(e[1]["text"] for e in ev if e[0] == "draft")
    assert kinds[-1] == "final" and "draft" in kinds and "token" not in kinds         # real tokens replace the re-chunked fallback
    assert kinds.index("draft") > kinds.index("step") and drafts.startswith("Employees get 25 days")
    assert ev[-1][1]["response"]["verified"] is True


def test_extractive_answers_still_use_token_fallback(tmp_path):
    c, k, s = app_with(tmp_path)                       # no LLM configured
    upload(c, "a.txt", b"Employees accrue 25 days of annual leave per year. " * 3)
    kinds = [e[0] for e in _events(c, {"question": "How many days of annual leave?"})]
    assert "token" in kinds and "draft" not in kinds and kinds[-1] == "final"


def test_stream_worker_errors_surface_as_error_event(tmp_path):
    c, k, s = app_with(tmp_path, llm=StreamingFake(lambda s, u: None))
    upload(c, "a.txt", b"Employees accrue 25 days of annual leave per year. " * 3)
    k.llm.stream = lambda s, u: (_ for _ in ()).throw(ProviderError("boom"))
    ev = _events(c, {"question": "How many days of annual leave?"})
    assert ev[-1][0] in ("final", "error")              # a failing provider degrades to extraction (final) or reports an error - never hangs
