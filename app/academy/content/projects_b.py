from .projects_kit import DEPLOY_COMMON, KIT, P

REQ = "fastapi\nuvicorn\nhttpx\npytest\npydantic\n"
REQ_LG = REQ + "langgraph\n"


def api_test(title, path, body):
    return {"title": title, "command": f"curl -X POST http://127.0.0.1:8000{path} -H 'Content-Type: application/json' -d '{body}'"}


PROJECTS_B = [
    P(id="tool-assistant", title="AI Assistant with Tool Calling", level="intermediate", hours=3, stack=["Python", "FastAPI", "Pydantic", "Tool registry", "Allow-list"], prereq=["function-calling", "tools-structured-output"],
      summary="An assistant that picks a tool, validates its arguments, runs it safely and explains the result. The model only proposes; your code decides.",
      architecture={"nodes": ["User message", "Planner (rules or LLM)", "Tool registry", "Argument validation", "Tool", "Reply"],
                    "edges": [["User message", "Planner (rules or LLM)"], ["Planner (rules or LLM)", "Tool registry"], ["Tool registry", "Argument validation"], ["Argument validation", "Tool"], ["Tool", "Reply"]]},
      folders="tool-assistant/\n├── core.py         # tools, registry, planner, run()\n├── app.py          # POST /assist\n├── test_app.py\n└── requirements.txt",
      steps=[{"title": "Install requirements", "detail": "FastAPI for the API, Pydantic for argument validation.", "file": "requirements.txt"},
             {"title": "Define tools with typed arguments", "detail": "Each tool is a small function plus a Pydantic model describing its arguments. The calculator uses `ast`, never `eval`, so it cannot run arbitrary code.", "file": "core.py"},
             {"title": "Add the planner", "detail": "A rule-based planner returns `{tool, args}` exactly like a model's function call would. Swap it for an LLM later; the validation below stays.", "file": "core.py"},
             {"title": "Expose the API", "detail": "`/assist` runs the plan, returns the answer and the tool trace.", "file": "app.py"},
             {"title": "Test the unsafe paths", "detail": "Unknown tools, bad arguments and code injection attempts must be refused.", "file": "test_app.py"}],
      files={"requirements.txt": REQ, "core.py": '''import ast
import operator
import re
from datetime import date

from pydantic import BaseModel, Field, ValidationError

OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg}


def safe_eval(expr):
    def go(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in OPS:
            a, b = go(n.left), go(n.right)
            if isinstance(n.op, ast.Pow) and abs(b) > 10:
                raise ValueError("exponent too large")
            return OPS[type(n.op)](a, b)
        if isinstance(n, ast.UnaryOp) and type(n.op) in OPS:
            return OPS[type(n.op)](go(n.operand))
        raise ValueError("only numbers and + - * / ** are allowed")
    return go(ast.parse(expr, mode="eval").body)


class CalcArgs(BaseModel):
    expression: str = Field(min_length=1, max_length=100)


class ConvertArgs(BaseModel):
    value: float
    unit: str = Field(pattern="^(km_to_miles|miles_to_km|c_to_f|f_to_c)$")


class DateArgs(BaseModel):
    pass


FACTORS = {"km_to_miles": lambda v: v * 0.621371, "miles_to_km": lambda v: v / 0.621371, "c_to_f": lambda v: v * 9 / 5 + 32, "f_to_c": lambda v: (v - 32) * 5 / 9}
TOOLS = {
    "calculator": (CalcArgs, lambda a: safe_eval(a.expression)),
    "convert": (ConvertArgs, lambda a: round(FACTORS[a.unit](a.value), 3)),
    "today": (DateArgs, lambda a: date.today().isoformat()),
}


def plan(message):
    """What an LLM function call would return: a tool name and raw arguments."""
    m = message.lower()
    nums = re.findall(r"-?\\d+(?:\\.\\d+)?", m)
    if "today" in m and "date" in m:
        return {"tool": "today", "args": {}}
    for unit, words in (("km_to_miles", ("km", "miles")), ("c_to_f", ("celsius", "fahrenheit"))):
        if nums and words[0] in m and words[1] in m:
            return {"tool": "convert", "args": {"value": float(nums[0]), "unit": unit}}
    expr = re.findall(r"[0-9+\\-*/(). ]{3,}", message)
    if expr:
        return {"tool": "calculator", "args": {"expression": expr[0].strip()}}
    return {"tool": None, "args": {}}


def run(call):
    """The model proposes, this function decides: allow-list, validate, execute, never trust."""
    name = call.get("tool")
    if name is None:
        return {"ok": False, "error": "no tool needed or understood"}
    if name not in TOOLS:
        return {"ok": False, "error": f"tool {name!r} is not allowed"}
    model, fn = TOOLS[name]
    try:
        args = model(**call.get("args", {}))
        return {"ok": True, "tool": name, "result": fn(args)}
    except ValidationError as e:
        return {"ok": False, "tool": name, "error": "invalid arguments: " + e.errors()[0]["msg"]}
    except (ValueError, SyntaxError, ZeroDivisionError) as e:
        return {"ok": False, "tool": name, "error": str(e)}


def assist(message):
    call = plan(message)
    out = run(call)
    reply = f"{call['tool']} returned {out['result']}" if out["ok"] else f"I could not do that: {out['error']}"
    return {"reply": reply, "trace": {"call": call, "outcome": out}}
''', "app.py": '''from fastapi import FastAPI
from pydantic import BaseModel, Field

from core import assist

app = FastAPI(title="Tool assistant")


class Msg(BaseModel):
    message: str = Field(min_length=1, max_length=300)


@app.post("/assist")
def assist_endpoint(body: Msg):
    return assist(body.message)
''', "test_app.py": '''from fastapi.testclient import TestClient

from app import app
from core import run

client = TestClient(app)


def ask(m):
    return client.post("/assist", json={"message": m}).json()


def test_calculator_and_conversion():
    assert "returned 14" in ask("what is 2 + 3 * 4")["reply"]
    assert "62.137" in ask("convert 100 km to miles")["reply"]


def test_code_injection_is_not_evaluated():
    out = run({"tool": "calculator", "args": {"expression": "__import__('os').system('id')"}})
    assert out["ok"] is False


def test_unknown_tool_and_bad_arguments_are_refused():
    assert "not allowed" in run({"tool": "delete_everything", "args": {}})["error"]
    assert "invalid arguments" in run({"tool": "convert", "args": {"value": "abc", "unit": "km_to_miles"}})["error"]
    assert run({"tool": "convert", "args": {"value": 1, "unit": "rm -rf"}})["ok"] is False


def test_huge_exponent_and_division_by_zero_are_handled():
    assert run({"tool": "calculator", "args": {"expression": "9**9**9"}})["ok"] is False
    assert run({"tool": "calculator", "args": {"expression": "1/0"}})["ok"] is False
'''},
      api_tests=[api_test("Calculator", "/assist", '{"message": "what is 2 + 3 * 4"}'), api_test("Conversion", "/assist", '{"message": "convert 100 km to miles"}')],
      deploy=DEPLOY_COMMON, interview="Tool calling is a contract: the model returns a tool name and arguments as data, and my code decides what runs. I keep an allow-list of tools, validate arguments with Pydantic, use ast instead of eval for the calculator, cap resource use (for example exponents), and return errors as normal results so the model can recover. Tools that touch private data take the authenticated user from the session, never from model text, and every call is logged."),

    P(id="research-agent", title="LangGraph Research Agent", level="advanced", hours=4, stack=["Python", "LangGraph", "FastAPI", "Local corpus search"], prereq=["graph-state-nodes", "reflection-planning"],
      summary="A graph with plan, search, draft and check nodes. If the check fails, the graph loops back with a better query; a hard step limit prevents infinite loops.",
      architecture={"nodes": ["plan", "search", "draft", "check", "END"],
                    "edges": [["plan", "search"], ["search", "draft"], ["draft", "check"], ["check", "search"], ["check", "END"]]},
      folders="research-agent/\n├── kit.py          # chunking and offline embedding\n├── core.py         # the LangGraph graph\n├── app.py          # POST /research\n├── test_app.py\n└── requirements.txt",
      steps=[{"title": "Install requirements", "detail": "LangGraph provides the graph runtime.", "file": "requirements.txt"},
             {"title": "Define the state", "detail": "A TypedDict holds question, query, evidence, draft, attempts. Every node returns only the keys it changes.", "file": "core.py"},
             {"title": "Write the nodes", "detail": "plan picks a query, search retrieves from a small corpus, draft writes an answer only from evidence, check decides if the draft is supported.", "file": "core.py"},
             {"title": "Wire the loop with a limit", "detail": "A conditional edge goes back to search with a broader query until the check passes or attempts reach the limit.", "file": "core.py"},
             {"title": "Serve and test", "detail": "The tests prove the loop retries once and that an unanswerable question ends with an honest 'not found', not a made-up answer.", "file": "test_app.py"}],
      files={"requirements.txt": REQ_LG, "kit.py": KIT, "core.py": '''from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from kit import best_sentence, chunk, embed, top_k, words

CORPUS = {
    "rag": "Retrieval-augmented generation fetches relevant passages and gives them to the model so answers are grounded in your documents.",
    "chunking": "Chunking splits long documents into overlapping pieces so retrieval returns focused passages. Typical sizes are 200 to 500 tokens.",
    "rerank": "A reranker rescoring the top candidates with a cross-encoder improves precision after the fast first-stage retrieval.",
    "graph": "LangGraph models an agent as nodes and edges over shared state, with checkpoints for pause and resume.",
}
ITEMS = [{"doc": k, "text": c["text"], "vec": embed(c["text"])} for k, t in CORPUS.items() for c in chunk(t)]
MAX_ATTEMPTS = 3
STOP = {"what", "does", "that", "this", "with", "from", "have", "which", "when", "where", "about", "explain", "would", "could"}


class State(TypedDict, total=False):
    question: str
    query: str
    evidence: list
    draft: str
    supported: bool
    attempts: int
    log: list


def plan(s):
    return {"query": s["question"], "attempts": 0, "log": ["plan: query = question"]}


def search(s):
    q = s["query"]
    hits = top_k(q, ITEMS, 2)
    return {"evidence": [h for _, h in hits], "attempts": s["attempts"] + 1, "log": s["log"] + [f"search #{s['attempts'] + 1}: {q!r} -> {len(hits)} hits"]}


def draft(s):
    if not s["evidence"]:
        return {"draft": "", "log": s["log"] + ["draft: no evidence"]}
    d = " ".join(best_sentence(e["text"], s["question"]) for e in s["evidence"][:1])
    return {"draft": d, "log": s["log"] + ["draft written from evidence"]}


def check(s):
    key = [w for w in words(s["question"]) if len(w) > 3 and w not in STOP]  # content words only: "the", "does" must not count as support
    ok = bool(s["draft"]) and bool(set(key) & set(words(s["draft"])))
    q = s["query"] if ok else (" ".join(key) or s["query"])  # not supported: retry with just the content words
    return {"supported": ok, "query": q, "log": s["log"] + [f"check: {'supported' if ok else 'not supported'}"]}


def route(s):
    return "done" if s["supported"] or s["attempts"] >= MAX_ATTEMPTS else "retry"


def build():
    g = StateGraph(State)
    for name, fn in (("plan", plan), ("search", search), ("draft", draft), ("check", check)):
        g.add_node(name, fn)
    g.add_edge(START, "plan")
    g.add_edge("plan", "search")
    g.add_edge("search", "draft")
    g.add_edge("draft", "check")
    g.add_conditional_edges("check", route, {"retry": "search", "done": END})
    return g.compile()


GRAPH = build()


def research(question):
    out = GRAPH.invoke({"question": question})
    answer = out["draft"] if out["supported"] else "I could not find supporting evidence for this."
    return {"answer": answer, "sources": [e["doc"] for e in out["evidence"]] if out["supported"] else [], "attempts": out["attempts"], "log": out["log"]}
''', "app.py": '''from fastapi import FastAPI
from pydantic import BaseModel, Field

from core import research

app = FastAPI(title="Research agent")


class Q(BaseModel):
    question: str = Field(min_length=3, max_length=300)


@app.post("/research")
def do_research(body: Q):
    return research(body.question)
''', "test_app.py": '''from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def ask(q):
    return client.post("/research", json={"question": q}).json()


def test_answers_from_the_corpus_with_sources():
    r = ask("What does a reranker do?")
    assert "cross-encoder" in r["answer"] and r["sources"] == ["rerank"]


def test_unanswerable_question_stops_at_the_step_limit_and_says_so():
    r = ask("Who won the cricket world cup in 1983?")
    assert r["sources"] == [] and "could not find" in r["answer"] and r["attempts"] == 3


def test_the_log_shows_each_step():
    log = ask("Explain chunking")["log"]
    assert log[0].startswith("plan") and any(x.startswith("search") for x in log) and log[-1].startswith("check")
'''},
      api_tests=[api_test("Research", "/research", '{"question": "What does a reranker do?"}')],
      deploy=DEPLOY_COMMON, interview="The research agent is a LangGraph StateGraph: plan, search, draft, check, with a conditional edge from check back to search. State is a TypedDict and nodes return partial updates. The loop is bounded by an attempts counter, so it always terminates, and the final node refuses when evidence is missing instead of guessing. In production I would add a checkpointer for resume, use an LLM for query rewriting and a groundedness check, stream node updates to the UI and evaluate with a fixed question set."),

    P(id="multi-agent", title="Multi-Agent System (Supervisor + Workers)", level="advanced", hours=4, stack=["Python", "LangGraph", "FastAPI", "Supervisor pattern"], prereq=["supervisor", "graph-state-nodes"],
      summary="A supervisor routes a task to a researcher, a writer and a reviewer. Each worker has one job and the supervisor decides who goes next or finishes.",
      architecture={"nodes": ["supervisor", "researcher", "writer", "reviewer", "END"],
                    "edges": [["supervisor", "researcher"], ["supervisor", "writer"], ["supervisor", "reviewer"], ["researcher", "supervisor"], ["writer", "supervisor"], ["reviewer", "supervisor"], ["supervisor", "END"]]},
      folders="multi-agent/\n├── core.py         # workers + supervisor graph\n├── app.py\n├── test_app.py\n└── requirements.txt",
      steps=[{"title": "Install requirements", "detail": "LangGraph runs the supervisor loop.", "file": "requirements.txt"},
             {"title": "Write narrow workers", "detail": "Each worker reads the shared state and adds one thing: notes, a draft, or a review verdict. Replace each body with an LLM call later.", "file": "core.py"},
             {"title": "Write the supervisor", "detail": "The supervisor looks at what exists and returns the next worker's name, or FINISH. It is a plain function here; an LLM supervisor must return one of the same labels.", "file": "core.py"},
             {"title": "Bound the loop", "detail": "A step counter forces FINISH after a maximum, so a confused supervisor cannot run forever.", "file": "core.py"},
             {"title": "Test routing", "detail": "Check the order of workers and the step limit.", "file": "test_app.py"}],
      files={"requirements.txt": REQ_LG, "core.py": '''from typing import TypedDict

from langgraph.graph import END, START, StateGraph

FACTS = {"rag": "RAG grounds answers in retrieved documents.", "agents": "Agents choose tools in a loop until the task is done.", "graph": "LangGraph runs nodes over shared state."}
MAX_STEPS = 6


class State(TypedDict, total=False):
    topic: str
    notes: str
    draft: str
    approved: bool
    next: str
    steps: int
    trail: list


def researcher(s):
    notes = " ".join(v for k, v in FACTS.items() if k in s["topic"].lower()) or "no facts found"
    return {"notes": notes, "trail": s["trail"] + ["researcher"]}


def writer(s):
    return {"draft": f"Summary of {s['topic']}: {s['notes']}", "trail": s["trail"] + ["writer"]}


def reviewer(s):
    return {"approved": "no facts found" not in s["draft"], "trail": s["trail"] + ["reviewer"]}


def supervisor(s):
    s = {**s, "steps": s.get("steps", 0) + 1, "trail": s.get("trail", [])}
    if s["steps"] > MAX_STEPS:
        nxt = "FINISH"
    elif "notes" not in s:
        nxt = "researcher"
    elif "draft" not in s:
        nxt = "writer"
    elif "approved" not in s:
        nxt = "reviewer"
    else:
        nxt = "FINISH"
    return {"next": nxt, "steps": s["steps"], "trail": s["trail"]}


def build():
    g = StateGraph(State)
    for n, f in (("supervisor", supervisor), ("researcher", researcher), ("writer", writer), ("reviewer", reviewer)):
        g.add_node(n, f)
    g.add_edge(START, "supervisor")
    g.add_conditional_edges("supervisor", lambda s: s["next"], {"researcher": "researcher", "writer": "writer", "reviewer": "reviewer", "FINISH": END})
    for w in ("researcher", "writer", "reviewer"):
        g.add_edge(w, "supervisor")
    return g.compile()


GRAPH = build()


def run(topic):
    out = GRAPH.invoke({"topic": topic})
    return {"draft": out.get("draft", ""), "approved": out.get("approved", False), "trail": out["trail"], "steps": out["steps"]}
''', "app.py": '''from fastapi import FastAPI
from pydantic import BaseModel, Field

from core import run

app = FastAPI(title="Multi-agent")


class Task(BaseModel):
    topic: str = Field(min_length=2, max_length=200)


@app.post("/run")
def run_task(body: Task):
    return run(body.topic)
''', "test_app.py": '''from fastapi.testclient import TestClient

import core
from app import app

client = TestClient(app)


def test_workers_run_in_order_and_the_result_is_approved():
    r = client.post("/run", json={"topic": "RAG and agents"}).json()
    assert r["trail"] == ["researcher", "writer", "reviewer"] and r["approved"] is True
    assert "grounds answers" in r["draft"]


def test_unknown_topic_is_not_approved():
    r = client.post("/run", json={"topic": "cooking pasta"}).json()
    assert r["approved"] is False


def test_step_limit_stops_a_confused_supervisor(monkeypatch):
    monkeypatch.setattr(core, "MAX_STEPS", 1)
    r = core.run("rag")
    assert r["trail"] == ["researcher"] and r["steps"] == 2
'''},
      api_tests=[api_test("Run a task", "/run", '{"topic": "RAG and agents"}')],
      deploy=DEPLOY_COMMON, interview="A supervisor graph has one routing node and several single-purpose workers that all report back to it. State is shared, so each worker only adds its own keys. The supervisor must return a label from a fixed set, which I enforce with a conditional-edge map, and a step counter guarantees termination. Compared with one big agent, workers are easier to test, give smaller prompts and let me restrict tools per role; the cost is extra latency and routing mistakes, so I add tracing and evaluate routing separately."),

    P(id="doc-analysis", title="AI Document Analysis System", level="intermediate", hours=3, stack=["Python", "FastAPI", "Pydantic", "Rule-based extraction (swap in an LLM)"], prereq=["tools-structured-output"],
      summary="Upload a contract or invoice text and get a type, structured fields and risk flags, validated by a schema so the output is always machine-readable.",
      architecture={"nodes": ["Upload", "Text cleaner", "Classifier", "Extractor", "Schema validation", "Risk rules", "JSON report"],
                    "edges": [["Upload", "Text cleaner"], ["Text cleaner", "Classifier"], ["Classifier", "Extractor"], ["Extractor", "Schema validation"], ["Schema validation", "Risk rules"], ["Risk rules", "JSON report"]]},
      folders="doc-analysis/\n├── core.py         # classify, extract, validate, risks\n├── app.py          # POST /analyze\n├── test_app.py\n└── requirements.txt",
      steps=[{"title": "Install requirements", "detail": "Pydantic gives the output schema.", "file": "requirements.txt"},
             {"title": "Define the output schema", "detail": "`Report` lists the fields you promise. Anything the extractor cannot find stays `None`, never guessed.", "file": "core.py"},
             {"title": "Classify and extract", "detail": "Keyword scoring picks invoice, contract or other; regexes pull amounts, dates and party names. With an LLM you would request JSON matching the same schema.", "file": "core.py"},
             {"title": "Flag risks", "detail": "Plain rules (auto-renewal, unlimited liability, missing date) are easier to audit than a model opinion.", "file": "core.py"},
             {"title": "Test", "detail": "Include a document with missing fields to prove nothing is invented.", "file": "test_app.py"}],
      files={"requirements.txt": REQ, "core.py": '''import re
from typing import Optional

from pydantic import BaseModel

KEYWORDS = {"invoice": ("invoice", "amount due", "bill to"), "contract": ("agreement", "party", "terms", "liability", "term of")}


class Report(BaseModel):
    doc_type: str
    amount: Optional[float] = None
    currency: Optional[str] = None
    dates: list[str] = []
    parties: list[str] = []
    risks: list[str] = []


def classify(text):
    t = text.lower()
    scores = {k: sum(w in t for w in ws) for k, ws in KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "other"


def extract(text):
    amt = re.search(r"(?P<cur>USD|INR|EUR|\\$|₹|€)\\s?(?P<num>\\d[\\d,]*(?:\\.\\d+)?)", text)
    cur = {"$": "USD", "₹": "INR", "€": "EUR"}.get(amt["cur"], amt["cur"]) if amt else None
    return {"amount": float(amt["num"].replace(",", "")) if amt else None, "currency": cur,
            "dates": re.findall(r"\\b\\d{4}-\\d{2}-\\d{2}\\b", text),
            "parties": re.findall(r"between ([A-Z][\\w&. ]+?) and ([A-Z][\\w&. ]+?)[,.]", text)[0] if re.search(r"between ([A-Z][\\w&. ]+?) and ([A-Z][\\w&. ]+?)[,.]", text) else []}


def risks(doc_type, text, fields):
    t, out = text.lower(), []
    if doc_type == "contract":
        if "automatically renew" in t or "auto-renew" in t:
            out.append("auto-renewal clause")
        if "unlimited liability" in t:
            out.append("unlimited liability")
        if not fields["dates"]:
            out.append("no dates found")
    if doc_type == "invoice" and fields["amount"] is None:
        out.append("no amount found")
    return out


def analyze(text):
    t = re.sub(r"\\s+", " ", text).strip()
    dt = classify(t)
    f = extract(t)
    return Report(doc_type=dt, risks=risks(dt, t, f), **f).model_dump()
''', "app.py": '''from fastapi import FastAPI
from pydantic import BaseModel, Field

from core import analyze

app = FastAPI(title="Document analysis")


class Doc(BaseModel):
    text: str = Field(min_length=10, max_length=50_000)


@app.post("/analyze")
def analyze_endpoint(body: Doc):
    return analyze(body.text)
''', "test_app.py": '''from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def run(text):
    return client.post("/analyze", json={"text": text}).json()


def test_invoice_fields():
    r = run("Invoice 77. Bill to Asha Traders. Amount due: INR 12,500.50 by 2026-01-31.")
    assert r["doc_type"] == "invoice" and r["amount"] == 12500.5 and r["currency"] == "INR" and r["dates"] == ["2026-01-31"]


def test_contract_risks_and_parties():
    r = run("This agreement is between Acme Ltd and Beta LLP, effective 2026-02-01. The term will automatically renew. Terms include unlimited liability.")
    assert r["doc_type"] == "contract" and r["parties"] == ["Acme Ltd", "Beta LLP"]
    assert "auto-renewal clause" in r["risks"] and "unlimited liability" in r["risks"]


def test_missing_fields_stay_empty_instead_of_invented():
    r = run("An invoice with no figures at all, please pay soon.")
    assert r["amount"] is None and r["dates"] == [] and "no amount found" in r["risks"]


def test_unrelated_text_is_other():
    assert run("Hello there, how are you doing today my friend?")["doc_type"] == "other"
'''},
      api_tests=[api_test("Analyze an invoice", "/analyze", '{"text": "Invoice 77. Bill to Asha Traders. Amount due: INR 12,500.50 by 2026-01-31."}')],
      deploy=DEPLOY_COMMON, interview="Document analysis is classification plus schema-bound extraction plus rules. I define a Pydantic Report, let a model or regexes fill it, validate it, and keep missing values as null so nothing is invented. Risk flags come from explicit, auditable rules rather than a model's opinion. For scanned PDFs I would add OCR first, and I would measure field-level precision and recall on labelled documents and keep a human review queue for low-confidence results."),

    P(id="production-app", title="Production-Ready Agentic App", level="advanced", hours=5, stack=["Python", "FastAPI", "API-key auth", "Rate limiting", "SSE streaming", "Request IDs", "Health check"], prereq=["prod-architecture", "deploy-monitor"],
      summary="The wrapper every agent needs before real users: authentication, per-key rate limit, streaming responses, request IDs for tracing, a health endpoint and tests for all of them.",
      architecture={"nodes": ["Client", "Request-ID middleware", "API-key auth", "Rate limiter", "Agent function", "SSE stream", "/health"],
                    "edges": [["Client", "Request-ID middleware"], ["Request-ID middleware", "API-key auth"], ["API-key auth", "Rate limiter"], ["Rate limiter", "Agent function"], ["Agent function", "SSE stream"], ["Client", "/health"]]},
      folders="production-app/\n├── core.py         # token bucket + agent stub\n├── app.py          # middleware, auth, endpoints\n├── test_app.py\n├── Dockerfile\n└── requirements.txt",
      steps=[{"title": "Install requirements", "detail": "FastAPI plus httpx (the test client needs it).", "file": "requirements.txt"},
             {"title": "Write the rate limiter", "detail": "A token bucket per API key refills over time. In production keep the counters in Redis so every replica shares them.", "file": "core.py"},
             {"title": "Add middleware and auth", "detail": "Every response gets an `X-Request-ID`. Protected routes require `X-API-Key`; keys are compared in constant time.", "file": "app.py"},
             {"title": "Stream the answer", "detail": "`/chat/stream` sends Server-Sent Events: one event per token and a final `done` event, so the UI can show text as it is produced.", "file": "app.py"},
             {"title": "Test the guard rails", "detail": "Missing key, wrong key, rate limit, request-id echo, streaming format and health.", "file": "test_app.py"},
             {"title": "Containerise", "detail": "The Dockerfile runs as a non-root user and exposes only the API port.", "file": "Dockerfile"}],
      files={"requirements.txt": REQ, "core.py": '''import time


class TokenBucket:
    def __init__(self, capacity=5, per_second=1.0, clock=time.monotonic):
        self.capacity, self.rate, self.clock, self.state = capacity, per_second, clock, {}

    def allow(self, key):
        now = self.clock()
        tokens, last = self.state.get(key, (self.capacity, now))
        tokens = min(self.capacity, tokens + (now - last) * self.rate)
        ok = tokens >= 1
        self.state[key] = (tokens - 1 if ok else tokens, now)
        return ok


def agent_tokens(message):
    """Stand-in for the real agent: yields the answer piece by piece. Replace with provider streaming."""
    for word in f"You said: {message}".split():
        yield word + " "
''', "app.py": '''import hmac
import json
import os
import uuid

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core import TokenBucket, agent_tokens

app = FastAPI(title="Production agent")
API_KEYS = {k for k in os.environ.get("APP_API_KEYS", "dev-key").split(",") if k}
bucket = TokenBucket(capacity=5, per_second=1.0)


@app.middleware("http")
async def request_id(request: Request, call_next):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    return response


def guard(x_api_key: str = Header(default="")):
    if not any(hmac.compare_digest(x_api_key, k) for k in API_KEYS):
        raise HTTPException(401, "invalid or missing API key")
    if not bucket.allow(x_api_key):
        raise HTTPException(429, "rate limit exceeded", headers={"Retry-After": "1"})
    return x_api_key


class Chat(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat")
def chat(body: Chat, _key: str = Depends(guard)):
    return {"answer": "".join(agent_tokens(body.message)).strip()}


@app.post("/chat/stream")
def chat_stream(body: Chat, _key: str = Depends(guard)):
    def events():
        for tok in agent_tokens(body.message):
            yield f"event: token\\ndata: {json.dumps({'text': tok})}\\n\\n"
        yield "event: done\\ndata: {}\\n\\n"
    return StreamingResponse(events(), media_type="text/event-stream")
''', "Dockerfile": '''FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd -r app && chown -R app /srv
USER app
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/health')"
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
''', "test_app.py": '''from fastapi.testclient import TestClient

import app as appmod
from core import TokenBucket

client = TestClient(appmod.app)
H = {"X-API-Key": "dev-key"}


def test_health_is_public_and_has_a_request_id():
    r = client.get("/health")
    assert r.json() == {"status": "ok"} and r.headers["X-Request-ID"]
    assert client.get("/health", headers={"X-Request-ID": "abc"}).headers["X-Request-ID"] == "abc"


def test_auth_is_required():
    assert client.post("/chat", json={"message": "hi"}).status_code == 401
    assert client.post("/chat", json={"message": "hi"}, headers={"X-API-Key": "nope"}).status_code == 401


def test_chat_and_stream_format():
    appmod.bucket.state.clear()
    assert client.post("/chat", json={"message": "hello"}, headers=H).json()["answer"] == "You said: hello"
    body = client.post("/chat/stream", json={"message": "hello"}, headers=H).text
    assert body.count("event: token") == 3 and body.rstrip().endswith("data: {}")


def test_rate_limit_returns_429_with_retry_after():
    appmod.bucket.state.clear()
    codes = [client.post("/chat", json={"message": "x"}, headers=H).status_code for _ in range(8)]
    assert codes[:5] == [200] * 5 and 429 in codes[5:]


def test_token_bucket_refills_over_time():
    t = [0.0]
    b = TokenBucket(capacity=2, per_second=1.0, clock=lambda: t[0])
    assert [b.allow("k"), b.allow("k"), b.allow("k")] == [True, True, False]
    t[0] = 1.0
    assert b.allow("k") is True


def test_invalid_input_is_rejected():
    appmod.bucket.state.clear()
    assert client.post("/chat", json={"message": ""}, headers=H).status_code == 422
'''},
      api_tests=[{"title": "Health", "command": "curl http://127.0.0.1:8000/health"}, {"title": "Chat", "command": "curl -X POST http://127.0.0.1:8000/chat -H 'X-API-Key: dev-key' -H 'Content-Type: application/json' -d '{\"message\": \"hello\"}'"},
                 {"title": "Streaming", "command": "curl -N -X POST http://127.0.0.1:8000/chat/stream -H 'X-API-Key: dev-key' -H 'Content-Type: application/json' -d '{\"message\": \"hello\"}'"}],
      deploy=DEPLOY_COMMON, interview="Before an agent meets users I wrap it with authentication (API keys compared in constant time, later OIDC), a per-key token-bucket rate limit shared through Redis, request IDs that appear in every log line and response, SSE streaming for latency, a health endpoint for the orchestrator and tests for each guard rail. Then I add cost and token metering, structured logs and traces, timeouts and retries with backoff on provider calls, secrets from the environment, and a rollout plan with a rollback."),
]
