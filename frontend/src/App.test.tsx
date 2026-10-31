import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { setToken } from "./api";
import { Login } from "./Login";
import { ReportView } from "./Evaluation";
import { mockFetch } from "./testutil";
import type { EvalReport } from "./types";

beforeEach(() => setToken(null));
afterEach(() => vi.unstubAllGlobals());

const EMPTY = { "/sources": { body: [] }, "/jobs": { body: [] }, "/conversations": { body: [] }, "/reports": { body: [] } };
const health = (auth: boolean) => ({ status: "ok", version: "2", embedder: "hash", llm: "none", vector_store: "local", auth_enabled: auth });

describe("App shell", () => {
  it("dev mode (auth disabled) shows a warning banner and all tabs", async () => {
    mockFetch({ "/health": { body: health(false) }, ...EMPTY });
    render(<App />);
    expect(await screen.findByText(/Development mode/)).toBeInTheDocument();
    for (const t of ["Dashboard", "Library", "Chat", "Exact search", "Compare", "Data analyst", "Reports", "History", "Learn lab", "Evaluation", "Settings", "Admin"]) expect(screen.getByRole("button", { name: t })).toBeInTheDocument();
  });

  it("requires login when auth is enabled and role-gates the tabs", async () => {
    mockFetch({
      "/health": { body: health(true) }, "POST /auth/login": { body: { access_token: "t", expires_in: 60, user: { id: "u", tenant_id: "t", email: "v@x.io", role: "user" } } },
      ...EMPTY,
    });
    render(<App />);
    await userEvent.type(await screen.findByLabelText("Email"), "v@x.io");
    await userEvent.type(screen.getByLabelText("Password"), "correct horse battery");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("button", { name: "Chat" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Admin" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Evaluation" })).toBeNull();
    expect(screen.getByRole("button", { name: "Settings" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Library" }));
    expect(screen.queryByLabelText("Upload documents")).toBeNull();      // plain users cannot ingest
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
  });

  it("validates the workspace id", async () => {
    mockFetch({ "/health": { body: health(false) }, ...EMPTY });
    render(<App />);
    const ws = await screen.findByLabelText("Workspace");
    await userEvent.clear(ws);
    await userEvent.type(ws, "bad id!{enter}");
    expect(ws).toHaveValue("default");
  });
});

describe("Login", () => {
  it("shows the server error for bad credentials", async () => {
    mockFetch({ "POST /auth/login": { status: 401, body: { detail: "Invalid email or password" } } });
    render(<Login onUser={() => {}} allowSignup />);
    await userEvent.type(screen.getByLabelText("Email"), "a@b.io");
    await userEvent.type(screen.getByLabelText("Password"), "wrongpassword");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid email or password");
  });

  it("can switch to sign-up and enforces the password length hint", async () => {
    render(<Login onUser={() => {}} allowSignup />);
    await userEvent.click(screen.getByRole("button", { name: /Sign up/ }));
    expect(screen.getByLabelText("Organisation name")).toBeInTheDocument();
    expect(screen.getByText(/at least 10 characters/)).toBeInTheDocument();
  });
});

describe("Evaluation report", () => {
  it("renders headline metrics, per-type table, comparison and failures", () => {
    const rep: EvalReport = {
      id: "r1", name: "Sample", dataset: "synthetic", created: "2026-01-01", duration_s: 1, config: { embedder: "hash:v1:1024", llm: "none", vector_store: "local" },
      metrics: {
        cases: 42, retrieval: { "recall@1": 0.9, "recall@3": 0.9, "recall@5": 0.909, "precision@1": 0.9, "precision@3": 0.3, "precision@5": 0.18, "ndcg@1": 0.9, "ndcg@3": 0.9, "ndcg@5": 0.9, mrr: 0.909 },
        answers: { route_accuracy: 1, "faithfulness_lexical (proxy)": 0.89, "answer_relevancy_embedding (proxy)": 0.26, citation_accuracy: 0.97 }, latency_ms: { p50: 10, p95: 29 },
        agents: { execution_success_rate: 1, cases_with_agent_failure: 0, verified_rate: 0.9, tool_calls: 41, failed_tool_calls: 2, failed_tool_call_rate: 0.049, cases_with_invalid_citations: 0 },
        tokens: { prompt: 0, completion: 0, embedding: 0, per_query: 0, estimated: false }, cost_usd: { total: 0, per_query: 0 },
        by_type: { semantic: { cases: 21, correct: 0.9, "recall@5": 0.9, mrr: 0.9, route_accuracy: 1, latency_p50_ms: 9 } },
      },
      failures: [{ id: "h01", question: "How much vacation time?", why: ["no relevant passage in top 5"] }], notes: ["Proxy metrics are not RAGAS"],
      comparison: [{ strategy: "hybrid", "recall@5": 0.86, "precision@5": 0.17, mrr: 0.83, "ndcg@5": 0.84, p50_ms: 8, p95_ms: 29, cost_per_query: 0 }], cases: [],
    };
    render(<ReportView rep={rep} />);
    expect(screen.getByText("90.9%", { selector: "b" })).toBeInTheDocument();
    expect(screen.getByText("Faithfulness*")).toBeInTheDocument();
    expect(screen.getByText("10 / 29 ms")).toBeInTheDocument();
    expect(screen.getByText("hybrid")).toBeInTheDocument();
    expect(screen.getByText("Citation accuracy")).toBeInTheDocument();
    expect(screen.getByText("2 / 41")).toBeInTheDocument();
    expect(screen.getByText("Agent execution success")).toBeInTheDocument();
    expect(screen.getByText(/no relevant passage in top 5/)).toBeInTheDocument();
    expect(screen.getAllByRole("img", { name: /%/ }).length).toBeGreaterThan(5);
  });
});

describe("Backend unreachable", () => {
  it("keeps the interface open with a retry banner instead of blocking it", async () => {
    mockFetch({ "/health": { status: 500, body: null } });
    render(<App />);
    expect(await screen.findByText(/Backend is not reachable/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Library" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry now" })).toBeInTheDocument();
  });
});
