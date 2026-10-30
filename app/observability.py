"""Observability: Prometheus metrics (per-app registry), OpenTelemetry spans and LangSmith wiring.

* Metrics are exposed by GET /metrics. The registry belongs to the application instance, so tests and multiple apps never clash.
* Tracing uses OpenTelemetry. With MKA_OTEL_ENDPOINT set, spans are exported over OTLP/gRPC; without it the tracer is a no-op.
  Tests inject an in-memory exporter.
* LangSmith is configured only through environment variables (LANGSMITH_*), which LangGraph/LangChain read themselves. That path is NOT
  exercised by the test-suite (no network access to LangSmith from the build environment); the code only sets the variables."""
from __future__ import annotations

import contextlib
import logging
import os
import time
from typing import Iterator, Optional

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram, generate_latest

from .config import Settings

log = logging.getLogger("mka.obs")
LAT = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120)


class Metrics:
    def __init__(self):
        r = self.registry = CollectorRegistry()
        self.http = Counter("mka_http_requests_total", "HTTP requests", ["method", "route", "status"], registry=r)
        self.http_seconds = Histogram("mka_http_request_seconds", "HTTP request latency", ["route"], buckets=LAT, registry=r)
        self.questions = Counter("mka_questions_total", "Questions answered", ["route", "verified"], registry=r)
        self.node_runs = Counter("mka_agent_node_runs_total", "Agent node executions", ["node", "outcome"], registry=r)  # ok | error | timeout
        self.node_seconds = Histogram("mka_agent_node_seconds", "Agent node latency", ["node"], buckets=LAT, registry=r)
        self.tool_calls = Counter("mka_tool_calls_total", "Tool calls", ["tool", "outcome"], registry=r)  # ok | declined (expected refusal) | error (failure)
        self.tokens = Counter("mka_llm_tokens_total", "LLM/embedding tokens", ["kind"], registry=r)
        self.cost = Counter("mka_llm_cost_usd_total", "Estimated LLM cost in USD", registry=r)
        self.citations = Counter("mka_citations_total", "Citations returned by verification result", ["status"], registry=r)  # valid | invalid | unchecked
        self.ingest = Counter("mka_ingest_total", "Ingestion outcomes", ["outcome"], registry=r)  # ready | duplicate | failed
        self.ingest_seconds = Histogram("mka_ingest_seconds", "Ingestion duration", buckets=LAT + (300, 600), registry=r)
        self.maintenance = Counter("mka_maintenance_runs_total", "Scheduled/manual maintenance task runs", ["task", "outcome"], registry=r)
        self.up = Gauge("mka_build_info", "Build information", ["version"], registry=r)

    def render(self) -> bytes:
        return generate_latest(self.registry)

    content_type = CONTENT_TYPE_LATEST


class Observability:
    def __init__(self, settings: Settings, tracer_provider=None):
        self.settings = settings
        self.metrics = Metrics()
        self._provider = tracer_provider
        self._exporter_started = False
        self.tracer = self._make_tracer()
        setup_langsmith(settings)

    def _make_tracer(self):
        from opentelemetry import trace

        if self._provider is None and self.settings.otel_endpoint:
            try:
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
                from opentelemetry.sdk.resources import Resource
                from opentelemetry.sdk.trace import TracerProvider
                from opentelemetry.sdk.trace.export import BatchSpanProcessor

                self._provider = TracerProvider(resource=Resource.create({"service.name": self.settings.otel_service_name}))
                self._provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=self.settings.otel_endpoint, insecure=self.settings.otel_endpoint.startswith("http://"))))
            except Exception as e:  # tracing must never take the API down
                log.warning("OpenTelemetry export disabled: %s", e)
        return self._provider.get_tracer("mka") if self._provider is not None else trace.get_tracer("mka-noop")

    @contextlib.contextmanager
    def span(self, name: str, **attrs) -> Iterator[object]:
        with self.tracer.start_as_current_span(name) as sp:
            for k, v in attrs.items():
                if v is not None:
                    sp.set_attribute(f"mka.{k}", v if isinstance(v, (bool, int, float)) else str(v))
            try:
                yield sp
            except Exception as e:
                sp.record_exception(e)
                from opentelemetry.trace import Status, StatusCode

                sp.set_status(Status(StatusCode.ERROR, type(e).__name__))
                raise

    @contextlib.contextmanager
    def timed(self, hist, *labels) -> Iterator[None]:
        t0 = time.perf_counter()
        try:
            yield
        finally:
            (hist.labels(*labels) if labels else hist).observe(time.perf_counter() - t0)

    def record_usage(self, usage: Optional[dict]) -> None:
        if not usage:
            return
        for k in ("prompt_tokens", "completion_tokens", "embed_tokens"):
            if usage.get(k):
                self.metrics.tokens.labels(k.replace("_tokens", "")).inc(usage[k])
        if usage.get("cost_usd"):
            self.metrics.cost.inc(usage["cost_usd"])

    def record_answer(self, resp) -> None:
        m = self.metrics
        m.questions.labels(resp.route.split("+")[0], str(bool(resp.verified)).lower()).inc()
        ck = (resp.details or {}).get("citation_check")
        if ck:
            m.citations.labels("valid").inc(ck["valid"])
            m.citations.labels("invalid").inc(len(ck["invalid"]))
            m.citations.labels("unchecked").inc(ck["unchecked"])
        self.record_usage(resp.usage)

    def shutdown(self) -> None:
        if self._provider is not None and hasattr(self._provider, "shutdown") and self.settings.otel_endpoint:
            with contextlib.suppress(Exception):
                self._provider.shutdown()


def setup_langsmith(s: Settings) -> bool:
    """Enable LangSmith tracing via its documented environment variables. Returns whether it was enabled. (Not tested against the live service.)"""
    key = s.secret("langsmith_api_key") if hasattr(s, "secret") else None
    if not key:
        return False
    os.environ.setdefault("LANGSMITH_TRACING", "true")
    os.environ.setdefault("LANGSMITH_API_KEY", key)
    os.environ.setdefault("LANGSMITH_PROJECT", s.langsmith_project)
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")  # legacy names still read by older langchain/langgraph releases
    os.environ.setdefault("LANGCHAIN_API_KEY", key)
    os.environ.setdefault("LANGCHAIN_PROJECT", s.langsmith_project)
    return True
