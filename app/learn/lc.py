"""LangChain lab. The platform itself is built directly on LangGraph; this module shows the same ideas with real `langchain_core` objects running on YOUR documents:
retriever -> prompt -> model -> parser (LCEL), tool schemas, structured output parsing, callbacks and message history. Nothing here is mocked: the
objects are langchain_core's own. The "model" is the configured LLM when there is one, otherwise a deterministic extractive function (so it works offline)."""
from __future__ import annotations

import re
import time
from typing import Any, Optional

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.documents import Document
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage, HumanMessage, trim_messages
from langchain_core.output_parsers import PydanticOutputParser, StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.retrievers import BaseRetriever
from langchain_core.runnables import RunnableLambda, RunnablePassthrough
from langchain_core.tools import StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel, Field, ValidationError

from ..agents.common import best_sentences
from ..tools.exact import exact_search


class MkaRetriever(BaseRetriever):
    """This project's whole retrieval pipeline (hybrid, rerank, parent-child, ...) exposed as a LangChain retriever."""

    pipeline: Any
    store: Any
    opts: Any
    source_ids: Optional[list[str]] = None

    def _get_relevant_documents(self, query: str, *, run_manager=None) -> list[Document]:
        res = self.pipeline.retrieve(self.store, query, self.opts, self.source_ids, None, None)
        return [Document(page_content=h.llm_text, metadata={"source": h.source, "location": h.location, "score": round(h.score, 3), "chunk_id": h.chunk_id}) for h in res.hits]


class Recorder(BaseCallbackHandler):
    """Records every runnable / retriever / tool start and end - the same hook LangSmith and OpenTelemetry integrations use."""

    def __init__(self):
        self.steps: list[dict] = []
        self._open: dict = {}

    @staticmethod
    def _p(v: Any, n: int = 220) -> str:
        t = v if isinstance(v, str) else repr(v)
        t = " ".join(t.split())
        return t if len(t) <= n else t[: n - 1] + "…"

    def _start(self, kind, serialized, payload, run_id, kwargs):
        name = kwargs.get("name") or (serialized or {}).get("name") or (serialized or {}).get("id", ["?"])[-1]
        self._open[run_id] = {"kind": kind, "name": name, "input": self._p(payload), "t0": time.perf_counter()}

    def _end(self, run_id, out):
        s = self._open.pop(run_id, None)
        if s:
            self.steps.append({"kind": s["kind"], "name": s["name"], "input": s["input"], "output": self._p(out), "ms": round((time.perf_counter() - s["t0"]) * 1000, 1)})

    def on_chain_start(self, serialized, inputs, *, run_id, **kw):
        self._start("chain", serialized, inputs, run_id, kw)

    def on_chain_end(self, outputs, *, run_id, **kw):
        self._end(run_id, outputs)

    def on_retriever_start(self, serialized, query, *, run_id, **kw):
        self._start("retriever", serialized, query, run_id, kw)

    def on_retriever_end(self, documents, *, run_id, **kw):
        self._end(run_id, f"{len(documents)} documents: " + "; ".join(f"{d.metadata.get('source')} {d.metadata.get('location')}" for d in documents[:4]))

    def on_tool_start(self, serialized, input_str, *, run_id, **kw):
        self._start("tool", serialized, input_str, run_id, kw)

    def on_tool_end(self, output, *, run_id, **kw):
        self._end(run_id, output)


class Verdict(BaseModel):
    """The shape we ask a model to return (and validate)."""

    supported: bool = Field(description="is the answer supported by the context")
    reason: str = Field(description="one short sentence")


class ExactArgs(BaseModel):
    term: str = Field(min_length=1, max_length=200, description="literal name, ID or phrase to count")
    whole_word: bool = True


CODE = {
    "retriever": '''class MkaRetriever(BaseRetriever):
    pipeline: Any; store: Any; opts: Any
    def _get_relevant_documents(self, query, *, run_manager=None):
        res = self.pipeline.retrieve(self.store, query, self.opts, self.source_ids, None, None)
        return [Document(page_content=h.llm_text, metadata={"source": h.source, "location": h.location}) for h in res.hits]''',
    "chain": '''prompt = ChatPromptTemplate.from_messages([("system", "Answer using ONLY the context. Cite as [n].\\nContext:\\n{context}"), ("human", "{question}")])
chain = (
    {"context": retriever | RunnableLambda(format_docs), "question": RunnablePassthrough()}
    | prompt
    | RunnableLambda(model)          # your LLM here (ChatOpenAI(...) in a real LangChain app)
    | StrOutputParser()
)
answer = chain.invoke(question, config={"callbacks": [Recorder()]})''',
    "tool": '''tool = StructuredTool.from_function(func=count_term, name="exact_search", description="Count a literal term", args_schema=ExactArgs)
schema = convert_to_openai_tool(tool)        # what a chat model receives to decide on a call
tool.invoke({"term": "Anjali Rao"})           # arguments are validated BEFORE the function runs''',
    "parser": '''parser = PydanticOutputParser(pydantic_object=Verdict)
parser.get_format_instructions()              # tells the model the exact JSON shape
parser.parse('{"supported": true, "reason": "number appears in the evidence"}')   # -> Verdict(...)
parser.parse("looks fine to me")              # -> OutputParserException''',
    "memory": '''turns = [HumanMessage(q1), AIMessage(a1), HumanMessage(q2), AIMessage(a2)]
trim_messages(turns, max_tokens=2, token_counter=len, strategy="last", start_on="human")   # a sliding window of recent turns''',
}


def run_demo(pipeline, k, st, question: str, opts, source_ids: Optional[list[str]], term: Optional[str] = None) -> dict:
    out: dict = {"llm_used": bool(k.llm.available), "code": CODE}
    retriever = MkaRetriever(pipeline=pipeline, store=st, opts=opts, source_ids=source_ids)
    rec = Recorder()

    # 1 - retriever
    docs = retriever.invoke(question, config={"callbacks": [rec]})
    out["retriever"] = {"documents": [{"source": d.metadata["source"], "location": d.metadata["location"], "score": d.metadata["score"], "text": " ".join(d.page_content.split())[:300]} for d in docs]}

    # 2 - LCEL chain
    def format_docs(ds: list[Document]) -> str:
        return "\n".join(f"[{i}] {' '.join(d.page_content.split())[:400]} ({d.metadata['source']}, {d.metadata['location']})" for i, d in enumerate(ds, 1))

    prompt = ChatPromptTemplate.from_messages([("system", "Answer using ONLY the context. Cite as [n]. If the context does not contain the answer, say you could not verify it.\nContext:\n{context}"), ("human", "{question}")])

    def model(pv) -> str:
        msgs = pv.to_messages()
        if k.llm.available:
            return k.llm.complete(msgs[0].content, msgs[1].content)
        ctx = [{"text": d.page_content, "context": d.page_content, "source": d.metadata["source"], "location": d.metadata["location"], "i": i} for i, d in enumerate(docs, 1)]
        picks = best_sentences(ctx, question, 2) if ctx else []
        return " ".join(f"{s} [{e['i']}]" for e, s in picks) or "I could not verify an answer from the retrieved passages."

    chain = ({"context": retriever | RunnableLambda(format_docs).with_config(run_name="format_docs"), "question": RunnablePassthrough()} | prompt
             | RunnableLambda(model).with_config(run_name="model" + ("(llm)" if k.llm.available else "(extractive, no LLM configured)")) | StrOutputParser())
    chain_rec = Recorder()
    answer = chain.invoke(question, config={"callbacks": [chain_rec]})
    rendered = prompt.invoke({"context": format_docs(docs), "question": question}).to_string()
    out["chain"] = {"answer": answer, "prompt": rendered[:2500], "steps": chain_rec.steps, "graph_ascii": _ascii(chain)}

    # 3 - tool
    t = term or _guess_term(question)

    def count_term(term: str, whole_word: bool = True) -> str:
        r = exact_search(st.iter_units(source_ids or [m["id"] for m in st.list_sources()]), term, whole_word=whole_word, max_excerpts=3)
        return f"{r.count} occurrence(s) of '{term}' in {r.units_with_match} location(s)"

    tool = StructuredTool.from_function(func=count_term, name="exact_search", description="Count a literal term in the complete extracted text", args_schema=ExactArgs)
    tool_rec = Recorder()
    result = tool.invoke({"term": t}, config={"callbacks": [tool_rec]})
    try:
        tool.invoke({"term": ""})
        invalid = "(no error?)"
    except (ValidationError, ValueError) as e:
        invalid = str(e).splitlines()[0][:200]
    out["tool"] = {"term": t, "schema": convert_to_openai_tool(tool), "result": result, "steps": tool_rec.steps, "invalid_call_rejected": invalid}

    # 4 - parser
    parser = PydanticOutputParser(pydantic_object=Verdict)
    good = parser.parse('{"supported": true, "reason": "the number appears in the evidence"}')
    try:
        parser.parse("looks fine to me")
        bad = "(parsed?)"
    except OutputParserException as e:
        bad = str(e).splitlines()[0][:200]
    out["parser"] = {"format_instructions": parser.get_format_instructions()[:700], "parsed": good.model_dump(), "malformed_output_error": bad}

    # 5 - message history
    turns = [HumanMessage("What is the leave policy?"), AIMessage("Employees accrue 25 days of annual leave [1]."), HumanMessage(question), AIMessage(answer[:300])]
    window = trim_messages(turns, max_tokens=2, token_counter=len, strategy="last", start_on="human")  # keep the last 2 messages (token_counter=len counts messages)
    out["memory"] = {"messages": [{"type": m.type, "content": m.content[:200]} for m in turns], "kept_by_window": [{"type": m.type, "content": m.content[:120]} for m in window]}
    return out


def _guess_term(question: str) -> str:
    m = re.search(r"[\"“']([^\"”']{2,})[\"”']", question)
    if m:
        return m.group(1)
    lead = {"Ask", "Does", "Show", "Find", "Who", "What", "How", "When", "Where", "Why", "Which", "Is", "Are", "Tell", "Explain", "Do", "Can", "List", "Search"}
    for c in re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+", question):
        words = [w for w in c.split() if w not in lead] if c.split()[0] in lead else c.split()
        if len(words) >= 2 or (words and c.split()[0] not in lead):
            return " ".join(words)
    words = sorted(re.findall(r"\w{4,}", question), key=len, reverse=True)
    return words[0] if words else question[:20]


def _ascii(chain) -> str:
    try:
        return chain.get_graph().draw_ascii()
    except Exception:  # drawing needs optional grandalf; the structure is still described by the steps
        return ""
