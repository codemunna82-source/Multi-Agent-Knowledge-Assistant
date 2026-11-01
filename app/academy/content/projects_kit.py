"""Shared by the guided projects: a tiny offline RAG toolkit (kit.py inside every project) and the common deployment text."""

KIT = '''"""Tiny RAG toolkit: chunking, a hash-based embedder that works offline, and cosine search.
Replace embed() with a real embedding model (OpenAI, Gemini, sentence-transformers) to search by meaning instead of by shared words."""
import hashlib
import math
import re


def words(text):
    return re.findall(r"[a-z0-9]+", text.lower())


def chunk(text, size=300, overlap=40):
    step, out = max(1, size - overlap), []
    for start in range(0, max(len(text), 1), step):
        piece = text[start:start + size].strip()
        if piece:
            out.append({"text": piece, "start": start})
        if start + size >= len(text):
            break
    return out


def embed(text, dim=256):
    v = [0.0] * dim
    for w in words(text):
        v[int(hashlib.sha256(w.encode()).hexdigest(), 16) % dim] += 1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def cosine(a, b):
    return sum(x * y for x, y in zip(a, b))


def top_k(query, items, k=3):
    q, qw = embed(query), set(words(query))
    # a hash embedder can collide two different words into one slot, so also require a real shared word
    scored = sorted(((cosine(q, it["vec"]), it) for it in items if qw & set(words(it["text"]))), key=lambda p: -p[0])
    return [(round(s, 4), it) for s, it in scored[:k] if s > 0]


def best_sentence(text, question):
    qs = set(words(question))
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\\s+", text) if s.strip()]
    return max(sents, key=lambda s: len(qs & set(words(s))), default=text)
'''

DEPLOY_COMMON = ("1. Create a virtual environment and install the requirements: `python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt`.\n"
                 "2. Run the tests: `python -m pytest -q`.\n"
                 "3. Start the API locally: `uvicorn app:app --reload` and open http://127.0.0.1:8000/docs for the interactive API page.\n"
                 "4. Containerise it: a `Dockerfile` with `FROM python:3.12-slim`, `COPY requirements.txt .`, `RUN pip install -r requirements.txt`, `COPY . .`, a non-root `USER`, and `CMD [\"uvicorn\", \"app:app\", \"--host\", \"0.0.0.0\", \"--port\", \"8000\"]`.\n"
                 "5. Pass secrets (for example OPENAI_API_KEY) as environment variables at run time, never inside the image, and put the container behind TLS.\n"
                 "6. Before real users: add authentication, rate limits, request logging and a health check (the production project shows all four).")


def P(**kw):
    return kw
