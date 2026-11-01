import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SCENES, type Values } from "./scenes";
import { attentionMatrix, contextBudget, EmbeddingViz, TemperatureViz, TokenGenerationViz } from "./specials";
import { Workflow } from "./Workflow";

const vals = (id: string, over: Values = {}): Values => ({ ...Object.fromEntries(SCENES[id].inputs.map((i) => [i.key, i.default])), ...over });
const run = (id: string, over: Values = {}, variant = SCENES[id].variants?.[0]?.id ?? "") => SCENES[id].build(vals(id, over), variant);

describe("scene logic", () => {
  it("RAG pipeline has the nine stages and reacts to chunk size", () => {
    const a = run("rag-pipeline", { size: 60 }), b = run("rag-pipeline", { size: 300 });
    expect(a.map((s) => s.label.slice(0, 2))).toEqual(["1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9."]);
    const n = (st: typeof a) => Number(/(\d+) chunks/.exec(st[2].output)![1]);
    expect(n(a)).toBeGreaterThan(n(b));
    expect(a[8].output).toMatch(/26 weeks/);                              // the parental-leave answer is found and cited
    expect(a[8].output).toMatch(/\[1\]$/);
  });
  it("RAG says it cannot find an answer instead of inventing one", () => {
    const st = run("rag-pipeline", { q: "xylophone quantum zebra" });
    expect(st[8].output).toMatch(/could not find/i);
  });
  it("chunking viz marks overlap", () => {
    const st = run("chunking", { size: 40, overlap: 10 });
    expect(st[1].segments!.some((s) => s.cls === "o")).toBe(true);
    expect(run("chunking", { overlap: 0 })[1].segments!.some((s) => s.cls === "o")).toBe(false);
  });
  it("hybrid search: exact code found by keyword search, fusion keeps it first", () => {
    const st = run("hybrid-rerank", { q: "error E-4021 after upgrade" });
    expect(st[1].output).toBe("best: doc 1");
    expect(st[3].output).toBe("fused best: doc 1");
  });
  it("query rewriting finds the resignation document with a synonym variant", () => {
    const st = run("query-transform", { q: "how do I quit my job" });
    expect(st[1].lines!.length).toBeGreaterThan(1);
    expect(st[3].output).toMatch(/best: doc 1/);
  });
  it("LangGraph variants: loop reaches the target, approval can be rejected, supervisor finishes", () => {
    const loop = run("langgraph-flow", { limit: 3 }, "loop");
    expect(loop[loop.length - 1].state).toMatchObject({ count: 3, passed: true });
    expect(loop.filter((s) => s.active?.[0] === "work")).toHaveLength(3);
    const rej = run("langgraph-flow", { approve: "reject" }, "approval");
    expect(rej.some((s) => s.output.startsWith("PAUSED"))).toBe(true);
    expect(rej[rej.length - 1].state).toMatchObject({ status: "rejected" });
    expect(rej.some((s) => s.active?.[0] === "send")).toBe(false);
    const ok = run("langgraph-flow", { approve: "approve" }, "approval");
    expect(ok[ok.length - 1].state).toMatchObject({ status: "refunded" });
    const sup = run("langgraph-flow", {}, "supervisor");
    expect(sup[sup.length - 2].output).toContain("FINISH");
    const route = run("langgraph-flow", { text: "Why was I charged twice?" }, "router");
    expect(route.map((s) => s.active?.[0])).toEqual(["START", "classify", "billing", "END"]);
    expect(run("langgraph-flow", { text: "the app crashes" }, "router")[2].active?.[0]).toBe("technical");
  });
  it("agent loop: calculator path, document path, blocked tool, no tool", () => {
    expect(run("agent-loop", { task: "What is 15% of 48000?" })[7].output).toBe("15% of 48000 is 7200.");
    expect(run("agent-loop", { task: "How many days of annual leave?" })[7].output).toMatch(/25 days/);
    const blocked = run("agent-loop", { task: "Delete all my files" });
    expect(blocked[3].output).toMatch(/BLOCKED/);
    expect(blocked[4].output).toBe("not executed");
    expect(run("agent-loop", { task: "Tell me a joke" })[2].output).toBe("none");
  });
  it("LangChain variants show each component's input and output; invalid structured output is rejected", () => {
    const seq = run("langchain-lcel", {}, "sequence");
    expect(seq.map((s) => s.label)).toEqual(["1. Input dict", "2. ChatPromptTemplate", "3. Chat model", "4. Output parser", "5. Result"]);
    expect(seq[1].output).toContain("You are a geography teacher");
    expect(run("langchain-lcel", { question: "Asha is 31" }, "structured")[2].output).toContain("age=31");
    expect(run("langchain-lcel", { question: "Asha is thirty-one" }, "structured")[2].output).toContain("ValidationError");
    expect(run("langchain-lcel", { question: "What is 2 plus 3 and 4?" }, "tool")[3].output).toBe("5");
  });
  it("LLM pipeline tokenizes and is deterministic for the same prompt", () => {
    const a = run("llm-pipeline", { prompt: "Hello, world" }), b = run("llm-pipeline", { prompt: "Hello, world" });
    expect(a[1].output).toBe("Hello  |  ,  |  world");
    expect(a).toEqual(b);
    expect(a[2].output).not.toBe(run("llm-pipeline", { prompt: "Goodbye" })[2].output);
  });
});

describe("special visualisations", () => {
  it("attention is a probability distribution per row; the causal mask hides the future", () => {
    const toks = ["the", "animal", "was", "tired", "because", "it", "slept"];
    const m = attentionMatrix(toks, true);
    m.forEach((row) => expect(row.reduce((a, b) => a + b, 0)).toBeCloseTo(1, 6));
    expect(m[1][5]).toBeLessThan(1e-6);                                // 'animal' cannot see the later word 'it'
    expect(attentionMatrix(toks, false)[1][5]).toBeGreaterThan(1e-4);
    const it = m[5];
    expect(it[1]).toBeGreaterThan(it[0]);                              // 'it' looks back at a content word more than at 'the'
  });
  it("context budget drops the oldest history first and truncates documents last", () => {
    const hist = ["one two three four five six", "seven eight nine ten eleven twelve", "latest question here please"];
    const roomy = contextBudget(500, 20, "sys prompt", hist, "doc text", "hi");
    expect(roomy.droppedHistory).toBe(0);
    expect(roomy.used).toBeLessThanOrEqual(500);
    const tight = contextBudget(40, 10, "sys prompt", hist, "a long retrieved document with many many words in it indeed", "hi");
    expect(tight.droppedHistory + (tight.docsTruncated ? 1 : 0)).toBeGreaterThan(0);
    expect(tight.used).toBeLessThanOrEqual(40);
    expect(contextBudget(10, 9, "this system prompt is longer than the window", [], "", "hello there").overflow).toBe(true);
  });
});

describe("Workflow component", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("plays automatically, highlights the current stage, pauses and resets", () => {
    render(<Workflow scene={SCENES["llm-pipeline"]} lang="en" />);
    const flow = screen.getByRole("list", { name: "Workflow stages" });
    const cur = () => within(flow).getByRole("button", { current: "step" }).textContent;
    expect(cur()).toBe("1. Prompt");
    act(() => { screen.getByRole("button", { name: /Play/ }).click(); });
    act(() => { vi.advanceTimersByTime(1600); });
    expect(cur()).toBe("2. Tokenization");
    act(() => { screen.getByRole("button", { name: /Pause/ }).click(); });
    act(() => { vi.advanceTimersByTime(5000); });
    expect(cur()).toBe("2. Tokenization");                                   // paused: nothing moves
    act(() => { screen.getByRole("button", { name: /Reset/ }).click(); });
    expect(cur()).toBe("1. Prompt");
  });

  it("steps manually, shows input and output, and technical details on demand", async () => {
    vi.useRealTimers();
    render(<Workflow scene={SCENES["llm-pipeline"]} lang="en" />);
    await userEvent.click(screen.getByRole("button", { name: /Step/ }));
    expect(screen.getByRole("heading", { name: "2. Tokenization" })).toBeInTheDocument();
    expect(screen.getByText(/Explain tokenization to a beginner\./)).toBeInTheDocument();         // input of the stage
    expect(screen.queryByText(/Real tokenizers/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Technical details" }));
    expect(screen.getByText(/Real tokenizers/)).toBeInTheDocument();
  });

  it("changing an input recomputes the stages and restarts the animation", async () => {
    vi.useRealTimers();
    render(<Workflow scene={SCENES["rag-pipeline"]} lang="en" />);
    await userEvent.click(screen.getByRole("button", { name: "3. Split into chunks" }));
    const before = screen.getByText(/\d+ chunks/).textContent;
    const size = screen.getByLabelText("Chunk size (characters)");
    await userEvent.clear(size);
    await userEvent.type(size, "400");
    expect(screen.getByRole("button", { current: "step" })).toHaveTextContent("1. Upload");        // back to the start
    await userEvent.click(screen.getByRole("button", { name: "3. Split into chunks" }));
    expect(screen.getByText(/\d+ chunks/).textContent).not.toBe(before);
  });

  it("explains in Hindi and Hinglish when the language changes", () => {
    const { rerender } = render(<Workflow scene={SCENES["llm-pipeline"]} lang="hi" />);
    expect(screen.getByText(/आप text लिखते हैं/)).toBeInTheDocument();
    rerender(<Workflow scene={SCENES["llm-pipeline"]} lang="hinglish" />);
    expect(screen.getByText(/Aap text likhte ho/)).toBeInTheDocument();
  });

  it("draws the graph for LangGraph scenes and lets you pick a pattern", async () => {
    vi.useRealTimers();
    render(<Workflow scene={SCENES["langgraph-flow"]} lang="en" />);
    expect(screen.getByRole("img", { name: /Agent graph/ })).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Pattern"), "approval");
    await userEvent.click(screen.getByRole("button", { name: /approve: interrupt/ }));
    expect(screen.getByText(/PAUSED/)).toBeInTheDocument();
  });
});

describe("interactive specials", () => {
  it("temperature slider changes the probabilities and sampling follows them", async () => {
    render(<TemperatureViz lang="en" />);
    const row = () => screen.getAllByRole("row")[0].textContent ?? "";
    const base = row();
    const slider = screen.getByLabelText(/^Temperature: /);
    fireEvent.change(slider, { target: { value: "0.2" } });
    expect(row()).not.toBe(base);
    expect(Number(/(\d+(?:\.\d)?)% →/.exec(row())![1])).toBeGreaterThan(Number(/(\d+(?:\.\d)?)% →/.exec(base)![1]));      // low temperature: the top token grows
    await userEvent.click(screen.getByRole("button", { name: "Sample 100" }));
    expect(screen.getByText(/last draws:/)).toBeInTheDocument();
  });
  it("token generation steps through a bigram model", async () => {
    render(<TokenGenerationViz lang="en" />);
    await userEvent.click(screen.getByRole("button", { name: /Step/ }));
    await userEvent.click(screen.getByRole("button", { name: /Step/ }));
    expect((screen.getByText((_, el) => el?.className === "viz-gen")).textContent ?? "").toMatch(/^the \w+ \w+/);
  });
  it("embedding search ranks the meaning match first and marks retrieved items", () => {
    render(<EmbeddingViz lang="en" />);
    const rows = screen.getAllByRole("row");
    expect(rows[0].textContent).toContain("resignation procedure");        // matched by meaning: "quit" and "resignation" share a concept
    expect(rows[0].textContent).toContain("retrieved");
    expect(rows[4].textContent).not.toContain("retrieved");
  });
});
