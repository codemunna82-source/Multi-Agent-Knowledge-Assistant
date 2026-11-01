from .projects_kit import DEPLOY_COMMON, KIT, P

REQ = "fastapi\nuvicorn\npython-multipart\nhttpx\npytest\npydantic\n"

PROJECTS_A = [
    P(id="pdf-chatbot", title="PDF Chatbot using RAG", level="beginner", hours=3, stack=["Python", "FastAPI", "PyMuPDF", "NumPy-free hash embeddings (swap in a real embedder)"], prereq=["rag-pipeline", "chunking-loading"],
      summary="Upload a document, ask questions, get answers with citations from the document only.",
      architecture={"nodes": ["Browser / curl", "FastAPI /upload", "Chunker", "Embedder", "In-memory store", "FastAPI /ask", "Answer (LLM or extractive)"],
                    "edges": [["Browser / curl", "FastAPI /upload"], ["FastAPI /upload", "Chunker"], ["Chunker", "Embedder"], ["Embedder", "In-memory store"], ["Browser / curl", "FastAPI /ask"], ["FastAPI /ask", "In-memory store"], ["In-memory store", "Answer (LLM or extractive)"]]},
      folders="pdf-chatbot/\n├── kit.py          # chunking, embedding, search\n├── core.py         # Store: add_document(), ask()\n├── app.py          # FastAPI endpoints\n├── test_app.py     # tests\n└── requirements.txt",
      steps=[{"title": "Create the project and install requirements", "detail": "Make a folder, copy `requirements.txt`, create a virtual environment and install. FastAPI serves the API; PyMuPDF (optional) reads PDFs.", "file": "requirements.txt"},
             {"title": "Write the toolkit", "detail": "kit.py cuts text into overlapping chunks and turns text into vectors. The hash embedder works offline; replace `embed()` with a real model later.", "file": "kit.py"},
             {"title": "Build the store", "detail": "core.py keeps chunks with their vectors, finds the top chunks for a question and builds a grounded answer with numbered citations. If nothing matches it says so instead of guessing.", "file": "core.py"},
             {"title": "Expose it as an API", "detail": "app.py adds /upload (TXT or PDF) and /ask. PDFs need `pip install pymupdf`; the endpoint returns a clear error if it is missing.", "file": "app.py"},
             {"title": "Test it", "detail": "The tests upload a text, ask a question that it answers and one that it does not.", "file": "test_app.py"},
             {"title": "Plug in a real model", "detail": "Pass `llm=your_function` to `Store.ask()` where your function sends the prompt to OpenAI or Gemini and returns text. Keep the 'answer only from the sources' instruction."}],
      files={"requirements.txt": REQ + "# pip install pymupdf   (only if you want to upload PDFs)\n", "kit.py": KIT,
             "core.py": '''from kit import best_sentence, chunk, embed, top_k


class Store:
    def __init__(self):
        self.items = []

    def add_document(self, name, text):
        for i, c in enumerate(chunk(text), 1):
            self.items.append({"doc": name, "n": i, "text": c["text"], "vec": embed(c["text"])})
        return sum(1 for it in self.items if it["doc"] == name)

    def ask(self, question, k=3, llm=None):
        hits = top_k(question, self.items, k)
        if not hits:
            return {"answer": "I could not find this in the uploaded document.", "citations": []}
        sources = "\\n".join(f"[{i}] {h['text']}" for i, (_, h) in enumerate(hits, 1))
        prompt = f"Answer ONLY from the sources and cite them like [1]. If they do not contain the answer, say so.\\n\\n{sources}\\n\\nQuestion: {question}"
        answer = llm(prompt) if llm else f"{best_sentence(hits[0][1]['text'], question)} [1]"
        return {"answer": answer, "citations": [{"n": i, "doc": h["doc"], "chunk": h["n"], "score": s} for i, (s, h) in enumerate(hits, 1)]}
''',
             "app.py": '''from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel

from core import Store

app = FastAPI(title="PDF chatbot")
store = Store()


class Ask(BaseModel):
    question: str


@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    data = await file.read()
    if file.filename.lower().endswith(".pdf"):
        try:
            import fitz  # PyMuPDF
        except ImportError:
            raise HTTPException(415, "Install pymupdf to read PDF files")
        text = "\\n".join(page.get_text() for page in fitz.open(stream=data, filetype="pdf"))
    else:
        text = data.decode("utf-8", "replace")
    if not text.strip():
        raise HTTPException(422, "No text could be extracted")
    return {"file": file.filename, "chunks": store.add_document(file.filename, text)}


@app.post("/ask")
def ask(body: Ask):
    return store.ask(body.question)
''',
             "test_app.py": '''from fastapi.testclient import TestClient

from app import app

client = TestClient(app)
DOC = b"Employees accrue 25 days of annual leave per year. Parental leave is 26 weeks for the primary caregiver. Expense reports are due in 30 days."


def test_upload_then_ask_with_citation():
    assert client.post("/upload", files={"file": ("hr.txt", DOC)}).json()["chunks"] >= 1
    r = client.post("/ask", json={"question": "How long is parental leave?"}).json()
    assert "26 weeks" in r["answer"] and r["citations"][0]["doc"] == "hr.txt"


def test_unanswerable_question_is_refused_not_invented():
    client.post("/upload", files={"file": ("hr.txt", DOC)})
    r = client.post("/ask", json={"question": "xylophone zebra quantum"}).json()
    assert r["citations"] == [] and "could not find" in r["answer"]


def test_empty_file_is_rejected():
    assert client.post("/upload", files={"file": ("empty.txt", b"   ")}).status_code == 422
'''},
      api_tests=[{"title": "Upload", "command": "curl -F file=@handbook.txt http://127.0.0.1:8000/upload"}, {"title": "Ask", "command": "curl -X POST http://127.0.0.1:8000/ask -H 'Content-Type: application/json' -d '{\"question\": \"How long is parental leave?\"}'"}],
      deploy=DEPLOY_COMMON, interview="I built a small RAG service: upload extracts text (PyMuPDF for PDFs), a chunker splits it with overlap, each chunk is embedded and kept in memory, and /ask retrieves the top chunks, builds a prompt that restricts the model to those sources, and returns the answer with numbered citations. It abstains when nothing matches. In production I would persist vectors in a vector database, use a real embedding model, add hybrid search and reranking, authenticate users, and evaluate recall and faithfulness on a labelled question set."),

    P(id="multi-doc-assistant", title="Multi-Document Knowledge Assistant", level="intermediate", hours=4, stack=["Python", "FastAPI", "Chunking with metadata", "Per-document filters"], prereq=["rag-pipeline"],
      summary="Many documents in one assistant: list and delete documents, restrict a question to chosen files, and cite the exact file.",
      architecture={"nodes": ["Client", "FastAPI", "Document registry", "Chunk store (metadata: doc, chunk)", "Filtered retrieval", "Answer + citations"],
                    "edges": [["Client", "FastAPI"], ["FastAPI", "Document registry"], ["FastAPI", "Chunk store (metadata: doc, chunk)"], ["Chunk store (metadata: doc, chunk)", "Filtered retrieval"], ["Filtered retrieval", "Answer + citations"]]},
      folders="multi-doc-assistant/\n├── kit.py\n├── core.py      # Library: add/remove/list documents, ask(docs=[...])\n├── app.py       # /documents, /ask\n├── test_app.py\n└── requirements.txt",
      steps=[{"title": "Reuse the toolkit", "detail": "Same kit.py. The new idea is metadata: every chunk remembers its document so we can filter and cite.", "file": "kit.py"},
             {"title": "A document library", "detail": "core.py stores documents by id, supports deletion (removing their chunks) and asks across all or selected documents. Filtering happens BEFORE ranking, so excluded documents can never appear.", "file": "core.py"},
             {"title": "API", "detail": "GET /documents, POST /documents (JSON with name and text), DELETE /documents/{name}, POST /ask with an optional `docs` list.", "file": "app.py"},
             {"title": "Test the filtering", "detail": "A question answered only by document B must not use document A when A is selected.", "file": "test_app.py"},
             {"title": "Add permissions", "detail": "Next step in a real system: store an owner or group with each document and apply it in the same filter, so users only retrieve what they may read."}],
      files={"requirements.txt": REQ, "kit.py": KIT,
             "core.py": '''from kit import best_sentence, chunk, embed, top_k


class Library:
    def __init__(self):
        self.docs, self.items = {}, []

    def add(self, name, text):
        self.remove(name)
        self.docs[name] = len(text)
        for i, c in enumerate(chunk(text, 200, 30), 1):
            self.items.append({"doc": name, "n": i, "text": c["text"], "vec": embed(c["text"])})
        return sum(1 for it in self.items if it["doc"] == name)

    def remove(self, name):
        existed = self.docs.pop(name, None) is not None
        self.items = [it for it in self.items if it["doc"] != name]
        return existed

    def ask(self, question, docs=None, k=3):
        pool = [it for it in self.items if docs is None or it["doc"] in docs]      # filter first, rank second
        hits = top_k(question, pool, k)
        if not hits:
            return {"answer": "None of the selected documents contains this.", "citations": []}
        best = hits[0][1]
        return {"answer": f"{best_sentence(best['text'], question)} [1]", "citations": [{"n": i, "doc": h["doc"], "chunk": h["n"], "score": s} for i, (s, h) in enumerate(hits, 1)]}
''',
             "app.py": '''from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from core import Library

app = FastAPI(title="Multi-document assistant")
lib = Library()


class Doc(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=200_000)


class Ask(BaseModel):
    question: str
    docs: Optional[list[str]] = None


@app.get("/documents")
def documents():
    return [{"name": n, "chars": c} for n, c in lib.docs.items()]


@app.post("/documents", status_code=201)
def add(doc: Doc):
    return {"name": doc.name, "chunks": lib.add(doc.name, doc.text)}


@app.delete("/documents/{name}")
def delete(name: str):
    if not lib.remove(name):
        raise HTTPException(404, "No such document")
    return {"deleted": name}


@app.post("/ask")
def ask(body: Ask):
    unknown = [d for d in (body.docs or []) if d not in lib.docs]
    if unknown:
        raise HTTPException(404, f"Unknown document(s): {', '.join(unknown)}")
    return lib.ask(body.question, body.docs)
''',
             "test_app.py": '''from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def setup_function():
    for d in client.get("/documents").json():
        client.delete(f"/documents/{d['name']}")
    client.post("/documents", json={"name": "hr.txt", "text": "Parental leave is 26 weeks for the primary caregiver."})
    client.post("/documents", json={"name": "it.txt", "text": "Reset your laptop password from the IT portal. Laptops are replaced every four years."})


def test_cites_the_right_document():
    r = client.post("/ask", json={"question": "How do I reset my password?"}).json()
    assert r["citations"][0]["doc"] == "it.txt"


def test_filter_excludes_other_documents():
    r = client.post("/ask", json={"question": "How do I reset my password?", "docs": ["hr.txt"]}).json()
    assert all(c["doc"] == "hr.txt" for c in r["citations"])


def test_delete_removes_knowledge():
    client.delete("/documents/it.txt")
    r = client.post("/ask", json={"question": "reset password laptop"}).json()
    assert all(c["doc"] != "it.txt" for c in r["citations"])
    assert client.delete("/documents/it.txt").status_code == 404
    assert client.post("/ask", json={"question": "x", "docs": ["ghost.txt"]}).status_code == 404
'''},
      api_tests=[{"title": "Add a document", "command": "curl -X POST http://127.0.0.1:8000/documents -H 'Content-Type: application/json' -d '{\"name\": \"hr.txt\", \"text\": \"Parental leave is 26 weeks.\"}'"}, {"title": "Ask only one document", "command": "curl -X POST http://127.0.0.1:8000/ask -H 'Content-Type: application/json' -d '{\"question\": \"parental leave\", \"docs\": [\"hr.txt\"]}'"}],
      deploy=DEPLOY_COMMON, interview="The key design point is metadata: every chunk carries its document id, so the library can list and delete documents (removing their chunks), restrict a question to selected documents, and cite exactly which file an answer came from. Filtering is applied before ranking, which is how you enforce access control too: a user's allowed documents become part of the retrieval query, never a post-filter. For scale I would move the chunk store into a vector database with metadata filters and add per-tenant isolation."),

    P(id="semantic-search", title="Semantic Search Engine", level="beginner", hours=2, stack=["Python", "FastAPI", "Embeddings", "Cosine similarity"], prereq=["what-are-embeddings", "vector-search"],
      summary="Index a list of texts and search it by meaning (or, with the offline embedder, by shared words) with similarity scores.",
      architecture={"nodes": ["POST /index", "Embedder", "Vector list", "GET /search?q=", "Cosine ranking", "Results with scores"],
                    "edges": [["POST /index", "Embedder"], ["Embedder", "Vector list"], ["GET /search?q=", "Embedder"], ["Embedder", "Cosine ranking"], ["Vector list", "Cosine ranking"], ["Cosine ranking", "Results with scores"]]},
      folders="semantic-search/\n├── kit.py\n├── app.py        # /index, /search, /stats\n├── test_app.py\n└── requirements.txt",
      steps=[{"title": "Understand what is being built", "detail": "A search box over your own texts: each text becomes a vector, a query becomes a vector, and the closest vectors win.", "file": "kit.py"},
             {"title": "Index endpoint", "detail": "POST /index replaces the index with a list of texts (max 1000) and reports how many vectors were stored.", "file": "app.py"},
             {"title": "Search endpoint", "detail": "GET /search?q=...&k=3 returns the top-k texts with cosine scores. Zero-score results are dropped.", "file": "app.py"},
             {"title": "Test", "detail": "A query that shares words with one text ranks it first; an unrelated query returns nothing.", "file": "test_app.py"},
             {"title": "Upgrade to real semantic search", "detail": "Replace `embed()` in kit.py by a call to an embedding model. Keep the same interface (text -> list of floats, length 1). Now 'quit my job' can find 'resignation procedure'."}],
      files={"requirements.txt": REQ, "kit.py": KIT,
             "app.py": '''from fastapi import FastAPI, Query
from pydantic import BaseModel, Field

from kit import embed, top_k

app = FastAPI(title="Semantic search")
INDEX = []


class Texts(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=1000)


@app.post("/index")
def index(body: Texts):
    INDEX[:] = [{"text": t, "vec": embed(t)} for t in body.texts]
    return {"indexed": len(INDEX)}


@app.get("/search")
def search(q: str = Query(min_length=1, max_length=500), k: int = Query(3, ge=1, le=20)):
    return [{"text": it["text"], "score": s} for s, it in top_k(q, INDEX, k)]


@app.get("/stats")
def stats():
    return {"documents": len(INDEX), "dimensions": len(INDEX[0]["vec"]) if INDEX else 0}
''',
             "test_app.py": '''from fastapi.testclient import TestClient

from app import app

client = TestClient(app)
TEXTS = ["How to reset your password", "Quarterly sales report for the finance team", "Office parking rules and visitor passes"]


def test_search_ranks_the_matching_text_first():
    assert client.post("/index", json={"texts": TEXTS}).json() == {"indexed": 3}
    r = client.get("/search", params={"q": "reset password"}).json()
    assert r[0]["text"] == TEXTS[0] and 0 < r[0]["score"] <= 1


def test_unrelated_query_returns_nothing_and_limits_are_validated():
    client.post("/index", json={"texts": TEXTS})
    assert client.get("/search", params={"q": "zebra xylophone"}).json() == []
    assert client.get("/search", params={"q": "x", "k": 99}).status_code == 422
    assert client.get("/stats").json()["dimensions"] == 256
'''},
      api_tests=[{"title": "Index", "command": "curl -X POST http://127.0.0.1:8000/index -H 'Content-Type: application/json' -d '{\"texts\": [\"How to reset your password\", \"Office parking rules\"]}'"}, {"title": "Search", "command": "curl 'http://127.0.0.1:8000/search?q=reset%20password&k=2'"}],
      deploy=DEPLOY_COMMON, interview="Semantic search embeds every document once and the query at request time with the SAME model, then ranks by cosine similarity. This version keeps vectors in a Python list (brute force is exact and fine up to about a hundred thousand vectors). For more data I would switch to a vector database with an ANN index such as HNSW, keep metadata filters inside the query, and combine it with keyword search because embeddings can blur exact identifiers."),

    P(id="rag-reranking", title="RAG with Hybrid Search and Reranking", level="advanced", hours=4, stack=["Python", "FastAPI", "BM25", "Reciprocal Rank Fusion", "Reranker"], prereq=["hybrid-rerank"],
      summary="Combine keyword and vector search, fuse the rankings, rerank the best candidates, and show the order before and after.",
      architecture={"nodes": ["Question", "BM25 keyword ranking", "Vector ranking", "RRF fusion", "Reranker (top 5)", "Final top-k + before/after"],
                    "edges": [["Question", "BM25 keyword ranking"], ["Question", "Vector ranking"], ["BM25 keyword ranking", "RRF fusion"], ["Vector ranking", "RRF fusion"], ["RRF fusion", "Reranker (top 5)"], ["Reranker (top 5)", "Final top-k + before/after"]]},
      folders="rag-reranking/\n├── kit.py\n├── core.py      # bm25(), rrf(), rerank(), search()\n├── app.py       # /index, /search\n├── test_app.py\n└── requirements.txt",
      steps=[{"title": "Keyword ranking", "detail": "BM25 scores documents by rare query words: ideal for codes such as E-4021.", "file": "core.py"},
             {"title": "Fuse with the vector ranking", "detail": "Reciprocal Rank Fusion adds 1/(60+rank) from each list, so no score scaling is needed.", "file": "core.py"},
             {"title": "Rerank a short list", "detail": "A second, slower, more careful scorer re-orders only the top candidates. Here it rewards exact phrase and word coverage; in production use a cross-encoder or an LLM.", "file": "core.py"},
             {"title": "Expose before/after", "detail": "The API returns the order before and after reranking so you can see what it changed.", "file": "app.py"},
             {"title": "Prove it with a test", "detail": "A query with an exact error code must put the document with that code first even if vector search prefers another one.", "file": "test_app.py"},
             {"title": "Measure", "detail": "Build a labelled question set and compare recall@3 and MRR with and without the reranker before keeping it (it adds latency)."}],
      files={"requirements.txt": REQ, "kit.py": KIT,
             "core.py": '''import math
from collections import Counter

from kit import cosine, embed, words


def bm25(query, docs, k1=1.5, b=0.75):
    toks = [words(d) for d in docs]
    avg = sum(len(t) for t in toks) / max(1, len(toks))
    df = Counter(w for t in toks for w in set(t))
    out = []
    for t in toks:
        tf, s = Counter(t), 0.0
        for w in words(query):
            if w in tf:
                s += math.log(1 + (len(toks) - df[w] + 0.5) / (df[w] + 0.5)) * tf[w] * (k1 + 1) / (tf[w] + k1 * (1 - b + b * len(t) / (avg or 1)))
        out.append(s)
    return out


def rank(scores):
    return [i for i, s in sorted(enumerate(scores), key=lambda p: (-p[1], p[0])) if s > 0]


def rrf(rankings, k=60):
    total = Counter()
    for r in rankings:
        for pos, i in enumerate(r, 1):
            total[i] += 1 / (k + pos)
    return [i for i, _ in sorted(total.items(), key=lambda p: (-p[1], p[0]))]


def rerank(query, docs, ids):
    q = set(words(query))
    def score(i):
        d = words(docs[i])
        coverage = len(q & set(d)) / max(1, len(q))
        phrase = 1.0 if " ".join(words(query)) in " ".join(d) else 0.0
        return coverage + 0.5 * phrase
    return sorted(ids, key=lambda i: (-score(i), ids.index(i)))


def search(query, docs, k=3, use_rerank=True):
    keyword = rank(bm25(query, docs))
    q = embed(query)
    vector = rank([cosine(q, embed(d)) for d in docs])
    fused = rrf([keyword, vector])
    pool = fused[:5]
    final = rerank(query, docs, pool) if use_rerank else pool
    return {"keyword": keyword, "vector": vector, "before": pool[:k], "after": final[:k]}
''',
             "app.py": '''from fastapi import FastAPI, Query
from pydantic import BaseModel, Field

from core import search

app = FastAPI(title="Hybrid search with reranking")
DOCS = []


class Texts(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=500)


@app.post("/index")
def index(body: Texts):
    DOCS[:] = body.texts
    return {"indexed": len(DOCS)}


@app.get("/search")
def do_search(q: str = Query(min_length=1, max_length=300), k: int = Query(3, ge=1, le=10), rerank: bool = True):
    r = search(q, DOCS, k, rerank)
    show = lambda ids: [{"id": i, "text": DOCS[i]} for i in ids]
    return {"before_rerank": show(r["before"]), "results": show(r["after"]), "keyword_only": r["keyword"][:k], "vector_only": r["vector"][:k]}
''',
             "test_app.py": '''from fastapi.testclient import TestClient

from app import app

client = TestClient(app)
DOCS = ["Upgrade failures: check disk space and restart the service.", "Error E-4021 appears after the upgrade to version 5; reinstall the driver.", "How to export a report to PDF."]


def test_exact_code_wins_with_hybrid_search_and_reranking():
    client.post("/index", json={"texts": DOCS})
    r = client.get("/search", params={"q": "error E-4021 after upgrade"}).json()
    assert r["results"][0]["id"] == 1


def test_response_shows_the_order_before_and_after_reranking():
    client.post("/index", json={"texts": DOCS})
    r = client.get("/search", params={"q": "upgrade disk space", "k": 2}).json()
    assert len(r["before_rerank"]) == 2 and len(r["results"]) == 2 and set(r["keyword_only"]) <= {0, 1}
    assert client.get("/search", params={"q": "x", "k": 50}).status_code == 422
'''},
      api_tests=[{"title": "Index", "command": "curl -X POST http://127.0.0.1:8000/index -H 'Content-Type: application/json' -d '{\"texts\": [\"Upgrade failures: check disk space.\", \"Error E-4021 appears after upgrade.\"]}'"}, {"title": "Search with and without reranking", "command": "curl 'http://127.0.0.1:8000/search?q=error%20E-4021&rerank=true' ; curl 'http://127.0.0.1:8000/search?q=error%20E-4021&rerank=false'"}],
      deploy=DEPLOY_COMMON, interview="I use hybrid retrieval because BM25 and dense search fail differently: BM25 nails exact codes and names, embeddings handle paraphrases. Reciprocal Rank Fusion merges the lists using ranks only. Then a reranker re-scores just the top candidates, because a cross-encoder reads query and passage together and is more accurate but too slow for the whole corpus. I verify the gain on a labelled set (recall@k before, precision of the final top-k after) and watch the latency cost."),

    P(id="support-agent", title="Customer Support AI Agent", level="intermediate", hours=4, stack=["Python", "FastAPI", "Intent routing", "Tools", "Escalation to a human"], prereq=["agent-loop", "function-calling"],
      summary="A support bot that routes by intent, looks up orders with a real tool, answers policy questions from an FAQ and hands over to a human when unsure or the customer is upset.",
      architecture={"nodes": ["Customer message", "Intent router", "Order tool (authorised lookup)", "FAQ retrieval", "Escalation to a human", "Reply"],
                    "edges": [["Customer message", "Intent router"], ["Intent router", "Order tool (authorised lookup)"], ["Intent router", "FAQ retrieval"], ["Intent router", "Escalation to a human"], ["Order tool (authorised lookup)", "Reply"], ["FAQ retrieval", "Reply"], ["Escalation to a human", "Reply"]]},
      folders="support-agent/\n├── kit.py\n├── core.py      # route(), tools, handle()\n├── app.py       # /chat\n├── test_app.py\n└── requirements.txt",
      steps=[{"title": "Decide the intents", "detail": "order_status, policy_question, and a safe fallback. A rule-based router keeps the demo offline; swap it for an LLM classifier that returns one of the same labels.", "file": "core.py"},
             {"title": "Write narrow tools", "detail": "`order_status(customer, order_id)` checks that the order belongs to the customer: authorise inside the tool, never trust the message.", "file": "core.py"},
             {"title": "Answer policy questions from an FAQ", "detail": "Retrieve the best FAQ entry; if the score is low, escalate instead of guessing.", "file": "core.py"},
             {"title": "Escalate", "detail": "Angry words or unknown intent create a handover ticket for a human and tell the customer honestly.", "file": "core.py"},
             {"title": "API and tests", "detail": "POST /chat with customer id and message returns the reply, the route taken and the tool trace.", "file": "app.py"}],
      files={"requirements.txt": REQ, "kit.py": KIT,
             "core.py": '''import re

from kit import best_sentence, embed, top_k

ORDERS = {"4412": {"customer": "asha", "status": "shipped yesterday"}, "5001": {"customer": "ravi", "status": "being packed"}}
FAQ = ["Refunds are paid back within 14 days after we receive the item.", "Standard shipping takes 3 to 5 business days.", "You can change your delivery address until the order is packed."]
FAQ_ITEMS = [{"text": t, "vec": embed(t)} for t in FAQ]
UPSET = re.compile(r"\\b(angry|furious|terrible|worst|lawyer|complaint|cancel everything)\\b", re.I)


def route(message):
    if UPSET.search(message):
        return "escalate"
    if re.search(r"\\border\\b.*\\b\\d{4}\\b|\\b\\d{4}\\b.*\\border\\b|\\bwhere is my order\\b", message, re.I):
        return "order_status"
    return "policy_question"


def order_status(customer, order_id):
    order = ORDERS.get(order_id)
    if not order or order["customer"] != customer:       # authorise with the REAL customer id
        return None
    return order["status"]


def handle(customer, message):
    intent, trace = route(message), []
    if intent == "order_status":
        m = re.search(r"\\b(\\d{4})\\b", message)
        status = order_status(customer, m.group(1)) if m else None
        trace.append({"tool": "order_status", "order": m.group(1) if m else None, "found": status is not None})
        if status:
            return {"intent": intent, "reply": f"Your order {m.group(1)} is {status}.", "trace": trace, "escalated": False}
        return {"intent": intent, "reply": "I could not find that order on your account. Please check the number.", "trace": trace, "escalated": False}
    if intent == "policy_question":
        hits = top_k(message, FAQ_ITEMS, 1)
        trace.append({"tool": "faq_search", "score": hits[0][0] if hits else 0})
        if hits and hits[0][0] >= 0.2:
            return {"intent": intent, "reply": best_sentence(hits[0][1]["text"], message), "trace": trace, "escalated": False}
    return {"intent": "escalate", "reply": "I am passing this to a colleague who will contact you soon.", "trace": trace + [{"tool": "create_ticket", "customer": customer}], "escalated": True}
''',
             "app.py": '''from fastapi import FastAPI
from pydantic import BaseModel, Field

from core import handle

app = FastAPI(title="Support agent")


class Chat(BaseModel):
    customer: str = Field(min_length=1, max_length=40)
    message: str = Field(min_length=1, max_length=1000)


@app.post("/chat")
def chat(body: Chat):
    return handle(body.customer, body.message)
''',
             "test_app.py": '''from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def chat(customer, message):
    return client.post("/chat", json={"customer": customer, "message": message}).json()


def test_order_lookup_uses_the_tool():
    r = chat("asha", "Where is my order 4412?")
    assert r["intent"] == "order_status" and "shipped yesterday" in r["reply"] and r["trace"][0]["tool"] == "order_status"


def test_customers_cannot_see_other_customers_orders():
    r = chat("asha", "Where is my order 5001?")
    assert "could not find" in r["reply"] and "packed" not in r["reply"]


def test_policy_questions_come_from_the_faq():
    assert "14 days" in chat("asha", "How long do refunds take?")["reply"]


def test_unknown_or_angry_messages_are_escalated():
    for msg in ("I am furious, this is the worst service", "What is the meaning of life in Antarctica?"):
        r = chat("asha", msg)
        assert r["escalated"] is True and r["trace"][-1]["tool"] == "create_ticket"
'''},
      api_tests=[{"title": "Order status", "command": "curl -X POST http://127.0.0.1:8000/chat -H 'Content-Type: application/json' -d '{\"customer\": \"asha\", \"message\": \"Where is my order 4412?\"}'"}, {"title": "Escalation", "command": "curl -X POST http://127.0.0.1:8000/chat -H 'Content-Type: application/json' -d '{\"customer\": \"asha\", \"message\": \"This is the worst service, I want a lawyer\"}'"}],
      deploy=DEPLOY_COMMON, interview="A support agent is a router plus narrow tools plus a safe fallback. The router (rules or an LLM that must return one of a fixed set of labels) picks a path; tools authorise with the authenticated customer id inside the tool, so a manipulated message cannot read another customer's order; policy answers come from retrieval and fall back to a human when confidence is low. Every step is traced for audit. I measure containment rate, escalation precision and wrong-answer rate on real transcripts before widening what the bot may do."),
]
