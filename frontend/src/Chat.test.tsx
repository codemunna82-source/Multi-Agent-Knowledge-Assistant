import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Chat } from "./Chat";
import { mockFetch, sse } from "./testutil";

afterEach(() => vi.unstubAllGlobals());

const base = { route: "semantic", confidence: "high", verified: true, limitations: ["No LLM configured"], needs_input: false, details: {}, usage: { prompt_tokens: 10, completion_tokens: 5, cost_usd: 0.00012 }, latency_ms: 42 };

function setup(final: object) {
  return mockFetch({
    "/conversations": { body: [] }, "/sources": { body: [{ id: "s1", name: "policy.pdf", kind: "pdf", status: "ready", tabular: false, warnings: [], needs_reindex: false, visibility: "tenant", created_at: "" }] },
    "POST /ask/stream": () => ({ stream: [sse("step", { node: "supervisor", detail: "supervisor: route=semantic" }), sse("token", { text: "Hello" }), sse("final", { response: { ...base, ...final } })] }),
  });
}

describe("Chat", () => {
  it("shows the answer with confidence, citations, limitations and follow-ups", async () => {
    setup({ answer: "Employees accrue 25 days.", conversation_id: "c1", citations: [{ source_id: "s1", source: "policy.pdf", location: "page 1", excerpt: "accrue 25 days of annual leave" }], followups: ["Summarize policy.pdf?"] });
    render(<Chat workspace="w" prefill={null} onPrefillUsed={() => {}} />);
    await userEvent.type(screen.getByLabelText("Question"), "How many leave days?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByText("Employees accrue 25 days.")).toBeInTheDocument();
    expect(screen.getByText("confidence: high")).toBeInTheDocument();
    expect(screen.getByText(/\[1\] policy\.pdf — page 1/)).toBeInTheDocument();
    expect(screen.getByText("accrue 25 days of annual leave")).toBeInTheDocument();
    expect(screen.getByText(/No LLM configured/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Summarize policy.pdf?" })).toBeInTheDocument();
    expect(screen.getByText(/42 ms · 15 tokens · \$0\.00012/)).toBeInTheDocument();
  });

  it("renders document-derived text as plain text (no HTML injection)", async () => {
    setup({ answer: '<img src=x onerror="window.__pwned=1"> <b>bold</b>', citations: [{ source_id: "s1", source: "<script>evil()</script>.pdf", location: "page 1", excerpt: "<iframe src=//evil></iframe>" }], followups: [] });
    const { container } = render(<Chat workspace="w" prefill={null} onPrefillUsed={() => {}} />);
    await userEvent.type(screen.getByLabelText("Question"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    await screen.findByText(/<img src=x/);
    expect(container.querySelector("img, iframe, script")).toBeNull();
    expect([...container.querySelectorAll("b")].some((b) => b.textContent === "bold")).toBe(false);  // "<b>bold</b>" stayed literal text
    expect((window as unknown as { __pwned?: number }).__pwned).toBeUndefined();
    expect(screen.getByText(/<script>evil\(\)<\/script>\.pdf/)).toBeInTheDocument();
  });

  it("sends the selected filters, documents and options with the question", async () => {
    const { calls } = setup({ answer: "ok", citations: [], followups: [] });
    render(<Chat workspace="w" prefill={null} onPrefillUsed={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: /Options/ }));
    await screen.findByText("policy.pdf");
    await userEvent.click(screen.getByLabelText("policy.pdf"));
    await userEvent.click(screen.getByRole("button", { name: "pdf" }));
    await userEvent.type(screen.getByLabelText("Minimum page"), "2");
    await userEvent.selectOptions(screen.getByLabelText("Retrieval mode"), "keyword");
    await userEvent.click(screen.getByLabelText("Multi-query"));
    await userEvent.type(screen.getByLabelText("Question"), "leave");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    await waitFor(() => expect(calls.some((c) => c.url.includes("/ask/stream"))).toBe(true));
    const body = JSON.parse(String(calls.find((c) => c.url.includes("/ask/stream"))!.init.body));
    expect(body.source_ids).toEqual(["s1"]);
    expect(body.retrieval).toMatchObject({ mode: "keyword", multi_query: true, filters: { kinds: ["pdf"], page_min: 2 } });
  });

  it("clicking a follow-up asks it, and server errors are shown", async () => {
    mockFetch({ "/conversations": { body: [] }, "/sources": { body: [] }, "POST /ask/stream": { status: 429, body: { detail: "Rate limit exceeded (30/minute). Retry in 5s." } } });
    render(<Chat workspace="w" prefill="preset question" onPrefillUsed={() => {}} />);
    expect(screen.getByLabelText("Question")).toHaveValue("preset question");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Rate limit exceeded");
  });

  it("loads a past conversation from history", async () => {
    mockFetch({
      "/conversations/c9/messages": { body: [{ id: 1, role: "user", content: "old q", created_at: "" }, { id: 2, role: "assistant", content: "old a", meta: { confidence: "low", route: "exact", citations: [] }, created_at: "" }] },
      "/conversations": { body: [{ id: "c9", workspace: "w", title: "Old chat", updated_at: "" }] }, "/sources": { body: [] },
    });
    render(<Chat workspace="w" prefill={null} onPrefillUsed={() => {}} />);
    await userEvent.click(await screen.findByRole("button", { name: "Old chat" }));
    expect(await screen.findByText("old a")).toBeInTheDocument();
    expect(screen.getByText("confidence: low")).toBeInTheDocument();
  });
});

describe("Chat experience", () => {
  it("reveals the answer progressively (typewriter) and can be skipped by clicking", async () => {
    const long = "Employees accrue twenty five days of annual leave per calendar year and may carry over five unused days. ".repeat(4);
    setup({ answer: long, citations: [], followups: [] });
    render(<Chat workspace="w" prefill={null} onPrefillUsed={() => {}} />);
    await userEvent.type(screen.getByLabelText("Question"), "leave?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    const first = await screen.findByText(/Employees accrue/);
    expect(first.textContent!.length).toBeLessThan(long.length);                    // mid-animation: only part of the text is visible
    await waitFor(() => expect(screen.getByText(/carry over five unused days\.\s*$/)).toBeInTheDocument(), { timeout: 3000 });
  });

  it("the Auto toggle sends retrieval.auto and the chosen strategy is explained", async () => {
    const auto = { chosen: "keyword-first", why: "the question contains a quoted phrase", candidates: [
      { name: "keyword-first", why: "exact words matter", grade: "correct", hits: 2, ms: 3, score: 9.1 }, { name: "hybrid", why: "balanced default", grade: "correct", hits: 2, ms: 4, score: 8.2 }] };
    const { calls } = setup({ answer: "ok", citations: [], followups: [], details: { plan: { auto_strategy: auto } } });
    render(<Chat workspace="w" prefill={null} onPrefillUsed={() => {}} />);
    const pill = screen.getByRole("button", { name: "Auto strategy" });
    expect(pill).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(pill);
    expect(pill).toHaveAttribute("aria-pressed", "true");
    await userEvent.type(screen.getByLabelText("Question"), 'find "INV-1"');
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByText(/Auto picked/)).toBeInTheDocument();
    expect(screen.getByText(/the question contains a quoted phrase/)).toBeInTheDocument();
    expect(JSON.parse(String(calls.find((c) => c.url.includes("/ask/stream"))!.init.body)).retrieval.auto).toBe(true);
  });

  it("shows starter prompts on an empty conversation and fills the box when one is clicked", async () => {
    setup({ answer: "x", citations: [], followups: [] });
    render(<Chat workspace="w" prefill={null} onPrefillUsed={() => {}} />);
    expect(screen.getByRole("heading", { name: /How can I help/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Summarize my documents" }));
    expect(screen.getByLabelText("Question")).toHaveValue("Summarize my documents");
  });
});
