"""Typed tool registry (tool calling). Agents - and, in LLM supervisor mode, the model's JSON tool selections - can only reach the
system through these validated, whitelisted functions. There is deliberately no tool that executes code, SQL or shell commands."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field, ValidationError

from ..ingestion import web as webfetch
from ..rag.options import MetadataFilter
from ..tools import tabular as tab
from ..tools.exact import exact_search
from ..tools.summarise import summarise_chunks


class ExactArgs(BaseModel):
    term: str = Field(min_length=1, max_length=200)
    case_sensitive: bool = False
    whole_word: bool = True


class SearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=6, ge=1, le=30)
    filters: Optional[MetadataFilter] = None


class TableArgs(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


class SummarizeArgs(BaseModel):
    source_ids: list[str] = Field(min_length=1, max_length=50)


class FetchArgs(BaseModel):
    url: str = Field(min_length=8, max_length=2048)


class ListArgs(BaseModel):
    pass


@dataclass
class Tool:
    name: str
    description: str
    args: type[BaseModel]
    fn: Callable[..., Any]


class ToolError(Exception):
    pass


class ToolRegistry:
    def __init__(self, assistant):
        self.a = assistant
        self.tools: dict[str, Tool] = {}
        for t in (
            Tool("exact_search", "Literal search over the complete extracted corpus with occurrence counts", ExactArgs, self._exact),
            Tool("hybrid_search", "Advanced-RAG retrieval (semantic + keyword, rerank, corrective)", SearchArgs, self._search),
            Tool("table_query", "Controlled pandas operations over CSV/Excel tables", TableArgs, self._table),
            Tool("summarize", "Hierarchical map-reduce summary of whole sources", SummarizeArgs, self._summarize),
            Tool("fetch_url", "Fetch and extract a public web page (SSRF-guarded)", FetchArgs, self._fetch),
            Tool("list_sources", "List the documents visible to the caller", ListArgs, self._list),
        ):
            self.tools[t.name] = t

    def specs(self) -> list[dict]:
        return [{"name": t.name, "description": t.description, "parameters": t.args.model_json_schema()} for t in self.tools.values()]

    def call(self, name: str, ctx, **args):
        t = self.tools.get(name)
        if t is None:
            raise ToolError(f"unknown tool '{name}'")
        m = self.a.k.obs.metrics.tool_calls
        try:
            parsed = t.args(**args)
        except ValidationError as e:
            m.labels(name, "error").inc()
            raise ToolError(f"invalid arguments for {name}: {e.errors()[0]['msg']}") from e
        try:
            with self.a.k.obs.span(f"tool.{name}"):
                out = t.fn(ctx, parsed)
        except tab.PlanError:  # expected outcome ("which column did you mean?", "this is not a table question"): the agent handles it, it is not a tool failure
            m.labels(name, "declined").inc()
            raise
        except Exception:
            m.labels(name, "error").inc()
            raise
        m.labels(name, "ok").inc()
        return out

    # ------------------------------------------------------------------ implementations
    def _exact(self, ctx, a: ExactArgs):
        k = self.a.k
        metas = ctx.sources(k)
        return exact_search(k.store(ctx.scope).iter_units([m["id"] for m in metas]), a.term, case_sensitive=a.case_sensitive, whole_word=a.whole_word,
                            max_excerpts=k.settings.max_excerpts), metas

    def _search(self, ctx, a: SearchArgs):
        from dataclasses import replace

        k = self.a.k
        metas = ctx.sources(k)
        o = replace(ctx.opts, top_k=a.top_k, filters=a.filters or ctx.opts.filters)
        last = (ctx.last or {}).get("question")
        return self.a.pipeline.retrieve(k.store(ctx.scope), a.query, o, [m["id"] for m in metas], last, ctx.summary)

    def _table(self, ctx, a: TableArgs):
        k = self.a.k
        metas = [m for m in ctx.sources(k) if m.get("tabular")]
        if not metas:
            raise ToolError("no CSV/Excel sources")
        tables = tab.load_tables(k.store(ctx.scope), metas)
        try:
            return tab.analyse(tables, a.question, k.llm)
        except tab.NotTabular:
            raise
        except tab.PlanError:
            if not k.llm.available:
                raise
            from ..analytics.nlsql import answer_with_sql

            return answer_with_sql(tables, a.question, k.llm)  # validated read-only SQL in the sandbox

    def _summarize(self, ctx, a: SummarizeArgs):
        k, st = self.a.k, self.a.k.store(ctx.scope)
        out = []
        for sid in a.source_ids:
            m = st.get_source(sid, ctx.principal)
            if m:
                text, _ = summarise_chunks(st.load_chunks(sid), k.llm if k.llm.available else None)
                out.append((m, text))
        return out

    def _fetch(self, ctx, a: FetchArgs):
        final, ctype, body = webfetch.fetch(a.url, self.a.k.settings, self.a.k.url_transport)
        return final, webfetch.extract_html(final, ctype, body)

    def _list(self, ctx, a: ListArgs):
        return ctx.sources(self.a.k)
