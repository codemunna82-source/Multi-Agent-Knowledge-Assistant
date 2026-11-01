import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Chat } from "./Chat";
import { StreamingMessage, splitBlocks } from "./StreamingMessage";
import { ThinkingIndicator } from "./ThinkingIndicator";
import { controlledStream, mockFetch, sse } from "./testutil";

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

const base = { route: "semantic", confidence: "high", verified: true, limitations: [], needs_input: false, details: {}, usage: { prompt_tokens: 1, completion_tokens: 1, cost_usd: 0 }, latency_ms: 10, citations: [], followups: [] };
const final = (answer: string, extra: object = {}) => sse("final", { response: { ...base, answer, conversation_id: "c1", ...extra } });

describe("StreamingMessage (Markdown)", () => {
  it("renders headings, lists, tables, links and inline code", () => {
    render(<StreamingMessage text={"## Leave\n\n- **25** days\n- `carry_over` allowed\n\n| Type | Days |\n|---|---|\n| Annual | 25 |\n\nSee [policy](https://example.com/p)."} />);
    expect(screen.getByRole("heading", { level: 2, name: "Leave" })).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText("carry_over").tagName).toBe("CODE");
    expect(screen.getByRole("table")).toBeInTheDocument();
    const a = screen.getByRole("link", { name: "policy" });
    expect(a).toHaveAttribute("href", "https://example.com/p");
    expect(a).toHaveAttribute("rel", expect.stringContaining("noopener"));
  });

  it("highlights code blocks and shows the language", () => {
    const { container } = render(<StreamingMessage text={"```python\ndef add(a, b):\n    return a + b\n```"} />);
    expect(container.querySelector("pre code.hljs, pre code[class*='language-']")).not.toBeNull();
    expect(container.querySelector(".hljs-keyword")?.textContent).toBe("def");
    expect(screen.getByText("python")).toBeInTheDocument();
  });

  it("renders a code block that is still open (partial stream) as code, not as stray backticks", () => {
    const { container } = render(<StreamingMessage streaming text={"Here:\n\n```js\nconst x = 1;\nconsole.lo"} />);
    expect(container.querySelector("pre code")?.textContent).toContain("console.lo");
    expect(container.textContent).not.toContain("```");
  });

  it("never renders raw HTML or javascript: links", () => {
    const { container } = render(<StreamingMessage text={"<img src=x onerror=alert(1)> <script>alert(1)</script>\n\n[click](javascript:alert(1)) [ok](https://a.io)"} />);
    expect(container.querySelector("img, script")).toBeNull();
    expect(container.querySelector("a[href^='javascript']")).toBeNull();
    expect(container.querySelector("a[href='https://a.io']")).not.toBeNull();
  });

  it("splits at blank lines but never inside a code fence", () => {
    expect(splitBlocks("a\n\nb\n\n```\nx\n\ny\n```\n\nc")).toEqual(["a", "b", "```\nx\n\ny\n```", "c"]);
    expect(splitBlocks("para\n\n```\nopen")).toEqual(["para", "```\nopen"]);
  });

  it("re-renders only the last block while text grows", () => {
    const { rerender, container } = render(<StreamingMessage streaming text={"First paragraph.\n\nSecond"} />);
    const first = container.querySelector("p")!;
    rerender(<StreamingMessage streaming text={"First paragraph.\n\nSecond paragraph grows"} />);
    expect(container.querySelector("p")).toBe(first);                      // the finished block's DOM node was kept, not rebuilt
    expect(container.textContent).toContain("Second paragraph grows");
  });
});

describe("ThinkingIndicator", () => {
  beforeEach(() => vi.useFakeTimers());

  it("shows ONE generic message at a time and rotates", () => {
    render(<ThinkingIndicator />);
    const seen = new Set<string>();
    for (let i = 0; i < 4; i++) {
      const msgs = screen.getByRole("status").querySelectorAll(".think-text");
      expect(msgs).toHaveLength(1);
      seen.add(msgs[0].textContent ?? "");
      act(() => { vi.advanceTimersByTime(2800); });
    }
    expect(seen.size).toBe(4);
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();                // no fake progress numbers
  });

  it("claims no stage the system is not running: 'Searching…' only comes from a real stage, 'Almost there…' only after a long wait", () => {
    const { rerender } = render(<ThinkingIndicator />);
    const generic = () => screen.getByRole("status").textContent ?? "";
    for (let i = 0; i < 4; i++) { expect(generic()).not.toMatch(/search|retriev|rerank|almost/i); act(() => { vi.advanceTimersByTime(2800); }); }
    act(() => { vi.advanceTimersByTime(9000); });
    expect(generic()).toContain("Almost there");
    rerender(<ThinkingIndicator stage="Searching documents" />);
    expect(generic()).toContain("Searching documents…");
    rerender(<ThinkingIndicator stage="Reranking retrieved chunks" />);
    expect(generic()).toContain("Reranking retrieved chunks…");
  });
});

function chat() { return render(<Chat workspace="w" prefill={null} onPrefillUsed={() => {}} />); }
async function ask(q: string) {
  await userEvent.type(screen.getByLabelText("Question"), q);
  await userEvent.click(screen.getByRole("button", { name: "Ask" }));
}
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 40)); });

describe("Chat streaming", () => {
  it("shows the loader until the first token, then appends chunks without replacing earlier text", async () => {
    const cs = controlledStream();
    mockFetch(cs.handlers);
    chat();
    await ask("Explain leave");
    expect(await screen.findByRole("status", { name: "Assistant is working" })).toBeInTheDocument();
    cs.push(sse("status", { stage: "retrieve", label: "Searching documents" }));
    expect(await screen.findByText("Searching documents…")).toBeInTheDocument();
    cs.push(sse("status", { stage: "rerank", label: "Reranking retrieved chunks" }));
    expect(await screen.findByText("Reranking retrieved chunks…")).toBeInTheDocument();
    cs.push(sse("draft", { text: "Employees " }));
    await waitFor(() => expect(screen.getByText(/Employees/)).toBeInTheDocument());
    expect(screen.queryByRole("status", { name: "Assistant is working" })).not.toBeInTheDocument();      // loader gone with the first token
    cs.push(sse("draft", { text: "get **25 days**" }));
    await waitFor(() => expect(screen.getByText("25 days").tagName).toBe("STRONG"));
    expect(screen.getByText(/Employees/)).toBeInTheDocument();                                           // earlier chunk still there
    expect(screen.getByRole("button", { name: "Stop generating" })).toBeInTheDocument();
    cs.push(final("Employees get **25 days**"));
    cs.push(sse("done", {}));
    cs.close();
    await waitFor(() => expect(screen.queryByRole("button", { name: "Stop generating" })).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Regenerate answer" })).toBeInTheDocument();
    expect(screen.queryByText(/adjusted after/)).not.toBeInTheDocument();                                // final == draft: no "corrected" note
  });

  it("tells the user when verification changed the streamed draft", async () => {
    const cs = controlledStream();
    mockFetch(cs.handlers);
    chat();
    await ask("q");
    cs.push(sse("draft", { text: "Employees get 30 days" }));
    await screen.findByText(/30 days/);
    cs.push(final("Employees get 25 days"));
    cs.close();
    expect(await screen.findByText("Employees get 25 days")).toBeInTheDocument();
    expect(screen.getByText(/adjusted after it was checked/)).toBeInTheDocument();
  });

  it("Stop aborts the request, keeps the partial text and allows a new question", async () => {
    const cs = controlledStream();
    mockFetch(cs.handlers);
    chat();
    await ask("long one");
    cs.push(sse("draft", { text: "Partial answer so far" }));
    await screen.findByText(/Partial answer/);
    await userEvent.click(screen.getByRole("button", { name: "Stop generating" }));
    await waitFor(() => expect(cs.state.signal?.aborted).toBe(true));
    expect(await screen.findByText("Generation stopped.")).toBeInTheDocument();
    expect(screen.getByText(/Partial answer so far/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();                                  // empty input, but not "busy"
    await userEvent.type(screen.getByLabelText("Question"), "another");
    expect(screen.getByRole("button", { name: "Ask" })).toBeEnabled();
  });

  it("does not start a second request while one is active", async () => {
    const cs = controlledStream();
    mockFetch(cs.handlers);
    chat();
    await ask("first");
    await screen.findByRole("status", { name: "Assistant is working" });
    await userEvent.type(screen.getByLabelText("Question"), "second{Enter}");
    await flush();
    expect(cs.state.requests).toBe(1);
    cs.push(final("done"));
    cs.close();
  });

  it("shows an error from the server with a retry that re-asks the same question", async () => {
    const cs = controlledStream();
    mockFetch(cs.handlers);
    chat();
    await ask("will fail");
    cs.push(sse("error", { detail: "Model/API error: boom" }));
    cs.close();
    expect(await screen.findByText(/Model\/API error: boom/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(cs.state.requests).toBe(2));
    expect(cs.state.bodies[1]).toMatchObject({ question: "will fail" });
    expect(cs.state.bodies[1].regenerate).toBeUndefined();                                              // nothing was stored, so nothing to replace
    expect(screen.getAllByText("will fail")).toHaveLength(1);                                           // same question bubble, not a duplicate
    cs.push(final("ok now")); cs.close();
  });

  it("handles a dropped network connection mid-stream: partial text stays, error + retry shown", async () => {
    const cs = controlledStream();
    mockFetch(cs.handlers);
    chat();
    await ask("net");
    cs.push(sse("draft", { text: "Half an ans" }));
    await screen.findByText(/Half an ans/);
    cs.fail(new TypeError("network error"));
    expect(await screen.findByText(/connection was lost/)).toBeInTheDocument();
    expect(screen.getByText(/Half an ans/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeEnabled();
  });

  it("treats a stream that ends without a final event as an error, not an endless spinner", async () => {
    const cs = controlledStream();
    mockFetch(cs.handlers);
    chat();
    await ask("cut");
    cs.push(sse("draft", { text: "abc" }));
    cs.close();
    expect(await screen.findByText(/closed before the answer was complete/)).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Assistant is working" })).not.toBeInTheDocument();
  });

  it("an empty answer from the server is shown as the server's message, not a blank bubble", async () => {
    const cs = controlledStream();
    mockFetch(cs.handlers);
    chat();
    await ask("nothing");
    cs.push(final("I could not find anything about that in your documents.", { verified: false }));
    cs.close();
    expect(await screen.findByText(/could not find anything/)).toBeInTheDocument();
  });

  it("Regenerate replaces the answer (regenerate flag only after a stored answer); Copy puts the answer on the clipboard", async () => {
    const cs = controlledStream();
    mockFetch(cs.handlers);
    const writeText = vi.fn(async () => {});
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    chat();
    await ask("regen me");
    cs.push(final("First answer")); cs.close();
    await screen.findByText("First answer");
    await userEvent.click(screen.getByRole("button", { name: "Copy answer" }));
    expect(writeText).toHaveBeenCalledWith("First answer");
    expect(await screen.findByText("✓ Copied")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Regenerate answer" }));
    await waitFor(() => expect(cs.state.requests).toBe(2));
    expect(cs.state.bodies[1]).toMatchObject({ question: "regen me", regenerate: true, conversation_id: "c1" });
    await waitFor(() => expect(screen.queryByText("First answer")).not.toBeInTheDocument());           // old answer replaced by the loader
    cs.push(final("Second answer")); cs.close();
    expect(await screen.findByText("Second answer")).toBeInTheDocument();
    expect(screen.getAllByText("regen me")).toHaveLength(1);
  });

  it("follows new text while at the bottom but not after the reader scrolled up", async () => {
    const cs = controlledStream();
    mockFetch(cs.handlers);
    chat();
    const log = document.querySelector(".log") as HTMLElement;
    let top = 0;
    Object.defineProperty(log, "scrollHeight", { configurable: true, get: () => 1000 });
    Object.defineProperty(log, "clientHeight", { configurable: true, get: () => 400 });
    Object.defineProperty(log, "scrollTop", { configurable: true, get: () => top, set: (v) => { top = v; } });
    await ask("scroll");
    cs.push(sse("draft", { text: "line one" }));
    await screen.findByText(/line one/);
    await waitFor(() => expect(top).toBe(1000));                                                         // pinned to the bottom
    top = 100;
    act(() => { log.dispatchEvent(new Event("scroll")); });                                              // reader scrolled up
    cs.push(sse("draft", { text: " and more text" }));
    await screen.findByText(/and more text/);
    await flush();
    expect(top).toBe(100);                                                                               // not yanked back down
    const jump = await screen.findByRole("button", { name: "Scroll to latest" });
    await userEvent.click(jump);
    await waitFor(() => expect(top).toBe(1000));
    cs.push(final("line one and more text")); cs.close();
    within(document.body);
  });
});
