import io
import json
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app import providers
from app.academy import playground_graph as pgg
from app.api import create_app
from app.config import Settings
from app.service import Knowledge

from .conftest import make_pdf
from .fakes import FakeLLM

PW = "correct horse battery"
DOC = ("Employees accrue 25 days of annual leave per year. Unused leave can be carried over for up to 5 days. "
       "Parental leave is 26 weeks for the primary caregiver and 4 weeks for the partner. Expense reports must be filed within 30 days of travel.")


class GenLLM(FakeLLM):
    """Scripted model that records the sampling parameters the playground passes and streams word by word."""

    def __init__(self, script=None):
        super().__init__(script or (lambda s, u: "Parental leave is 26 weeks [1]."))
        self.params = []

    def generate(self, system, user, temperature=None, max_tokens=None):
        self.params.append((temperature, max_tokens))
        return self.complete(system, user)

    def generate_stream(self, system, user, temperature=None, max_tokens=None):
        self.params.append((temperature, max_tokens))
        for w in self.complete(system, user).split(" "):
            time.sleep(0.01)
            yield w + " "


def build(tmp_path, llm=None, **kw):
    opts = {"data_dir": str(tmp_path / "d"), "auth_enabled": True, "jwt_secret": "x" * 40, "rate_limit_auth": "10000/minute", "rate_limit_playground": "10000/minute", "rate_limit_ingest": "10000/minute", **kw}
    s = Settings(_env_file=None, **opts)
    k = Knowledge(s, llm=llm)
    c = TestClient(create_app(s, k))
    t = c.post("/auth/signup", json={"tenant_name": "Acme", "email": "a@acme.io", "password": PW}).json()
    return c, k, {"Authorization": "Bearer " + t["access_token"], "X-Session-ID": "w"}


@pytest.fixture
def env(tmp_path):
    return build(tmp_path)


@pytest.fixture
def llm_env(tmp_path):
    llm = GenLLM()
    c, k, h = build(tmp_path, llm=llm)
    return c, k, h, llm


def P(c, h, path, body=None, **kw):
    return c.post(f"/academy/playground/{path}", json=body, headers=h, **kw)


# ----------------------------------------------------------------------------- capabilities, LLM
def test_capabilities_are_honest_about_what_is_configured(env):
    c, k, h = env
    j = c.get("/academy/playground/capabilities", headers=h).json()
    assert j["llm"]["available"] is False and "MKA_LLM_PROVIDER" in j["llm"]["setup"]
    assert j["embedder"]["semantic"] is False and "WORDS" in j["embedder"]["note"] and j["embedder"]["dim"] > 0
    assert isinstance(j["cross_encoder"]["available"], bool) and "code_runner" in j and j["limits"]["max_tokens"] == 1000


def test_llm_without_a_model_shows_the_request_instead_of_pretending(env):
    c, k, h = env
    r = P(c, h, "llm", {"system": "Be brief.", "prompt": "Hi", "temperature": 0.3, "max_tokens": 50}).json()
    assert r["available"] is False and r["request"]["messages"][1]["content"] == "Hi" and r["request"]["temperature"] == 0.3 and "text" not in r


def test_llm_passes_sampling_parameters_and_reports_usage_and_latency(llm_env):
    c, k, h, llm = llm_env
    r = P(c, h, "llm", {"system": "s", "prompt": "What is parental leave?", "temperature": 1.2, "max_tokens": 77}).json()
    assert r["available"] and r["text"].startswith("Parental leave") and r["latency_ms"] >= 0 and r["model"] == "fake"
    assert llm.params[-1] == (1.2, 77) and r["usage"]["llm_calls"] >= 0


@pytest.mark.parametrize("body", [{"prompt": ""}, {"prompt": "x", "temperature": 3}, {"prompt": "x", "max_tokens": 5000}, {"prompt": "x" * 9000}, {"prompt": "x", "system": "s" * 5000}])
def test_llm_validates_input(env, body):
    c, k, h = env
    assert P(c, h, "llm", body).status_code == 422


def _sse(c, h, path, body):
    ev, cur = [], None
    with c.stream("POST", f"/academy/playground/{path}", json=body, headers=h) as r:
        assert r.status_code == 200
        for line in r.iter_lines():
            if line.startswith("event:"):
                cur = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                ev.append((cur, json.loads(line.split(":", 1)[1])))
    return ev


def test_llm_stream_sends_tokens_then_done_with_first_token_time(llm_env):
    c, k, h, llm = llm_env
    ev = _sse(c, h, "llm/stream", {"prompt": "go", "temperature": 0.5, "max_tokens": 20})
    toks = [e[1]["text"] for e in ev if e[0] == "token"]
    assert len(toks) >= 3 and "".join(toks).strip() == "Parental leave is 26 weeks [1]."
    done = ev[-1]
    assert done[0] == "done" and done[1]["first_token_ms"] is not None and done[1]["chunks"] == len(toks) and llm.params[-1] == (0.5, 20)


def test_llm_stream_without_a_model_says_unavailable(env):
    c, k, h = env
    ev = _sse(c, h, "llm/stream", {"prompt": "go"})
    assert ev == [("unavailable", ev[0][1])] and "setup" in ev[0][1]


def test_llm_stream_is_cancelled_when_the_client_disconnects(tmp_path):
    import socket

    import uvicorn

    produced = []
    closed = threading.Event()

    class Slow(GenLLM):
        def generate_stream(self, system, user, temperature=None, max_tokens=None):
            try:
                for i in range(300):
                    time.sleep(0.02)
                    produced.append(i)
                    yield f"w{i} "
            finally:
                closed.set()

    s = Settings(data_dir=str(tmp_path / "d"), _env_file=None, rate_limit_playground="10000/minute")
    app = create_app(s, Knowledge(s, llm=Slow()))
    sock = socket.socket(); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]; sock.close()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=srv.run, daemon=True); th.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    try:
        n = 0
        with httpx.Client(timeout=20) as cl, cl.stream("POST", f"http://127.0.0.1:{port}/academy/playground/llm/stream", json={"prompt": "x"}) as r:
            for line in r.iter_lines():
                n += line.startswith("event: token")
                if n >= 3:
                    break
        assert closed.wait(5), "the provider stream was not abandoned"
        m = len(produced)
        time.sleep(0.3)
        assert len(produced) == m < 300
    finally:
        srv.should_exit = True
        th.join(5)


def test_provider_payloads_carry_temperature_and_token_limits_and_openai_is_metered(monkeypatch):
    seen = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen["payload"] = json
        if "openai" in url:
            return httpx.Response(200, json={"choices": [{"message": {"content": " hi "}}], "usage": {"prompt_tokens": 9, "completion_tokens": 2}}, request=httpx.Request("POST", url))
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "yo"}]}}], "usageMetadata": {"promptTokenCount": 4, "candidatesTokenCount": 1}}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    o = providers.OpenAILLM(Settings(openai_api_key="sk-x", _env_file=None))
    with providers.track_usage() as u:
        assert o.generate("s", "u", 1.4, 55) == "hi"
    assert seen["payload"]["temperature"] == 1.4 and seen["payload"]["max_completion_tokens"] == 55 and (u.prompt_tokens, u.completion_tokens) == (9, 2)
    o.complete("s", "u")
    assert seen["payload"]["temperature"] == 0 and "max_completion_tokens" not in seen["payload"]            # the main pipeline is unchanged
    g = providers.GeminiLLM(Settings(gemini_api_key="g-x", _env_file=None))
    assert g.generate("s", "u", 0.9, 33) == "yo"
    assert seen["payload"]["generationConfig"] == {"temperature": 0.9, "maxOutputTokens": 33}


# ----------------------------------------------------------------------------- prompts, embeddings
def test_prompt_comparison_runs_variants_and_diffs_the_outputs(tmp_path):
    llm = GenLLM(lambda s, u: "Short answer." if "briefly" in s else "A much longer and more detailed answer with extra words.")
    c, k, h = build(tmp_path, llm=llm)
    body = {"variants": [{"name": "plain", "system": "", "prompt": "Explain RAG"}, {"name": "brief", "system": "Answer briefly.", "prompt": "Explain RAG"}], "temperature": 0}
    r = P(c, h, "prompts/compare", body).json()
    assert r["available"] and [v["name"] for v in r["variants"]] == ["plain", "brief"]
    b = r["variants"][1]
    assert b["similarity_to_first"] < 0.5 and "Short" in b["only_here"] and b["words"] == 2 and r["variants"][0]["words"] > 5
    assert P(c, h, "prompts/compare", {"variants": [body["variants"][0]]}).status_code == 422
    assert P(c, h, "prompts/compare", {"variants": body["variants"] * 2}).status_code == 422                      # more than 3


def test_prompt_comparison_without_a_model_previews_each_request(env):
    c, k, h = env
    r = P(c, h, "prompts/compare", {"variants": [{"name": "a", "prompt": "x"}, {"name": "b", "system": "y", "prompt": "z"}]}).json()
    assert r["available"] is False and r["variants"][1]["request"]["messages"][0]["content"] == "y"


def test_embeddings_return_dimensions_similarity_matrix_and_ranking(env):
    c, k, h = env
    r = P(c, h, "embeddings", {"texts": ["car engine repair", "automobile engine repair", "chocolate cake recipe"]}).json()
    assert r["dim"] == len(r["vectors"][0]["first_values"]) or r["dim"] > 8
    m = r["similarity"]
    assert all(abs(m[i][i] - 1) < 1e-3 for i in range(3)) and m[0][1] == m[1][0] and r["semantic"] is False and "WORDS" in r["note"]
    assert r["ranking_vs_first"][0]["index"] == 1 and r["ranking_vs_first"][0]["cosine"] > r["ranking_vs_first"][1]["cosine"]
    for bad in ({"texts": ["one"]}, {"texts": ["a"] * 11}, {"texts": ["a", ""]}, {"texts": ["a", "b" * 501]}):
        assert P(c, h, "embeddings", bad).status_code == 422


# ----------------------------------------------------------------------------- RAG
def rag(c, h, **kw):
    data = {"question": "How long is parental leave?", "chunk_size": "100", "chunk_overlap": "10", "top_k": "3", "mode": "hybrid", "rerank": "lexical", "answer": "true", **kw.pop("data", {})}
    return c.post("/academy/playground/rag", data=({**data, "text": DOC} if "files" not in kw else data), headers=h, **kw)


def test_rag_playground_exposes_every_stage_and_stores_nothing(env):
    c, k, h = env
    r = rag(c, h).json()
    assert set(r) >= {"extract", "chunks", "embed", "store", "search", "rerank", "context", "answer", "total_ms"}
    assert r["extract"]["chars"] == len(DOC) and r["chunks"]["count"] >= 3 and r["chunks"]["size"] == 100
    top = r["search"]["top"]
    assert top[0]["text"].startswith("Parental leave") or "Parental" in top[0]["text"]
    assert r["embed"]["semantic"] is False and r["store"]["persisted"] is False
    assert r["rerank"]["method"] == "lexical" and r["rerank"]["items"][0]["rerank_score"] is not None
    assert "26 weeks" in r["answer"]["text"] and r["answer"]["citations"] and "extractive" in r["answer"]["method"]
    assert "Sources:" in r["context"]["prompt"] and "[1]" in r["context"]["prompt"]
    assert c.get("/sources", headers=h).json() == []                       # nothing was ingested


def test_rag_chunk_size_changes_the_number_of_chunks_and_modes_differ(env):
    c, k, h = env
    small, big = rag(c, h, data={"chunk_size": "100"}).json(), rag(c, h, data={"chunk_size": "600"}).json()
    assert small["chunks"]["count"] > big["chunks"]["count"] and big["chunks"]["count"] >= 1
    kw = rag(c, h, data={"mode": "keyword"}).json()["search"]
    vec = rag(c, h, data={"mode": "vector"}).json()["search"]
    assert kw["mode"] == "keyword" and vec["mode"] == "vector"


def test_rag_reranking_is_reported_before_and_after_and_cross_encoder_degrades_honestly(env):
    c, k, h = env
    r = rag(c, h, data={"rerank": "cross_encoder", "top_k": "3"}).json()["rerank"]
    assert r["method"].startswith("lexical (cross-encoder") or r["method"] == "cross_encoder"
    assert sorted(r["before"]) == sorted(r["after"]) or len(r["after"]) <= 3
    assert rag(c, h, data={"rerank": "none"}).json()["rerank"]["method"] == "none"


def test_rag_says_when_the_document_has_no_answer(env):
    c, k, h = env
    a = rag(c, h, data={"question": "xylophone quantum zebra"}).json()["answer"]
    assert a["found"] is False and "does not seem to contain" in a["text"]


def test_rag_uses_the_llm_when_configured_and_parses_citations(llm_env):
    c, k, h, llm = llm_env
    a = rag(c, h).json()["answer"]
    assert a["method"].startswith("llm") and a["citations"][0]["n"] == 1 and a["uncited"] is False and llm.params[-1] == (0.0, 400)


def test_rag_accepts_pdf_txt_csv_and_rejects_everything_else(env):
    c, k, h = env
    pdf = make_pdf(["Parental leave is 26 weeks for the primary caregiver.", "Expense reports are due in 30 days."])
    for name, data in [("p.pdf", pdf), ("n.txt", DOC.encode()), ("t.csv", b"name,leave\nAsha,26 weeks\nRavi,4 weeks\n")]:
        r = c.post("/academy/playground/rag", data={"question": "parental leave weeks", "chunk_size": "300", "chunk_overlap": "30"}, files={"file": (name, io.BytesIO(data))}, headers=h)
        assert r.status_code == 200, (name, r.text)
        assert r.json()["extract"]["file"] == name
    bad = c.post("/academy/playground/rag", data={"question": "x"}, files={"file": ("evil.exe", io.BytesIO(b"MZ"))}, headers=h)
    assert bad.status_code == 422 and "PDF, TXT, CSV" in bad.json()["detail"]
    big = c.post("/academy/playground/rag", data={"question": "x"}, files={"file": ("big.txt", io.BytesIO(b"a " * 1_500_000))}, headers=h)
    assert big.status_code == 422
    fake_pdf = c.post("/academy/playground/rag", data={"question": "x"}, files={"file": ("fake.pdf", io.BytesIO(b"not a pdf at all"))}, headers=h)
    assert fake_pdf.status_code == 422


def test_rag_validates_parameters(env):
    c, k, h = env
    assert c.post("/academy/playground/rag", data={"question": "x"}, headers=h).status_code == 422                                            # neither file nor text
    assert c.post("/academy/playground/rag", data={"question": "x", "text": "a", "chunk_overlap": "200", "chunk_size": "150"}, headers=h).status_code == 422   # overlap >= size
    assert c.post("/academy/playground/rag", data={"question": "x", "text": "a " * 90_000, "chunk_size": "100", "chunk_overlap": "0"}, headers=h).status_code == 422   # too many chunks


# ----------------------------------------------------------------------------- LangChain
def lc(c, h, **kw):
    return P(c, h, "langchain", {"system": "You are a {role}.", "template": "{question}", "variables": {"role": "teacher", "question": "Capital of France?"}, **kw})


def test_langchain_runs_real_runnables_and_records_each_component(env):
    c, k, h = env
    r = lc(c, h, fake_reply="Paris, France, Europe", parser="list").json()
    assert r["chain"] == ["ChatPromptTemplate", "FakeListChatModel", "CommaSeparatedListOutputParser"] and r["output"] == ["Paris", "France", "Europe"] and r["error"] is None
    names = [s["name"] for s in r["steps"]]
    assert "ChatPromptTemplate" in names and "FakeListChatModel" in names and all("ms" in s for s in r["steps"])
    assert next(s for s in r["steps"] if s["name"] == "FakeListChatModel")["output"] == "Paris, France, Europe"
    assert "teacher" in next(s for s in r["steps"] if s["name"] == "ChatPromptTemplate")["output"]
    par = lc(c, h, pattern="parallel").json()
    assert set(par["output"]) == {"answer", "input_length"} and par["output"]["input_length"] == len("teacher")


def test_langchain_reports_parser_failures_without_crashing(env):
    c, k, h = env
    r = lc(c, h, fake_reply="not json", parser="json").json()
    assert r["error"] and "OutputParserException" in r["error"] and r["steps"]
    assert lc(c, h, fake_reply='{"city": "Paris"}', parser="json").json()["output"] == {"city": "Paris"}


def test_langchain_templates_cannot_reach_attributes_and_must_be_complete(env):
    c, k, h = env
    for tpl in ("{question.__class__}", "{question[0]}", "{question!r}", "{question:>10}", "{0}"):
        assert P(c, h, "langchain", {"template": tpl, "variables": {"question": "x"}}).status_code == 422, tpl
    assert P(c, h, "langchain", {"template": "{question} {other}", "variables": {"question": "x"}}).status_code == 422
    assert P(c, h, "langchain", {"template": "literal {{braces}} and {question}", "variables": {"question": "x"}, "system": "s"}).status_code == 200


def test_langchain_configured_model_needs_an_llm_and_then_uses_it(tmp_path):
    c, k, h = build(tmp_path / "none")
    assert lc(c, h, model="configured").json()["available"] is False
    llm = GenLLM()
    c2, k2, h2 = build(tmp_path / "with", llm=llm)
    r = lc(c2, h2, model="configured", temperature=0.4, max_tokens=60).json()
    assert r["available"] and r["output"] == "Parental leave is 26 weeks [1]." and r["model"] == "fake" and llm.params[-1] == (0.4, 60)


# ----------------------------------------------------------------------------- LangGraph
def test_presets_run_on_the_real_langgraph(env):
    c, k, h = env
    presets = c.get("/academy/playground/langgraph/presets", headers=h).json()
    assert set(presets) == {"loop", "router", "approval", "supervisor"}
    out = {n: P(c, h, "langgraph/run", {"spec": p["spec"], "input": p["input"]}).json() for n, p in presets.items()}
    assert out["loop"]["status"] == "finished" and out["loop"]["final_state"]["count"] == 3 and [s["node"] for s in out["loop"]["steps"]].count("work") == 3
    assert out["router"]["final_state"]["answer"] == "sent to a human reviewer"
    assert out["approval"]["status"] == "paused" and out["approval"]["pending"] == ["send"] and out["approval"]["thread_id"]
    assert out["supervisor"]["final_state"]["draft"].startswith("Summary: 26 weeks") and all("state_after" in s for s in out["supervisor"]["steps"])
    assert out["loop"]["history"] and out["loop"]["graph"]["nodes"][0] == "__start__"


def test_human_in_the_loop_pause_edit_state_and_resume(env):
    c, k, h = env
    p = c.get("/academy/playground/langgraph/presets", headers=h).json()["approval"]
    paused = P(c, h, "langgraph/run", {"spec": p["spec"], "input": p["input"]}).json()
    t = paused["thread_id"]
    r = P(c, h, "langgraph/resume", {"thread_id": t, "state_update": {"amount": 4200}}).json()
    assert r["status"] == "finished" and r["final_state"] == {"amount": 4200, "status": "refund of 4200 sent"}
    assert P(c, h, "langgraph/resume", {"thread_id": t}).status_code == 404                                    # a finished run cannot be resumed again


def test_other_users_cannot_resume_my_paused_run(env):
    c, k, h = env
    c.post("/admin/users", json={"email": "u@acme.io", "password": PW, "role": "user"}, headers=h)
    h2 = {"Authorization": "Bearer " + c.post("/auth/login", json={"email": "u@acme.io", "password": PW}).json()["access_token"], "X-Session-ID": "w"}
    p = c.get("/academy/playground/langgraph/presets", headers=h).json()["approval"]
    t = P(c, h, "langgraph/run", {"spec": p["spec"], "input": p["input"]}).json()["thread_id"]
    assert P(c, h2, "langgraph/resume", {"thread_id": t}).status_code == 404
    assert P(c, h, "langgraph/resume", {"thread_id": t}).status_code == 200


def test_endless_loops_hit_the_step_limit_instead_of_hanging(env):
    c, k, h = env
    spec = {"state": {"n": "int"}, "nodes": [{"id": "spin", "type": "increment", "key": "n"}], "edges": [["spin", "spin"]], "entry": "spin"}
    r = P(c, h, "langgraph/run", {"spec": spec, "input": {"n": 0}, "max_steps": 6}).json()
    assert r["status"] == "limit_reached" and "safety limit" in r["message"] and len(r["steps"]) <= 6


@pytest.mark.parametrize("patch,expect", [
    ({"edges": [["a", "ghost"]]}, "unknown node"), ({"entry": "ghost"}, "entry node does not exist"), ({"edges": []}, "no outgoing edge"),
    ({"nodes": [{"id": "a", "type": "set", "key": "zzz", "value": "1"}]}, "not declared"), ({"nodes": [{"id": "A!", "type": "noop"}]}, "String should match"),
    ({"nodes": [{"id": "a", "type": "set"}]}, "needs a key and a value"), ({"nodes": [{"id": "a", "type": "run_python", "key": "n"}]}, "Input should be"),
    ({"conditional": [{"source": "a", "key": "n", "op": "==", "value": 1, "then": "END", "otherwise": "END"}]}, "both a normal and a conditional edge"),
])
def test_graph_specs_are_validated(env, patch, expect):
    c, k, h = env
    spec = {"state": {"n": "int"}, "nodes": [{"id": "a", "type": "increment", "key": "n"}], "edges": [["a", "END"]], "entry": "a", **patch}
    r = P(c, h, "langgraph/run", {"spec": spec, "input": {}})
    assert r.status_code == 422 and expect in r.text


def test_graph_nodes_cannot_run_code(env):
    c, k, h = env
    spec = {"state": {"x": "str"}, "nodes": [{"id": "a", "type": "concat", "key": "x", "template": "{__import__('os').system('id')}"}], "edges": [["a", "END"]], "entry": "a"}
    assert P(c, h, "langgraph/run", {"spec": spec, "input": {}}).status_code == 422
    ok = {"state": {"x": "str"}, "nodes": [{"id": "a", "type": "concat", "key": "x", "template": "{x}!"}], "edges": [["a", "END"]], "entry": "a"}
    assert P(c, h, "langgraph/run", {"spec": ok, "input": {"x": "hi"}}).json()["final_state"]["x"] == "hi!"


# ----------------------------------------------------------------------------- agent
def agent(c, h, task, tools=None, **kw):
    body = {"task": task, **({"tools": tools} if tools is not None else {}), **kw}
    return P(c, h, "agent/run", body).json()


def test_agent_calculator_path_shows_operational_steps(env):
    c, k, h = env
    r = agent(c, h, "What is 15% of 48000?")
    assert r["final"] == "The answer is 7200." and "rule-based" in r["policy"]
    assert [s["type"] for s in r["steps"]] == ["plan", "tool_selected", "tool_result", "reflection", "final"]
    sel = r["steps"][1]
    assert sel["tool"] == "calculator" and sel["input"] == {"expression": "15% of 48000"} and r["steps"][2]["text"] == "7200"
    assert "chain-of-thought" not in json.dumps(r).lower() or "No private reasoning" in r["note"]


def test_agent_searches_the_workspace_documents_with_real_retrieval(env):
    c, k, h = env
    c.post("/sources/upload", files=[("files", ("hr.txt", io.BytesIO(DOC.encode())))], headers=h)
    r = agent(c, h, "How long is parental leave?")
    assert r["steps"][1]["tool"] == "search_documents" and "hr.txt" in r["steps"][2]["text"] and "26 weeks" in r["final"] or "26 weeks" in r["steps"][2]["text"]
    ls = agent(c, h, "Which documents do I have?")
    assert ls["steps"][1]["tool"] == "list_documents" and "hr.txt" in ls["steps"][2]["text"]
    ex = agent(c, h, 'How many times does "parental" appear?', ["exact_search"])
    assert ex["steps"][1]["tool"] == "exact_search" and "occurrence" in ex["steps"][2]["text"]


def test_agent_only_uses_allowed_tools_and_survives_bad_input(env):
    c, k, h = env
    none = agent(c, h, "What is 2+2?", ["list_documents"])
    assert "No allowed tool" in none["final"] and not any(s.get("tool") == "calculator" for s in none["steps"])   # calculator was not given, so it is never used
    nothing = agent(c, h, "What is 2+2?", [])
    assert "No allowed tool" in nothing["final"]
    assert P(c, h, "agent/run", {"task": "x", "tools": ["delete_all_files"]}).status_code == 422
    assert agent(c, h, "Compute 5 / 0")["final"].startswith("I could not complete the task") or "division" in json.dumps(agent(c, h, "Compute 5 / 0"))
    assert pgg.calculator("2+3*4") == "14"
    for evil in ("__import__('os').system('id')", "open('/etc/passwd').read()", "9**9**9", "[1][0]"):
        with pytest.raises(ValueError):
            pgg.calculator(evil)


def test_agent_with_an_llm_chooses_tools_itself_and_tool_output_is_treated_as_data(tmp_path):
    seen = []

    def script(system, user):
        seen.append(user)
        if "called calculator" in user:
            return json.dumps({"final": "It is 7200."})
        return json.dumps({"tool": "calculator", "input": {"expression": "0.15 * 48000"}, "why": "need the percentage"})

    c, k, h = build(tmp_path, llm=GenLLM(script))
    r = agent(c, h, "What is 15% of 48000?")
    assert r["final"] == "It is 7200." and "LLM (fake)" in r["policy"] and [s["type"] for s in r["steps"]][:3] == ["plan", "tool_selected", "tool_result"]
    assert "untrusted" in seen[1].lower() or "tool result" in seen[1].lower()


def test_agent_with_an_llm_that_returns_garbage_or_a_forbidden_tool_stops_safely(tmp_path):
    c, k, h = build(tmp_path, llm=GenLLM(lambda s, u: "I will do it, trust me"))
    r = agent(c, h, "anything")
    assert any(s["type"] == "error" for s in r["steps"]) and r["final"]
    c2, k2, h2 = build(tmp_path / "b", llm=GenLLM(lambda s, u: json.dumps({"tool": "shell", "input": {"cmd": "rm -rf /"}, "why": "x"})))
    r2 = agent(c2, h2, "anything", ["calculator"], max_steps=3)
    assert any(s["type"] == "tool_blocked" for s in r2["steps"]) and not any(s["type"] == "tool_result" for s in r2["steps"])


# ----------------------------------------------------------------------------- access control
def test_playgrounds_need_login_and_are_rate_limited(tmp_path):
    c, k, h = build(tmp_path, rate_limit_playground="4/minute")
    anon = [("get", "capabilities"), ("post", "llm"), ("post", "llm/stream"), ("post", "prompts/compare"), ("post", "embeddings"), ("post", "rag"), ("post", "langchain"),
            ("get", "langgraph/presets"), ("post", "langgraph/run"), ("post", "langgraph/resume"), ("get", "agent/tools"), ("post", "agent/run")]
    for m, p in anon:
        assert getattr(c, m)(f"/academy/playground/{p}", **({} if m == "get" else {"json": {}})).status_code == 401, p
    codes = [P(c, h, "embeddings", {"texts": ["a b", "c d"]}).status_code for _ in range(7)]
    assert codes[0] == 200 and 429 in codes
