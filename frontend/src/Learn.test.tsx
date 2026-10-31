import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { GraphDiagram } from "./GraphDiagram";
import { Learn } from "./Learn";
import { mockFetch } from "./testutil";
import type { GraphInfo, LabRow } from "./types";

afterEach(() => vi.unstubAllGlobals());

const lessons = {
  llm_available: false, embedder: "hash:v1:1024", presets: ["semantic only", "keyword only (BM25)", "hybrid (RRF)"], ablation: ["1. semantic only (bare)"], note: "",
  demo_questions: [{ q: "How many weeks of parental leave do partners get?", teaches: "a fact in a longer section" }],
  lessons: [
    { id: "rerank", group: "RAG", title: "Re-ranking", what: "A second scorer reorders candidates.", why: "Order matters.", code: "app/rag/steps.py::lexical_rerank", try: { lab: "retrieval", preset: "hybrid (RRF)" } },
    { id: "lg-parallel", group: "LangGraph", title: "Parallel branches (Send)", what: "Send fans out.", why: "Speed.", code: "app/agents/graph.py", try: { lab: "graph", preset: "parallel" } },
    { id: "lc-lcel", group: "LangChain", title: "Prompts and LCEL chains", what: "prompt | model | parser", why: "Standard wiring.", code: "app/learn/lc.py", try: { lab: "langchain" }, needs_llm: true },
  ],
};
const row = (name: string, extra: Partial<LabRow> = {}): LabRow => ({
  name, overrides: {}, grade: "correct", abstained: false, query_used: "q", attempts: 1, ms: 12, notes: [], trace: [{ step: "retrieve", mode: "hybrid" }, { step: "grade", grade: "correct", method: "heuristic" }], delta: null,
  hits: [{ rank: 1, chunk_id: "c1", source: "company_handbook.md", location: "lines 5-17", score: 0.4, lexical: 0.8, fused: 0.03, rerank: null, chars_matched: 861, chars_to_model: 861, compressed: false, excerpt: "Partners receive 4 weeks" }], ...extra,
});
const info: GraphInfo = {
  nodes: [{ id: "__start__", description: "" }, { id: "supervisor", description: "Routes the question" }, { id: "semantic", description: "Advanced RAG answer" }, { id: "verify", description: "Checks citations" }, { id: "final", description: "Builds the response" }, { id: "__end__", description: "" }],
  edges: [{ source: "__start__", target: "supervisor", conditional: false }, { source: "supervisor", target: "semantic", conditional: true }, { source: "semantic", target: "verify", conditional: false }, { source: "verify", target: "final", conditional: true },
          { source: "verify", target: "semantic", conditional: true }, { source: "final", target: "__end__", conditional: false }], mermaid: "---\nconfig: x\n---\ngraph TD;",
};

describe("Learn lab", () => {
  it("lists lessons by group and 'Try it' opens the matching lab with the preset", async () => {
    mockFetch({ "/learn/lessons": { body: lessons } });
    render(<Learn workspace="w" canIngest />);
    const rag = await screen.findByLabelText("RAG lessons");
    expect(within(rag).getByText("Re-ranking")).toBeInTheDocument();
    expect(screen.getByLabelText("LangGraph lessons")).toBeInTheDocument();
    expect(screen.getByText(/needs a model for full effect/)).toBeInTheDocument();
    expect(screen.getByText(/No language model is configured/)).toBeInTheDocument();
    await userEvent.click(within(rag).getByText("Re-ranking"));
    await userEvent.click(within(rag).getByRole("button", { name: /Try it/ }));
    expect(await screen.findByRole("button", { name: "Run experiment" })).toBeInTheDocument();
    expect(screen.getByLabelText("hybrid (RRF)")).toBeChecked();                       // the lesson's preset is pre-selected in compare mode
  });

  it("ablation shows, per added technique, what changed (passages, grade, characters sent to the model)", async () => {
    const { calls } = mockFetch({
      "POST /learn/retrieval/ablation": { body: { rows: [row("1. semantic only (bare)"),
        row("8. + contextual compression", { hits: [{ ...row("x").hits[0], chars_to_model: 658, compressed: true }], delta: { vs: "7. + parent-child context", overlap: 1, new: [], dropped: [], same_top1: true, grade_changed: null, ms_change: 1, chars_to_model_change: -203 } }),
        row("9. + corrective loop", { grade: "ambiguous", delta: { vs: "8. + contextual compression", overlap: 0.5, new: ["lines 20-30 · company_handbook.md"], dropped: ["lines 5-17 · company_handbook.md"], same_top1: false, grade_changed: "correct → ambiguous", ms_change: 3, chars_to_model_change: 0 } })] } },
      "POST /learn/demo-corpus": { body: { documents: [{ name: "a.pdf", status: "ready" }, { name: "b.md", status: "duplicate" }] } }, "/learn/lessons": { body: lessons },
    });
    render(<Learn workspace="w" canIngest />);
    await userEvent.click(await screen.findByRole("tab", { name: "Retrieval lab" }));
    await userEvent.click(screen.getByRole("button", { name: "Load demo documents" }));
    expect(await screen.findByText("Loaded 1 new, 1 already present.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "How many weeks of parental leave do partners get?" }));
    await userEvent.click(screen.getByRole("button", { name: "Run experiment" }));
    const t = await screen.findByRole("table", { name: "Experiment results" });
    expect(within(t).getByText("baseline")).toBeInTheDocument();
    expect(within(t).getByText(/-203 characters to the model/)).toBeInTheDocument();
    expect(within(t).getByText("grade correct → ambiguous")).toBeInTheDocument();
    expect(within(t).getByText(/50% same passages, different #1/)).toBeInTheDocument();
    expect(within(t).getByText(/\+ lines 20-30 · company_handbook\.md/)).toBeInTheDocument();
    expect(JSON.parse(String(calls.find((c) => c.url.includes("/ablation"))!.init.body)).question).toBe("How many weeks of parental leave do partners get?");
  });

  it("compare mode needs two settings and reports what a missing model means", async () => {
    mockFetch({ "POST /learn/retrieval/compare": { body: { rows: [row("semantic only"), row("hybrid (RRF)", { notes: ["HyDE needs a model to write the hypothetical answer"] })] } }, "/learn/lessons": { body: lessons } });
    render(<Learn workspace="w" canIngest />);
    await userEvent.click(await screen.findByRole("tab", { name: "Retrieval lab" }));
    await userEvent.click(screen.getByRole("tab", { name: "Compare settings side by side" }));
    await userEvent.click(screen.getByLabelText("keyword only (BM25)"));
    await userEvent.click(screen.getByLabelText("hybrid (RRF)"));
    expect(screen.getByRole("button", { name: "Run experiment" })).toBeDisabled();            // only one setting left
    await userEvent.click(screen.getByLabelText("keyword only (BM25)"));
    await userEvent.click(screen.getByRole("button", { name: "Run experiment" }));
    expect(await screen.findByText(/HyDE needs a model/)).toBeInTheDocument();
  });

  it("graph lab draws the compiled graph, runs a question and highlights the nodes that ran", async () => {
    const { calls } = mockFetch({
      "/learn/graph/run": { body: { steps: [{ node: "supervisor", ms: 8, writes: ["plan", "route"], summary: { route: "semantic" } }, { node: "strategy", ms: 14, writes: ["plan"], summary: { auto_strategy: { chosen: "hybrid" } } },
        { node: "semantic", ms: 7, writes: ["draft"], summary: {} }, { node: "final", ms: 5, writes: ["result"], summary: { final: true } }], checkpoints: [{ step: 0, next: ["supervisor"], writes: [] }],
        response: { answer: "Partners receive 4 weeks.", route: "semantic", confidence: "high", verified: true, citations: [], limitations: [], needs_input: false, details: {}, followups: [], usage: {} } } },
      "/learn/graph": { body: info }, "/learn/lessons": { body: lessons },
    });
    const { container } = render(<Learn workspace="w" canIngest />);
    await userEvent.click(await screen.findByRole("tab", { name: "Agent graph" }));
    expect(await screen.findByRole("img", { name: /Agent graph with 6 nodes and 6 edges/ })).toBeInTheDocument();
    expect(container.querySelectorAll("path.edge.cond").length).toBe(3);                         // conditional edges are dashed
    await userEvent.click(screen.getByLabelText(/Auto strategy/));
    await userEvent.click(screen.getByRole("button", { name: "Run through the graph" }));
    const steps = await screen.findByLabelText("Graph steps");
    expect(within(steps).getAllByRole("listitem")).toHaveLength(4);
    expect(within(steps).getByText(/wrote plan, route/)).toBeInTheDocument();
    expect(screen.getByText("Partners receive 4 weeks.")).toBeInTheDocument();
    await waitFor(() => expect(container.querySelectorAll("g.gnode.ran").length).toBe(3));        // supervisor, semantic, final exist in the drawing; "strategy" is not in this test graph
    expect(JSON.parse(String(calls.find((c) => c.url.endsWith("/graph/run"))!.init.body)).retrieval).toMatchObject({ auto: true, self_rag: false });
  });

  it("LangChain lab shows code and the recorded outputs of every example", async () => {
    mockFetch({
      "POST /learn/langchain": { body: { llm_used: false, code: { retriever: "class MkaRetriever(BaseRetriever): ...", chain: "chain = prompt | model", tool: "StructuredTool.from_function(...)", parser: "PydanticOutputParser(...)", memory: "trim_messages(...)" },
        retriever: { documents: [{ source: "hr.txt", location: "line 1", score: 0.5, text: "25 days" }] },
        chain: { answer: "25 days [1]", prompt: "System: Answer using ONLY the context", steps: [{ kind: "chain", name: "ChatPromptTemplate", input: "{...}", output: "messages", ms: 0.4 }] },
        tool: { term: "Anjali Rao", result: "4 occurrence(s)", schema: { type: "function" }, invalid_call_rejected: "1 validation error for ExactArgs" },
        parser: { format_instructions: "The output should be formatted as a JSON instance", parsed: { supported: true }, malformed_output_error: "Invalid json output: looks fine to me" },
        memory: { messages: [{ type: "human", content: "q" }], kept_by_window: [{ type: "ai", content: "a" }] } } },
      "/learn/lessons": { body: lessons },
    });
    render(<Learn workspace="w" canIngest />);
    await userEvent.click(await screen.findByRole("tab", { name: "LangChain lab" }));
    await userEvent.click(screen.getByRole("button", { name: "Run the LangChain examples" }));
    expect(await screen.findByText("chain = prompt | model")).toBeInTheDocument();
    expect(screen.getByText("ChatPromptTemplate")).toBeInTheDocument();
    expect(screen.getByText("4 occurrence(s)")).toBeInTheDocument();
    expect(screen.getByText(/Invalid json output/)).toBeInTheDocument();
    expect(screen.getByText(/deterministic extractive function/)).toBeInTheDocument();
  });

  it("explains that only managers can load the demo documents and surfaces API errors", async () => {
    mockFetch({ "POST /learn/retrieval/ablation": { status: 404, body: { detail: "No documents in this workspace: upload some first" } }, "/learn/lessons": { body: lessons } });
    render(<Learn workspace="w" canIngest={false} />);
    await userEvent.click(await screen.findByRole("tab", { name: "Retrieval lab" }));
    expect(screen.getByText("Ask a manager to load the demo documents.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Run experiment" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No documents in this workspace");
  });
});

describe("GraphDiagram", () => {
  it("places nodes left to right and keeps loop edges inside the drawing", () => {
    const { container } = render(<GraphDiagram info={info} />);
    const x = (id: string) => Number(container.querySelector(`g.gnode:has(text)`) && [...container.querySelectorAll("g.gnode")].find((g) => g.textContent?.startsWith(id.replace(/__/g, "")))?.getAttribute("transform")?.match(/translate\(([\d.]+)/)?.[1]);
    expect(x("supervisor")).toBeLessThan(x("semantic"));
    expect(x("semantic")).toBeLessThan(x("verify"));
    expect(x("verify")).toBeLessThan(x("final"));
    expect(container.querySelectorAll("path.edge").length).toBe(6);
  });
});
