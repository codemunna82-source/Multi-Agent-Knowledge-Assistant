import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings
from app.learn import lab
from app.learn.catalog import LESSONS
from app.service import Knowledge

from .conftest import upload
from .fakes import FakeLLM

H = {"X-Session-ID": "s1"}
PW = "correct horse battery"


@pytest.fixture
def demo(client):
    r = client.post("/learn/demo-corpus", headers=H)
    assert r.status_code == 200
    return client


def test_catalog_covers_rag_langgraph_and_langchain_and_points_at_real_files():
    from pathlib import Path

    groups = {x["group"] for x in LESSONS}
    assert groups == {"RAG", "LangGraph", "LangChain"} and len({x["id"] for x in LESSONS}) == len(LESSONS) >= 25
    root = Path(__file__).resolve().parents[1]
    for x in LESSONS:
        first = x["code"].split(",")[0].split("::")[0].split(" (")[0].strip()
        assert (root / first).exists(), (x["id"], first)               # every lesson names a file that exists
        assert x["what"] and x["why"] and x["try"]["lab"] in ("retrieval", "graph", "langchain", "eval")


def test_lessons_endpoint_and_demo_corpus(client):
    j = client.get("/learn/lessons", headers=H).json()
    assert j["llm_available"] is False and "semantic only" in j["presets"] and len(j["ablation"]) == 9 and len(j["demo_questions"]) >= 6
    docs = client.post("/learn/demo-corpus", headers=H).json()["documents"]
    assert {d["name"] for d in docs} >= {"hr_policy.pdf", "company_handbook.md", "sales_q1.xlsx"} and all(d["status"] == "ready" for d in docs)
    again = client.post("/learn/demo-corpus", headers=H).json()["documents"]
    assert all(d["status"] == "duplicate" for d in again)                 # idempotent: identical files are not indexed twice


def test_compare_shows_per_setting_hits_grades_and_differences(demo):
    r = demo.post("/learn/retrieval/compare", json={"question": "Anjali Rao", "presets": ["semantic only", "keyword only (BM25)", "hybrid + compression"]}, headers=H).json()
    rows = {x["name"]: x for x in r["rows"]}
    assert rows["semantic only"]["delta"] is None and rows["keyword only (BM25)"]["delta"]["vs"] == "semantic only"
    assert rows["hybrid + compression"]["hits"][0]["source"] == "hr_policy.pdf" and rows["keyword only (BM25)"]["grade"] == "correct"
    assert any(t["step"] == "gate" for t in rows["semantic only"]["trace"]) and all("ms" in x for x in r["rows"])
    assert demo.post("/learn/retrieval/compare", json={"question": "x y", "presets": ["nope"]}, headers=H).status_code == 422


def test_ablation_adds_one_technique_at_a_time_and_compression_visibly_shrinks_context(demo):
    rows = demo.post("/learn/retrieval/ablation", json={"question": "How many weeks of parental leave do partners get?"}, headers=H).json()["rows"]
    assert [r["name"][:2] for r in rows] == [f"{i}." for i in range(1, 10)]
    assert rows[0]["overrides"] == {} and rows[1]["overrides"]["mode"] == "hybrid" and rows[-1]["overrides"]["corrective"] is True       # cumulative settings
    before, after = rows[6], rows[7]
    assert after["delta"]["chars_to_model_change"] < 0 and before["hits"][0]["chars_to_model"] > after["hits"][0]["chars_to_model"]    # compression: same passage, fewer characters sent
    assert after["hits"][0]["compressed"] is True and rows[0]["hits"][0]["compressed"] is False


def test_labs_say_when_a_step_needs_a_model(demo):
    rows = demo.post("/learn/retrieval/compare", json={"question": "annual leave", "presets": ["hybrid + HyDE", "hybrid + multi-query"]}, headers=H).json()["rows"]
    assert all(r["notes"] for r in rows)
    k = demo.app.state.knowledge
    k.llm = FakeLLM(lambda s, u: '{"queries": ["annual leave days", "vacation"]}')
    assert all(not r["notes"] for r in demo.post("/learn/retrieval/compare", json={"question": "annual leave", "presets": ["hybrid + HyDE"]}, headers=H).json()["rows"])


def test_graph_info_describes_the_compiled_langgraph(client):
    g = client.get("/learn/graph", headers=H).json()
    ids = {n["id"] for n in g["nodes"]}
    assert {"supervisor", "strategy", "semantic", "compare", "branch", "merge", "verify", "final", "__start__", "__end__"} <= ids
    edges = {(e["source"], e["target"]): e["conditional"] for e in g["edges"]}
    assert edges[("supervisor", "strategy")] is True and edges[("verify", "final")] is True and edges[("exact", "final")] is False and edges[("branch", "merge")] is False
    assert all(n["description"] for n in g["nodes"]) and g["mermaid"].lstrip().startswith("---") and "supervisor" in g["mermaid"]


def test_graph_run_reports_each_step_state_writes_and_checkpoints(demo):
    j = demo.post("/learn/graph/run", json={"question": "How many weeks of parental leave do partners get?", "retrieval": {"auto": True}}, headers=H).json()
    names = [s["node"] for s in j["steps"]]
    assert names[0] == "supervisor" and names[-1] == "final" and "verify" in names
    assert names.index("strategy") < names.index("semantic")                       # auto mode: pick the configuration, then answer (also after the data agent hands a non-table question over)
    by = {s["node"]: s for s in j["steps"]}
    assert by["strategy"]["summary"]["auto_strategy"]["chosen"] and "plan" in by["strategy"]["writes"] and by["semantic"]["summary"]["draft"]["citations"] >= 1
    assert by["verify"]["summary"]["verification"]["status"] == "pass" and all(s["ms"] >= 0 for s in j["steps"])
    assert j["response"]["route"] == "semantic" and j["checkpoints"] and j["checkpoints"][0]["step"] in (-1, 0)
    assert demo.get("/conversations", headers=H).json() == []                     # the learning run leaves nothing behind
    par = demo.post("/learn/graph/run", json={"question": 'How many times does "Anjali Rao" appear, and what is the highest sales?'}, headers=H).json()
    assert "branch" in [s["node"] for s in par["steps"]] and "merge" in [s["node"] for s in par["steps"]] and par["response"]["route"] == "parallel"


def test_langchain_lab_uses_real_langchain_core_objects(demo):
    j = demo.post("/learn/langchain", json={"question": 'What does the handbook say about "Anjali Rao"?'}, headers=H).json()
    assert j["retriever"]["documents"] and j["retriever"]["documents"][0]["source"]
    names = [s["name"] for s in j["chain"]["steps"]]
    assert {"MkaRetriever", "format_docs", "ChatPromptTemplate", "StrOutputParser"} <= set(names) and any(n.startswith("model(") for n in names)
    assert "Answer using ONLY the context" in j["chain"]["prompt"] and "[1]" in j["chain"]["answer"]
    t = j["tool"]
    assert t["term"] == "Anjali Rao" and "occurrence" in t["result"] and t["schema"]["type"] == "function" and t["schema"]["function"]["name"] == "exact_search"
    assert "term" in t["schema"]["function"]["parameters"]["properties"] and "validation error" in t["invalid_call_rejected"].lower()
    assert "supported" in j["parser"]["format_instructions"] and j["parser"]["parsed"]["supported"] is True and "Invalid json" in j["parser"]["malformed_output_error"]
    assert len(j["memory"]["messages"]) == 4 and len(j["memory"]["kept_by_window"]) == 2 and set(j["code"]) == {"retriever", "chain", "tool", "parser", "memory"}


def test_langchain_lab_calls_the_configured_model(tmp_path):
    seen = []
    s = Settings(data_dir=str(tmp_path / "d"), _env_file=None)
    c = TestClient(create_app(s, Knowledge(s, llm=FakeLLM(lambda sy, u: (seen.append((sy, u)) if "Answer using ONLY" in sy else None) or "Generated answer [1]"))))
    upload(c, "p.txt", b"Employees accrue 25 days of annual leave per year.")
    j = c.post("/learn/langchain", json={"question": "How many days of annual leave?"}, headers=H).json()
    assert j["llm_used"] is True and j["chain"]["answer"] == "Generated answer [1]" and seen and "Answer using ONLY the context" in seen[0][0] and "annual leave" in seen[0][0]
    assert any(st["name"] == "model(llm)" for st in j["chain"]["steps"])


def test_labs_need_documents_respect_isolation_and_roles(tmp_path):
    s = Settings(data_dir=str(tmp_path / "d"), auth_enabled=True, jwt_secret="x" * 40, rate_limit_ask="1000/minute", rate_limit_auth="1000/minute", rate_limit_ingest="1000/minute", _env_file=None)
    c = TestClient(create_app(s))
    assert c.get("/learn/lessons").status_code == 401
    adm = {"Authorization": "Bearer " + c.post("/auth/signup", json={"tenant_name": "Acme", "email": "a@acme.io", "password": PW}).json()["access_token"], **H}
    c.post("/admin/users", json={"email": "u@acme.io", "password": PW, "role": "user"}, headers=adm)
    usr = {"Authorization": "Bearer " + c.post("/auth/login", json={"email": "u@acme.io", "password": PW}).json()["access_token"], **H}
    assert c.post("/learn/retrieval/ablation", json={"question": "leave"}, headers=adm).status_code == 404            # nothing uploaded yet
    assert c.post("/learn/demo-corpus", headers=usr).status_code == 403                                           # loading documents needs the manager role
    assert c.post("/learn/demo-corpus", headers=adm).status_code == 200
    assert c.post("/learn/retrieval/compare", json={"question": "Anjali Rao", "presets": ["hybrid (RRF)"]}, headers=usr).status_code == 200      # users can run the labs
    other = {"Authorization": "Bearer " + c.post("/auth/signup", json={"tenant_name": "Beta", "email": "b@beta.io", "password": PW}).json()["access_token"], **H}
    assert c.post("/learn/langchain", json={"question": "Anjali Rao"}, headers=other).status_code == 404            # the other tenant sees none of Acme's documents


def test_every_preset_and_ablation_step_is_a_valid_option_set():
    from dataclasses import fields

    from app.rag.options import Resolved

    valid = {f.name for f in fields(Resolved)}
    for ov in [*lab.PRESETS.values(), *(a for _, a in lab.ABLATION), lab.BARE]:
        assert set(ov) <= valid
