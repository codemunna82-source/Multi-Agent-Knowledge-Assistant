import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockFetch, sse } from "../testutil";
import { resetCodeStatus } from "./CodeLab";
import { Playground } from "./Playground";

vi.mock("./CodeEditor", () => ({ default: ({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) => <textarea aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} /> }));
afterEach(() => { vi.unstubAllGlobals(); resetCodeStatus(); });

const caps = (llm = true) => ({ llm: { available: llm, name: llm ? "openai:gpt-4o-mini" : null, setup: llm ? null : "Set MKA_LLM_PROVIDER=openai and OPENAI_API_KEY" },
  embedder: { name: "hash:v1:1024", dim: 1024, semantic: false, note: "The built-in 'hash' embedder measures shared WORDS, not meaning." }, cross_encoder: { available: false, model: "ce", setup: "pip install sentence-transformers" },
  code_runner: { available: true, reason: null }, limits: { max_tokens: 1000 } });
const req = (init: RequestInit) => JSON.parse(String(init.body));
const setup = (extra: Record<string, unknown> = {}, llm = true) => mockFetch({ "/academy/playground/capabilities": { body: caps(llm) }, ...extra });
async function open(tab: string, llm = true, extra: Record<string, unknown> = {}) {
  const f = setup(extra, llm);
  render(<Playground workspace="w" />);
  await screen.findByLabelText("What is available on this server");
  await userEvent.click(screen.getByRole("tab", { name: tab }));
  return f;
}

describe("Playground", () => {
  it("shows honestly what is configured", async () => {
    setup({}, false);
    render(<Playground workspace="w" />);
    const list = await screen.findByLabelText("What is available on this server");
    expect(within(list).getByText(/No language model configured/)).toBeInTheDocument();
    expect(within(list).getByText(/word overlap, not meaning/)).toBeInTheDocument();
    expect(within(list).getByText(/Cross-encoder not installed/)).toBeInTheDocument();
  });

  it("LLM: streams tokens into the output and shows tokens, first-token time and latency", async () => {
    const { calls } = await open("LLM", true, { "/llm/stream": { stream: [sse("token", { text: "An embedding " }), sse("token", { text: "is a vector." }), sse("done", { model: "openai:gpt-4o-mini", usage: { prompt_tokens: 20, completion_tokens: 6 }, latency_ms: 812, first_token_ms: 240, chunks: 2 })] } });
    await userEvent.click(screen.getByRole("button", { name: /Run/ }));
    expect(await screen.findByText("An embedding is a vector.")).toBeInTheDocument();
    expect(await screen.findByText(/first token after 240 ms/)).toBeInTheDocument();
    expect(screen.getByText(/20 prompt \+ 6 completion tokens/)).toBeInTheDocument();
    expect(req(calls.find((c) => c.url.endsWith("/llm/stream"))!.init)).toMatchObject({ temperature: 0.7, max_tokens: 200 });
  });

  it("LLM without a model shows setup and the exact request instead of an invented answer", async () => {
    await open("LLM", false, { "/llm/stream": { stream: [sse("unavailable", { setup: "Set MKA_LLM_PROVIDER", request: { messages: [{ role: "user", content: "hi" }], temperature: 0.7, max_tokens: 200 } })] } });
    await userEvent.click(screen.getByRole("button", { name: /Run/ }));
    expect(await screen.findByText(/A language model is not configured/)).toBeInTheDocument();
    expect(screen.getByText(/"max_tokens": 200/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Model output")).not.toBeInTheDocument();
  });

  it("LLM non-streaming mode uses the plain endpoint with the chosen parameters", async () => {
    const { calls } = await open("LLM", true, { "POST /academy/playground/llm": { body: { available: true, text: "Hello!", model: "m", latency_ms: 50, usage: { prompt_tokens: 3, completion_tokens: 2 }, request: {} } } });
    await userEvent.click(screen.getByLabelText("Stream token by token"));
    await userEvent.clear(screen.getByLabelText("Max tokens"));
    await userEvent.type(screen.getByLabelText("Max tokens"), "55");
    await userEvent.click(screen.getByRole("button", { name: /Run/ }));
    expect(await screen.findByText("Hello!")).toBeInTheDocument();
    expect(req(calls.find((c) => c.url.endsWith("/playground/llm") && c.init.method === "POST")!.init).max_tokens).toBe(55);
  });

  it("Prompt engineering: fills few-shot templates, compares outputs and shows the differences", async () => {
    const { calls } = await open("Prompt engineering", true, { "/prompts/compare": { body: { available: true, model: "m", variants: [
      { name: "zero-shot", text: "The sentiment is mixed, leaning negative because of the price.", words: 10, latency_ms: 200, usage: { prompt_tokens: 30, completion_tokens: 12 }, request: {} },
      { name: "few-shot", text: "neutral", words: 1, latency_ms: 150, usage: { prompt_tokens: 90, completion_tokens: 1 }, request: {}, similarity_to_first: 0.05, only_here: ["neutral"], missing_vs_first: ["sentiment"] }] } } });
    await userEvent.click(screen.getByRole("button", { name: "Variant 1: one-shot template" }));
    expect((document.getElementById("pv-p0") as HTMLTextAreaElement).value).toContain("Sentiment: negative");
    await userEvent.click(screen.getByRole("button", { name: /Run and compare/ }));
    const res = await screen.findByLabelText("Comparison results");
    expect(within(res).getByText(/Similarity to the first output/)).toHaveTextContent("5%");
    expect(within(res).getByText(/Similarity to the first output/)).toHaveTextContent("only here: neutral");
    const body = req(calls.find((c) => c.url.endsWith("/prompts/compare"))!.init);
    expect(body.variants).toHaveLength(2);
    expect(body.variants[0].prompt).toContain("Sentiment: negative");
  });

  it("Embeddings: shows dimensions, the ranking and the similarity matrix, plus the hash-embedder warning", async () => {
    await open("Embeddings", true, { "POST /academy/playground/embeddings": { body: { embedder: "hash:v1:1024", semantic: false, note: "The built-in 'hash' embedder measures shared WORDS.", dim: 1024, latency_ms: 4, texts: ["a", "b", "c"], vectors: [{ first_values: [0.1], norm: 1 }, { first_values: [0.2], norm: 1 }, { first_values: [0.3], norm: 1 }], similarity: [[1, 0.8, 0.1], [0.8, 1, 0.2], [0.1, 0.2, 1]], ranking_vs_first: [{ index: 1, text: "b", cosine: 0.8 }, { index: 2, text: "c", cosine: 0.1 }] } } });
    await userEvent.click(screen.getByRole("button", { name: "Generate embeddings" }));
    expect(await screen.findByText(/numbers per vector/)).toHaveTextContent("1024");
    const rank = screen.getByRole("table", { name: "Similarity to the first sentence" });
    expect(within(rank).getAllByRole("row")[0]).toHaveTextContent("0.80");
    expect(screen.getByRole("table", { name: "Cosine similarity matrix" })).toBeInTheDocument();
    expect(screen.getAllByText(/measures shared WORDS/).length).toBeGreaterThan(0);
  });

  it("RAG: sends the form, shows every stage and the before/after reranking", async () => {
    const run = { extract: { file: "pasted.txt", units: 1, chars: 239, preview: "Employees accrue…", warnings: [] },
      chunks: { count: 3, size: 120, overlap: 20, lengths: [120, 118, 60], items: [{ id: 1, location: "document", chars: 120, text: "Employees accrue 25 days" }], truncated_list: false },
      embed: { embedder: "hash:v1:1024", dim: 1024, ms: 3, semantic: false, note: "word overlap" }, store: { vectors: 3, bytes: 24576, persisted: false, note: "In memory only." },
      search: { mode: "hybrid", candidates: 3, top: [{ rank: 1, chunk: 2, cosine: 0.31, bm25: 2.1, score: 0.0328, location: "document", text: "Parental leave is 26 weeks" }] },
      rerank: { method: "lexical (cross-encoder is not installed)", before: [3, 2], after: [2, 3], moved: [2, 3], items: [{ rank: 1, chunk: 2, rerank_score: 0.71, was_rank: 2, text: "Parental leave is 26 weeks" }] },
      context: { system: "s", prompt: "Sources:\n[1] Parental leave is 26 weeks", chars: 40 }, answer: { method: "extractive (no LLM configured)", text: "Parental leave is 26 weeks [1].", citations: [{ n: 1, location: "document", chunk: 2 }], found: true }, total_ms: 12 };
    const { calls } = await open("RAG", true, { "POST /academy/playground/rag": { body: run } });
    await userEvent.selectOptions(screen.getByLabelText("Reranking"), "cross_encoder");
    await userEvent.click(screen.getByRole("button", { name: /Run the pipeline/ }));
    const stages = await screen.findByLabelText("Pipeline stages");
    expect(within(stages).getByText(/chunks \(size 120, overlap 20\)/)).toHaveTextContent("3 chunks");
    expect(within(stages).getByText(/Reranking: lexical \(cross-encoder is not installed\)/)).toBeInTheDocument();
    expect(within(stages).getByText(/Before: chunks 3, 2/)).toBeInTheDocument();
    expect(within(stages).getByLabelText("Answer")).toHaveTextContent("Parental leave is 26 weeks [1].");
    expect(within(stages).getByText(/Citations: \[1\] chunk 2/)).toBeInTheDocument();
    expect(within(stages).getByText(/In memory only/)).toBeInTheDocument();
    const form = calls.find((c) => c.url.endsWith("/playground/rag"))!.init.body as FormData;
    expect(form.get("question")).toBe("How long is parental leave?");
    expect(form.get("rerank")).toBe("cross_encoder");
    expect(form.get("text")).toContain("Employees accrue");
    expect(form.get("file")).toBeNull();
  });

  it("RAG: an uploaded file replaces the pasted text, and server errors are shown", async () => {
    const { calls } = await open("RAG", true, { "POST /academy/playground/rag": { status: 422, body: { detail: "The playground accepts PDF, TXT, CSV and MD files" } } });
    await userEvent.upload(screen.getByLabelText("Upload a file"), new File(["x"], "notes.pdf"));
    await userEvent.click(screen.getByRole("button", { name: /Run the pipeline/ }));
    expect(await screen.findByText(/accepts PDF, TXT, CSV and MD files/)).toBeInTheDocument();
    const form = calls.find((c) => c.url.endsWith("/playground/rag"))!.init.body as FormData;
    expect((form.get("file") as File).name).toBe("notes.pdf");
    expect(form.get("text")).toBeNull();
  });

  it("LangChain: detects placeholders, runs the chain and lists each component's input and output", async () => {
    const { calls } = await open("LangChain", true, { "POST /academy/playground/langchain": { body: { available: true, pattern: "sequence", model: "FakeListChatModel", chain: ["ChatPromptTemplate", "FakeListChatModel", "StrOutputParser"], inputs: {}, latency_ms: 3, error: null, output: "Paris, France, Europe",
      steps: [{ kind: "chain", name: "ChatPromptTemplate", input: "{'role': 'teacher'}", output: "System: You are a teacher.", ms: 0.4 }, { kind: "model", name: "FakeListChatModel", input: "System: You are a teacher.", output: "Paris, France, Europe", ms: 1 }] } } });
    expect(screen.getByLabelText("Value of {role}")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Human template"), { target: { value: "{question} Answer in {language}." } });
    expect(await screen.findByLabelText("Value of {language}")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Value of {language}"), "English");
    await userEvent.click(screen.getByRole("button", { name: /Run the chain/ }));
    const comps = await screen.findByRole("table", { name: "Components" });
    expect(within(comps).getByText("ChatPromptTemplate")).toBeInTheDocument();
    expect(within(comps).getAllByText("Paris, France, Europe").length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Chain output")).toHaveTextContent("Paris, France, Europe");
    expect(req(calls.find((c) => c.url.endsWith("/playground/langchain"))!.init).variables).toEqual({ role: "geography teacher", question: "What is the capital of France?", language: "English" });
  });

  it("LangChain: edited sample code runs in the sandbox", async () => {
    const { calls } = await open("LangChain", true, { "/academy/code/status": { body: { available: true, reason: null, languages: ["python"], timeout_s: 10, memory_mb: 1536, network: false, setup: null, preinstalled: [], limits: { code_bytes: 1, output_bytes: 1 } } },
      "POST /academy/code/run": { body: { ok: true, stdout: "Paris is the capital of France.\n", stderr: "", exit_code: 0, ms: 600, timed_out: false, truncated: false, unavailable: null, notes: [], error_help: null, passed: null, expected: null } } });
    await userEvent.click(screen.getByRole("tab", { name: "Edit and run code" }));
    await userEvent.click(screen.getByRole("button", { name: /Run code/ }));
    expect(await screen.findByRole("region", { name: "Output console" })).toHaveTextContent("Paris is the capital of France.");
    expect(req(calls.find((c) => c.url.endsWith("/code/run"))!.init)).toMatchObject({ language: "python", task: "scratch" });
  });

  const spec = { state: { count: "int", log: "list" }, nodes: [{ id: "work", type: "increment", key: "count", by: 1 }, { id: "note", type: "append", key: "log", value: "worked" }], edges: [["work", "note"]], conditional: [{ source: "note", key: "count", op: ">=", value: 3, then: "END", otherwise: "work" }], entry: "work" };
  const preset = (label: string, input = {}, sp = spec) => ({ label, input, spec: sp });
  const graphRun = (extra: object = {}) => ({ thread_id: "abc123", status: "finished", message: null, pending: [], ms: 5, graph: { nodes: ["__start__", "work", "note", "__end__"], edges: [["__start__", "work", false], ["work", "note", false], ["note", "work", true], ["note", "__end__", true]] },
    steps: [{ step: 1, node: "work", update: { count: 1 }, state_after: { count: 1, log: [] }, ms: 0.3 }, { step: 2, node: "note", update: { log: ["worked"] }, state_after: { count: 1, log: ["worked"] }, ms: 0.2 }],
    final_state: { count: 1, log: ["worked"] }, history: [{ step: -1, next: ["__start__"], state: {} }, { step: 2, next: [], state: { count: 1, log: ["worked"] } }], ...extra });

  it("LangGraph: loads presets, runs the graph and steps through the state changes", async () => {
    const { calls } = await open("LangGraph", true, { "/langgraph/presets": { body: { loop: preset("Loop until a check passes", { count: 0 }) } }, "POST /academy/playground/langgraph/run": { body: graphRun() } });
    await screen.findByLabelText("Node 1 id");
    await userEvent.click(screen.getByRole("button", { name: /Run the graph/ }));
    const res = await screen.findByLabelText("Run result");
    expect(within(res).getByText(/finished/)).toBeInTheDocument();
    expect(within(res).getByText(/step 1 \/ 2: node/)).toBeInTheDocument();
    expect(within(res).getByText(/● count: 1/)).toBeInTheDocument();                       // the changed key is marked
    await userEvent.click(within(res).getByRole("button", { name: /Step/ }));
    expect(within(res).getByText(/● log: \["worked"\]/)).toBeInTheDocument();
    expect(within(res).getByText(/Execution history \(2 checkpoints\)/)).toBeInTheDocument();
    expect(req(calls.find((c) => c.url.endsWith("/langgraph/run"))!.init)).toMatchObject({ input: { count: 0 }, max_steps: 15 });
  });

  it("LangGraph: editing the builder changes the spec that is sent", async () => {
    const { calls } = await open("LangGraph", true, { "/langgraph/presets": { body: { loop: preset("Loop") } }, "POST /academy/playground/langgraph/run": { body: graphRun() } });
    await userEvent.selectOptions(await screen.findByLabelText("Node 1 type"), "decrement".length ? "noop" : "noop");
    await userEvent.click(screen.getByRole("button", { name: "+ node" }));
    await userEvent.click(screen.getByLabelText("Pause before work"));
    await userEvent.click(screen.getByRole("button", { name: /Run the graph/ }));
    await screen.findByLabelText("Run result");
    const sent = req(calls.find((c) => c.url.endsWith("/langgraph/run"))!.init).spec;
    expect(sent.nodes).toHaveLength(3);
    expect(sent.nodes[0].type).toBe("noop");
    expect(sent.interrupt_before).toEqual(["work"]);
  });

  it("LangGraph: a paused run waits for approval, with optional state edits, then resumes", async () => {
    const { calls } = await open("LangGraph", true, { "/langgraph/presets": { body: { loop: preset("Loop") } },
      "POST /academy/playground/langgraph/run": { body: graphRun({ status: "paused", message: "Paused before 'send'.", pending: ["send"] }) },
      "POST /academy/playground/langgraph/resume": { body: graphRun({ status: "finished", final_state: { amount: 4200 } }) } });
    await screen.findByLabelText("Node 1 id");
    await userEvent.click(screen.getByRole("button", { name: /Run the graph/ }));
    expect(await screen.findByText(/Waiting for a person/)).toBeInTheDocument();
    const edit = screen.getByLabelText(/State changes/);
    await userEvent.clear(edit);
    await userEvent.type(edit, '{{"amount": 4200}');
    await userEvent.click(screen.getByRole("button", { name: /Approve and continue/ }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/langgraph/resume"))).toBe(true));
    expect(req(calls.find((c) => c.url.endsWith("/langgraph/resume"))!.init)).toMatchObject({ thread_id: "abc123", state_update: { amount: 4200 } });
    expect(await screen.findByText(/"amount":4200/)).toBeInTheDocument();
  });

  it("LangGraph: a safety-limit stop and invalid JSON are explained", async () => {
    await open("LangGraph", true, { "/langgraph/presets": { body: { loop: preset("Loop") } }, "POST /academy/playground/langgraph/run": { body: graphRun({ status: "limit_reached", message: "Stopped after 15 steps. A loop without a stop condition would run forever; this is the safety limit." }) } });
    await screen.findByLabelText("Node 1 id");
    await userEvent.click(screen.getByRole("button", { name: /Run the graph/ }));
    expect(await screen.findByText(/safety limit/)).toBeInTheDocument();
    const inp = screen.getByLabelText("Initial state (JSON)");
    await userEvent.clear(inp);
    await userEvent.type(inp, "not json");
    await userEvent.click(screen.getByRole("button", { name: /Run the graph/ }));
    expect(await screen.findByText(/not valid JSON/)).toBeInTheDocument();
  });

  it("Agent: only ticked tools are sent; the trace shows tool, input, result and the final answer", async () => {
    const { calls } = await open("Agentic AI", false, { "/agent/tools": { body: { calculator: "Evaluate arithmetic. Input: {}", search_documents: "Search. Input: {}", list_documents: "List. Input: {}" } },
      "POST /academy/playground/agent/run": { body: { policy: "rule-based planner (no LLM is configured, so tool choice follows simple rules)", ms: 3, note: "Steps are operational.", final: "The answer is 7200.", steps: [
        { n: 1, type: "plan", text: "Goal received." }, { n: 2, type: "tool_selected", text: "the task contains arithmetic", tool: "calculator", input: { expression: "15% of 48000" } }, { n: 3, type: "tool_result", text: "7200", tool: "calculator", ms: 0.1 }, { n: 4, type: "final", text: "The answer is 7200." }] } } });
    await screen.findByLabelText(/calculator/);
    await userEvent.click(screen.getByLabelText(/list_documents/));
    await userEvent.click(screen.getByRole("button", { name: /Run the agent/ }));
    const trace = await screen.findByLabelText("Agent trace");
    expect(within(trace).getByText(/rule-based planner/)).toBeInTheDocument();
    expect(within(trace).getByText(/calculator\(\{"expression":"15% of 48000"\}\)/)).toBeInTheDocument();
    expect(within(trace).getByLabelText("Final answer")).toHaveTextContent("The answer is 7200.");
    expect(req(calls.find((c) => c.url.endsWith("/agent/run"))!.init)).toEqual({ task: "What is 15% of 48000?", tools: ["calculator", "search_documents"], max_steps: 4 });
  });
});
