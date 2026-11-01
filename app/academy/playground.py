"""Server side of the Academy playgrounds: LLM, prompt comparison, embeddings, an ephemeral RAG pipeline and a LangChain pipeline runner.

Principles: real components only (the configured LLM / embedder, the project's own loaders, chunker and rerankers, real langchain_core objects);
when something is not configured the response says so and shows what WOULD be sent - nothing is simulated and presented as real.
Everything here is stateless and in-memory: uploaded text is never stored, indexed or logged."""
from __future__ import annotations

import difflib
import importlib.util
import math
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Iterator, Optional

import numpy as np

from ..core import IngestError, format_loc, stem, tokenize
from ..ingestion import loaders
from ..ingestion.chunking import chunk_units
from ..providers import track_usage
from ..rag import steps
from ..rag.types import Hit
from ..security.files import validate_upload

LLM_SETUP = ("No language model is configured on this server. Set MKA_LLM_PROVIDER=openai and OPENAI_API_KEY (or MKA_LLM_PROVIDER=gemini and GEMINI_API_KEY), "
             "restart the server and reload this page. Below is the exact request that would be sent.")
MAX_PROMPT, MAX_SYSTEM, MAX_TOKENS = 8000, 4000, 1000
RAG_LIMITS = {"file_bytes": 2_000_000, "chars": 200_000, "chunks": 400}
RAG_TYPES = {".pdf", ".txt", ".csv", ".md"}


# ----------------------------------------------------------------------------- capabilities
def capabilities(k) -> dict:
    emb = k.embedder
    return {
        "llm": {"available": bool(k.llm.available), "name": k.llm.name if k.llm.available else None, "setup": None if k.llm.available else LLM_SETUP},
        "embedder": {"name": emb.name, "dim": getattr(emb, "dim", 0), "semantic": not str(emb.name).startswith("hash"),
                     "note": None if not str(emb.name).startswith("hash") else "The built-in 'hash' embedder measures shared WORDS, not meaning (it works without a key). Configure OpenAI or Gemini embeddings (MKA_EMBEDDING_PROVIDER) for semantic similarity."},
        "cross_encoder": {"available": importlib.util.find_spec("sentence_transformers") is not None, "model": k.settings.cross_encoder_model,
                          "setup": "pip install sentence-transformers (the model downloads on first use and needs internet access)"},
        "limits": {"prompt_chars": MAX_PROMPT, "system_chars": MAX_SYSTEM, "max_tokens": MAX_TOKENS, **{f"rag_{a}": b for a, b in RAG_LIMITS.items()}},
    }


# ----------------------------------------------------------------------------- LLM
def llm_request(system: str, prompt: str, temperature: float, max_tokens: int) -> dict:
    return {"messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}], "temperature": temperature, "max_tokens": max_tokens}


def llm_run(k, system: str, prompt: str, temperature: float, max_tokens: int) -> dict:
    req = llm_request(system, prompt, temperature, max_tokens)
    if not k.llm.available:
        return {"available": False, "setup": LLM_SETUP, "request": req}
    t0 = time.perf_counter()
    with track_usage() as u:
        text = k.llm.generate(system, prompt, temperature, max_tokens)
    return {"available": True, "text": text, "model": k.llm.name, "latency_ms": round((time.perf_counter() - t0) * 1000), "usage": u.as_dict(), "request": req}


def llm_stream(k, system: str, prompt: str, temperature: float, max_tokens: int) -> Iterator[dict]:
    """Yields {"type": "token"|"done"|"unavailable"}. The first token time is measured, not guessed."""
    req = llm_request(system, prompt, temperature, max_tokens)
    if not k.llm.available:
        yield {"type": "unavailable", "setup": LLM_SETUP, "request": req}
        return
    t0, first, n = time.perf_counter(), None, 0
    with track_usage() as u:
        for piece in k.llm.generate_stream(system, prompt, temperature, max_tokens):
            if first is None:
                first = time.perf_counter()
            n += 1
            yield {"type": "token", "text": piece}
    yield {"type": "done", "model": k.llm.name, "usage": u.as_dict(), "latency_ms": round((time.perf_counter() - t0) * 1000), "first_token_ms": round((first - t0) * 1000) if first else None, "chunks": n, "request": req}


def compare_prompts(k, variants: list[dict], temperature: float, max_tokens: int) -> dict:
    reqs = [llm_request(v["system"], v["prompt"], temperature, max_tokens) for v in variants]
    if not k.llm.available:
        return {"available": False, "setup": LLM_SETUP, "variants": [{"name": v["name"], "request": r} for v, r in zip(variants, reqs)]}
    out = []
    for v, r in zip(variants, reqs):
        t0 = time.perf_counter()
        with track_usage() as u:
            text = k.llm.generate(v["system"], v["prompt"], temperature, max_tokens)
        out.append({"name": v["name"], "text": text, "words": len(text.split()), "latency_ms": round((time.perf_counter() - t0) * 1000), "usage": u.as_dict(), "request": r})
    base = out[0]["text"].split()
    for o in out[1:]:
        w = o["text"].split()
        o["similarity_to_first"] = round(difflib.SequenceMatcher(None, base, w).ratio(), 3)
        o["only_here"] = sorted(set(w) - set(base))[:15]
        o["missing_vs_first"] = sorted(set(base) - set(w))[:15]
    return {"available": True, "model": k.llm.name, "variants": out}


# ----------------------------------------------------------------------------- embeddings
def embeddings_compare(k, texts: list[str]) -> dict:
    emb = k.embedder
    t0 = time.perf_counter()
    v = np.asarray(emb.embed_documents(texts), dtype=np.float64)
    ms = round((time.perf_counter() - t0) * 1000)
    nrm = np.linalg.norm(v, axis=1, keepdims=True)
    u = v / np.where(nrm == 0, 1, nrm)
    sim = (u @ u.T).round(4)
    order = sorted(range(1, len(texts)), key=lambda i: -sim[0][i])
    caps = capabilities(k)["embedder"]
    return {"embedder": emb.name, "semantic": caps["semantic"], "note": caps["note"], "dim": int(v.shape[1]), "latency_ms": ms, "texts": texts,
            "vectors": [{"first_values": [round(float(x), 4) for x in row[:8]], "norm": round(float(n), 4)} for row, n in zip(v, nrm[:, 0])],
            "similarity": sim.tolist(), "ranking_vs_first": [{"index": i, "text": texts[i], "cosine": float(sim[0][i])} for i in order]}


# ----------------------------------------------------------------------------- RAG
def _bm25(q_terms: list[str], docs: list[list[str]], k1: float = 1.5, b: float = 0.75) -> list[float]:
    n = len(docs)
    avg = sum(len(d) for d in docs) / max(1, n)
    df: dict[str, int] = {}
    for d in docs:
        for w in set(d):
            df[w] = df.get(w, 0) + 1
    out = []
    for d in docs:
        tf: dict[str, int] = {}
        for w in d:
            tf[w] = tf.get(w, 0) + 1
        s = 0.0
        for w in q_terms:
            f = tf.get(w)
            if f:
                s += math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5)) * f * (k1 + 1) / (f + k1 * (1 - b + b * len(d) / (avg or 1)))
        out.append(s)
    return out


def _extract(k, filename: Optional[str], data: Optional[bytes], text: Optional[str]):
    work = Path(tempfile.mkdtemp(prefix="mka-pg-"))
    try:
        if text is not None:
            if len(text) > RAG_LIMITS["chars"]:
                raise IngestError(f"Pasted text is limited to {RAG_LIMITS['chars']:,} characters")
            name, data = "pasted.txt", text.encode("utf-8")
        else:
            name = Path(filename or "upload").name
            if Path(name).suffix.lower() not in RAG_TYPES:
                raise IngestError("The playground accepts PDF, TXT, CSV and MD files")
        if data is None or len(data) > RAG_LIMITS["file_bytes"]:
            raise IngestError(f"Files are limited to {RAG_LIMITS['file_bytes'] // 1_000_000} MB in the playground")
        path = work / re.sub(r"[^A-Za-z0-9._-]", "_", name)
        path.write_bytes(data)
        kind = loaders.kind_for(path.name)
        validate_upload(path, kind, 50)
        ex = loaders.extract(path, kind, k.settings.model_copy(update={"ocr_enabled": False}))
        return name, ex
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _sentences(t: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", t) if len(s.strip()) > 3]


def rag_run(k, *, filename: Optional[str], data: Optional[bytes], text: Optional[str], question: str, chunk_size: int, overlap: int, top_k: int, mode: str, rerank: str, answer: bool) -> dict:
    t_all = time.perf_counter()
    name, ex = _extract(k, filename, data, text)
    full = "\n".join(u.text for u in ex.units)
    if not full.strip():
        raise IngestError("No text could be extracted (scanned PDFs need OCR, which the playground does not run)")
    stages: dict[str, Any] = {"extract": {"file": name, "units": len(ex.units), "chars": len(full), "title": ex.title, "warnings": ex.warnings[:3], "preview": full[:1500], "tables": len(ex.tables)}}

    chunks = chunk_units(ex.units, chunk_size, overlap)
    if len(chunks) > RAG_LIMITS["chunks"]:
        raise IngestError(f"That makes {len(chunks)} chunks; the playground allows {RAG_LIMITS['chunks']}. Use a larger chunk size or a shorter text.")
    loc = [format_loc(c.loc, c.loc_end) for c in chunks]
    stages["chunks"] = {"count": len(chunks), "size": chunk_size, "overlap": overlap, "lengths": [len(c.text) for c in chunks],
                        "items": [{"id": i + 1, "location": loc[i], "chars": len(c.text), "text": c.text[:260]} for i, c in enumerate(chunks[:60])], "truncated_list": len(chunks) > 60}

    t0 = time.perf_counter()
    vecs = np.asarray(k.embedder.embed_documents([c.text for c in chunks]), dtype=np.float64)
    qv = np.asarray(k.embedder.embed_query(question), dtype=np.float64)
    caps = capabilities(k)["embedder"]
    stages["embed"] = {"embedder": k.embedder.name, "dim": int(vecs.shape[1]), "ms": round((time.perf_counter() - t0) * 1000), "semantic": caps["semantic"], "note": caps["note"]}
    stages["store"] = {"vectors": len(chunks), "bytes": int(vecs.nbytes), "persisted": False, "note": "An in-memory NumPy matrix for this request only. Nothing is saved or indexed."}

    nrm = np.linalg.norm(vecs, axis=1) * (np.linalg.norm(qv) or 1.0)
    cos = np.divide(vecs @ qv, nrm, out=np.zeros(len(chunks)), where=nrm > 0)
    q_terms = [stem(t) for t in tokenize(question)]
    docs = [[stem(t) for t in tokenize(c.text)] for c in chunks]
    kw = np.asarray(_bm25(q_terms, docs))
    vec_rank = list(np.argsort(-cos, kind="stable"))
    kw_rank = [int(i) for i in np.argsort(-kw, kind="stable") if kw[i] > 0]
    if mode == "vector":
        order, fused = [int(i) for i in vec_rank], {int(i): float(cos[i]) for i in vec_rank}
    elif mode == "keyword":
        order, fused = kw_rank, {i: float(kw[i]) for i in kw_rank}
    else:
        f: dict[int, float] = {}
        for ranking in (vec_rank, kw_rank):
            for pos, i in enumerate(ranking):
                f[int(i)] = f.get(int(i), 0.0) + 1 / (60 + pos + 1)
        order = sorted(f, key=lambda i: -f[i])
        fused = f
    pool = order[: max(top_k * 3, top_k, 10)]
    stages["search"] = {"mode": mode, "candidates": len(pool), "top": [{"rank": r + 1, "chunk": i + 1, "cosine": round(float(cos[i]), 4), "bm25": round(float(kw[i]), 3), "score": round(fused[i], 5), "location": loc[i], "text": chunks[i].text[:220]} for r, i in enumerate(pool[:top_k])]}

    hits = [Hit(chunk_id=str(i), source_id="p", source=name, location=loc[i], loc=chunks[i].loc, text=chunks[i].text, score=max(0.0, float(cos[i])), lexical=0.0, fused=float(fused[i])) for i in pool]
    before = [int(h.chunk_id) for h in hits]
    method = "none"
    if rerank != "none" and hits:
        mx = float(kw.max()) or 1.0
        steps.lexical_rerank(hits, q_terms, {h.chunk_id: float(kw[int(h.chunk_id)]) / mx for h in hits})
        method = "lexical"
        if rerank == "cross_encoder":
            try:
                if steps.cross_encoder_rerank(k.settings.cross_encoder_model, question, hits):
                    method = "cross_encoder"
                else:
                    method = "lexical (cross-encoder is not installed)"
            except Exception as e:  # noqa: BLE001 - e.g. the model could not be downloaded
                method = f"lexical (cross-encoder failed: {type(e).__name__})"
        hits.sort(key=lambda h: -(h.rerank or 0.0))
    after = [int(h.chunk_id) for h in hits]
    top = hits[:top_k]
    stages["rerank"] = {"method": method, "before": [i + 1 for i in before[:top_k]], "after": [i + 1 for i in after[:top_k]], "moved": [i + 1 for i in after[:top_k] if i not in before[:top_k] or before.index(i) != after.index(i)],
                        "items": [{"rank": r + 1, "chunk": int(h.chunk_id) + 1, "rerank_score": None if h.rerank is None else round(h.rerank, 4), "was_rank": before.index(int(h.chunk_id)) + 1, "text": h.text[:160]} for r, h in enumerate(top)]}

    sources = "\n".join(f"[{n}] ({h.location}) {h.text.strip()}" for n, h in enumerate(top, 1))
    system = "Answer ONLY from the numbered sources and cite them like [1]. If the sources do not contain the answer, say that they do not."
    prompt = f"Sources:\n{sources}\n\nQuestion: {question}"
    stages["context"] = {"system": system, "prompt": prompt, "chars": len(prompt), "note": "Retrieved text is data, not instructions."}

    if answer:
        best_overlap = max((len(set(q_terms) & set(d)) for d in docs), default=0)
        if not top or (best_overlap == 0 and (not top or float(cos[int(top[0].chunk_id)]) < 0.05)):
            stages["answer"] = {"method": "none", "text": "The document does not seem to contain an answer to this question.", "citations": [], "found": False}
        elif k.llm.available:
            with track_usage() as u:
                t1 = time.perf_counter()
                text_out = k.llm.generate(system, prompt, 0.0, 400)
            cited = sorted({int(m) for m in re.findall(r"\[(\d+)\]", text_out) if 1 <= int(m) <= len(top)})
            stages["answer"] = {"method": f"llm ({k.llm.name})", "text": text_out, "citations": [{"n": n, "location": top[n - 1].location, "chunk": int(top[n - 1].chunk_id) + 1} for n in cited], "found": True,
                                "uncited": not cited, "usage": u.as_dict(), "ms": round((time.perf_counter() - t1) * 1000)}
        else:
            qs = set(q_terms)
            cand = [(len(qs & {stem(t) for t in tokenize(s)}), n, s) for n, h in enumerate(top, 1) for s in _sentences(h.text)]
            cand = [c for c in cand if c[0] > 0]
            cand.sort(key=lambda c: (-c[0], c[1]))
            pick = cand[:2]
            stages["answer"] = {"method": "extractive (no LLM configured: the best matching sentences are quoted, nothing is generated)", "text": " ".join(f"{s} [{n}]" for _, n, s in pick) if pick else "The document does not seem to contain an answer to this question.",
                                "citations": [{"n": n, "location": top[n - 1].location, "chunk": int(top[n - 1].chunk_id) + 1} for _, n, _s in pick], "found": bool(pick)}
    stages["total_ms"] = round((time.perf_counter() - t_all) * 1000)
    return stages


# ----------------------------------------------------------------------------- LangChain
_VAR = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def template_vars(t: str) -> list[str]:
    """The variable names of a template; raises ValueError for anything but plain {name} placeholders (no attribute access, indexing or format specs)."""
    scrubbed = t.replace("{{", "").replace("}}", "")
    found = _VAR.findall(scrubbed)
    if _VAR.sub("", scrubbed).count("{") or _VAR.sub("", scrubbed).count("}"):
        raise ValueError("Templates may only use plain {name} placeholders (write {{ and }} for literal braces)")
    return list(dict.fromkeys(found))


def _jsonable(x: Any) -> Any:
    if isinstance(x, (str, int, float, bool)) or x is None:
        return x
    if isinstance(x, dict):
        return {str(a): _jsonable(b) for a, b in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(i) for i in x]
    if hasattr(x, "model_dump"):
        return _jsonable(x.model_dump())
    c = getattr(x, "content", None)
    return c if isinstance(c, str) else repr(x)[:400]


def langchain_run(k, *, system: str, template: str, variables: dict[str, str], model: str, fake_reply: str, parser: str, pattern: str, temperature: float, max_tokens: int) -> dict:
    from langchain_core.language_models.fake_chat_models import FakeListChatModel
    from langchain_core.output_parsers import CommaSeparatedListOutputParser, JsonOutputParser, StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.runnables import RunnableLambda, RunnableParallel

    from ..learn.lc import Recorder

    names = list(dict.fromkeys(template_vars(system) + template_vars(template)))
    missing = [n for n in names if n not in variables]
    if missing:
        raise ValueError(f"Give a value for: {', '.join(missing)}")
    inputs = {n: variables[n] for n in names}
    if model == "configured" and not k.llm.available:
        return {"available": False, "setup": LLM_SETUP, "chain": ["ChatPromptTemplate", "ConfiguredLLM", parser]}
    prompt = ChatPromptTemplate.from_messages([("system", system), ("human", template)])
    if model == "fake":
        mdl: Any = FakeListChatModel(responses=[fake_reply])
        mname = "FakeListChatModel (canned reply: no network, no cost)"
    else:
        def call(pv):
            msgs = pv.to_messages()
            return k.llm.generate(msgs[0].content, "\n".join(m.content for m in msgs[1:]), temperature, max_tokens)
        mdl, mname = RunnableLambda(call).with_config(run_name="ConfiguredLLM"), k.llm.name
    parse = {"str": StrOutputParser(), "list": CommaSeparatedListOutputParser(), "json": JsonOutputParser()}[parser]
    chain = prompt | mdl | parse
    top: Any = chain
    if pattern == "parallel":
        first = names[0] if names else ""
        top = RunnableParallel(answer=chain, input_length=RunnableLambda(lambda d: len(str(d.get(first, "")))).with_config(run_name="input_length"))
    rec = Recorder()
    t0 = time.perf_counter()
    error = None
    out: Any = None
    with track_usage() as u:
        try:
            out = top.invoke(inputs, config={"callbacks": [rec]})
        except Exception as e:  # noqa: BLE001 - parser errors are part of what the learner should see
            error = f"{type(e).__name__}: {str(e)[:300]}"
    return {"available": True, "pattern": pattern, "model": mname, "chain": [type(s).__name__ for s in chain.steps], "inputs": inputs, "steps": rec.steps, "output": _jsonable(out), "error": error,
            "latency_ms": round((time.perf_counter() - t0) * 1000), "usage": u.as_dict()}
