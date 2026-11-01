"""ChatGPT-style streaming contract: status stages, cancellation on disconnect, timeout, regenerate, error handling, auth.
Provider behaviour is simulated with scripted LLMs - this tests OUR streaming plumbing, not a real provider."""
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings
from app.core import ProviderError
from app.service import Knowledge

from .conftest import upload
from .fakes import FakeLLM

H = {"X-Session-ID": "s1"}
DOC = b"Employees accrue 25 days of annual leave per year. " * 3
Q = {"question": "How many days of annual leave?"}


class Slow(FakeLLM):
    """Streams `pieces` pieces with `delay` seconds between them and counts how many were really produced."""

    def __init__(self, pieces=200, delay=0.02, text="Employees get 25 days of annual leave [1]. ", fail_after=None):
        super().__init__(lambda s, u: None)
        self.pieces, self.delay, self.text, self.fail_after = pieces, delay, text, fail_after
        self.produced = 0
        self.closed = threading.Event()

    def stream(self, system, user):
        try:
            if "Answer using ONLY" not in system and "Question:" not in user:
                yield self.complete(system, user)
                return
            for i in range(self.pieces):
                if self.fail_after is not None and i >= self.fail_after:
                    raise ProviderError("connection reset")
                time.sleep(self.delay)
                self.produced += 1
                yield self.text if i == 0 else "word "
        finally:
            self.closed.set()


def make(tmp_path, llm=None, **kw):
    s = Settings(data_dir=str(tmp_path / "d"), _env_file=None, **kw)
    k = Knowledge(s, llm=llm)
    c = TestClient(create_app(s, k))
    upload(c, "a.txt", DOC)
    return c, k


def events(c, body=None, headers=H, stop_after=None):
    ev, cur = [], None
    with c.stream("POST", "/ask/stream", json=body or Q, headers=headers) as r:
        assert r.status_code == 200, r.read()
        for line in r.iter_lines():
            if line.startswith("event:"):
                cur = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                ev.append((cur, json.loads(line.split(":", 1)[1])))
                if stop_after and len(ev) >= stop_after:
                    break                       # leaving the `with` block closes the connection = the browser's Stop button
    return ev


def test_status_events_report_real_stages_in_order_and_never_reasoning(tmp_path):
    c, k = make(tmp_path)
    ev = events(c)
    stages = [e[1]["stage"] for e in ev if e[0] == "status"]
    assert stages[0] == "understand" and "retrieve" in stages and stages.index("retrieve") < stages.index("verify")
    assert all(e[1]["label"] for e in ev if e[0] == "status") and ev[-1][0] == "done"
    assert not any(k_ in json.dumps(ev).lower() for k_ in ("chain-of-thought", "my reasoning"))


def test_rerank_and_grade_stages_come_from_the_pipeline_itself(tmp_path):
    c, k = make(tmp_path)
    stages = [e[1]["stage"] for e in events(c) if e[0] == "status"]
    assert "grade" in stages and "rerank" in stages and stages.index("grade") < stages.index("rerank")


def test_llm_answer_streams_while_generating_and_generate_stage_precedes_first_token(tmp_path):
    c, k = make(tmp_path, llm=Slow(pieces=10, delay=0.01))
    ev = events(c)
    kinds = [e[0] for e in ev]
    assert kinds.count("draft") >= 10 and kinds.index("draft") > [i for i, e in enumerate(ev) if e[0] == "status" and e[1]["stage"] == "generate"][0]
    # the scripted filler text is not supported by the sources, so verification replaces the draft with an extractive answer: final != draft is legitimate
    fin = ev[kinds.index("final")][1]["response"]
    assert fin["answer"].strip() and (fin["verified"] or fin["answer"].startswith("Most relevant passages"))


class Live:
    """A real uvicorn server on a free port: Starlette's TestClient never sends a disconnect, a real socket close does."""

    def __init__(self, tmp_path, llm):
        import socket

        import uvicorn

        s = Settings(data_dir=str(tmp_path / "d"), _env_file=None)
        self.k = Knowledge(s, llm=llm)
        self.app = create_app(s, self.k)
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        self.port = sock.getsockname()[1]
        sock.close()
        self.server = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=self.port, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        for _ in range(100):
            if self.server.started:
                break
            time.sleep(0.05)
        self.url = f"http://127.0.0.1:{self.port}"
        import httpx

        httpx.post(self.url + "/sources/upload", files=[("files", ("a.txt", DOC))], headers=H).raise_for_status()

    def stream(self, body=None, stop_after=None):
        import httpx

        ev, cur = [], None
        with httpx.Client(timeout=30) as cl, cl.stream("POST", self.url + "/ask/stream", json=body or Q, headers=H) as r:
            for line in r.iter_lines():
                if line.startswith("event:"):
                    cur = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    ev.append((cur, json.loads(line.split(":", 1)[1])))
                    if stop_after and len(ev) >= stop_after:
                        break                                   # leaving the block closes the socket = the browser's Stop button
        return ev

    def close(self):
        self.server.should_exit = True
        self.thread.join(5)


@pytest.fixture
def live(tmp_path):
    made = []

    def build(llm):
        lv = Live(tmp_path, llm)
        made.append(lv)
        return lv

    yield build
    for lv in made:
        lv.close()


def test_stop_cancels_generation_and_stores_nothing(live):
    llm = Slow(pieces=400, delay=0.02)                         # would take 8 s if left running
    lv = live(llm)
    ev = lv.stream(stop_after=12)                              # read statuses + first drafts, then disconnect
    t0 = time.time()
    assert llm.closed.wait(5), "provider stream was not abandoned after the client disconnected"
    produced = llm.produced
    time.sleep(0.3)
    assert llm.produced == produced < 400                      # generation really stopped, not just hidden
    import httpx

    assert httpx.get(lv.url + "/conversations", headers=H).json() == []      # a stopped answer is not stored, nor is an empty conversation left behind
    assert not any(e[0] == "final" for e in ev) and time.time() - t0 < 5


def test_new_question_after_stop_works(live):
    llm = Slow(pieces=200, delay=0.02)
    lv = live(llm)
    lv.stream(stop_after=10)
    llm.closed.wait(5)
    llm.pieces, llm.delay = 3, 0
    ev = lv.stream()
    assert ev[-1][0] == "done" and any(e[0] == "final" for e in ev)


def test_stream_timeout_ends_with_an_error_event(tmp_path):
    c, k = make(tmp_path, llm=Slow(pieces=500, delay=0.05), stream_timeout_s=0.6)
    ev = events(c)
    assert ev[-1][0] == "error" and "longer than" in ev[-1][1]["detail"] and not any(e[0] == "final" for e in ev)
    assert c.get("/conversations", headers=H).json() == []         # nothing stored, no empty conversation left


def test_provider_failure_mid_stream_degrades_or_reports_without_hanging(tmp_path):
    c, k = make(tmp_path, llm=Slow(pieces=50, delay=0.001, fail_after=5))
    ev = events(c)
    kinds = [e[0] for e in ev]
    assert kinds[-1] in ("done", "error") and ("final" in kinds or "error" in kinds)
    if "final" in kinds:        # degraded: the answer says so
        assert any("unavailable" in x.lower() or "extract" in x.lower() for x in ev[kinds.index("final")][1]["response"]["limitations"])


def test_empty_llm_response_still_gets_a_clear_final_answer(tmp_path):
    class Empty(Slow):
        def stream(self, system, user):
            if "Question:" in user:
                return iter(())
            return super().stream(system, user)

    c, k = make(tmp_path, llm=Empty())
    ev = events(c)
    fin = [e for e in ev if e[0] == "final"]
    assert fin and fin[0][1]["response"]["answer"].strip() and ev[-1][0] == "done"


def test_no_relevant_documents_gives_a_fallback_answer(tmp_path):
    c, k = make(tmp_path)
    ev = events(c, {"question": "What is the capital of Atlantis?"})
    fin = [e for e in ev if e[0] == "final"][0][1]["response"]
    assert fin["verified"] is False and fin["answer"].strip() and ev[-1][0] == "done"


def test_unknown_source_is_an_error_event_not_a_crash(tmp_path):
    c, k = make(tmp_path)
    ev = events(c, {"question": "x", "source_ids": ["0" * 32]})
    assert ev[-1][0] == "error" and ev[-1][1]["detail"]


def test_regenerate_replaces_the_last_exchange_only_after_success(tmp_path):
    c, k = make(tmp_path, llm=Slow(pieces=3, delay=0))
    first = [e for e in events(c) if e[0] == "final"][0][1]["response"]
    cid = first["conversation_id"]
    body = {**Q, "conversation_id": cid, "regenerate": True}
    assert len(c.get(f"/conversations/{cid}/messages", headers=H).json()) == 2
    events(c, body)
    msgs = c.get(f"/conversations/{cid}/messages", headers=H).json()
    assert [m["role"] for m in msgs] == ["user", "assistant"] and msgs[0]["content"] == Q["question"]          # replaced, not appended
    k.settings.stream_timeout_s = 0.3
    k.llm.pieces, k.llm.delay = 200, 0.02
    assert events(c, body)[-1][0] == "error"                                                                  # a failed regeneration keeps the old answer
    assert len(c.get(f"/conversations/{cid}/messages", headers=H).json()) == 2
    k.settings.stream_timeout_s = 300
    k.llm.pieces, k.llm.delay = 2, 0
    events(c, {**Q, "conversation_id": cid})                                                                  # an ordinary follow-up appends
    assert len(c.get(f"/conversations/{cid}/messages", headers=H).json()) == 4


def test_regenerate_does_not_delete_a_different_question(tmp_path):
    c, k = make(tmp_path, llm=Slow(pieces=2, delay=0))
    cid = [e for e in events(c) if e[0] == "final"][0][1]["response"]["conversation_id"]
    events(c, {"question": "Something else entirely?", "conversation_id": cid, "regenerate": True})
    assert len(c.get(f"/conversations/{cid}/messages", headers=H).json()) == 4


def test_streaming_keeps_authentication_and_validation(tmp_path):
    s = Settings(data_dir=str(tmp_path / "d"), auth_enabled=True, jwt_secret="x" * 40, rate_limit_ask="3/minute", rate_limit_auth="1000/minute", _env_file=None)
    c = TestClient(create_app(s))
    assert c.post("/ask/stream", json=Q, headers=H).status_code == 401
    tok = c.post("/auth/signup", json={"tenant_name": "Acme", "email": "a@a.io", "password": "correct horse battery"}).json()["access_token"]
    h = {**H, "Authorization": f"Bearer {tok}"}
    assert c.post("/ask/stream", json={"question": ""}, headers=h).status_code == 422
    codes = [c.post("/ask/stream", json=Q, headers=h).status_code for _ in range(5)]
    assert 429 in codes
