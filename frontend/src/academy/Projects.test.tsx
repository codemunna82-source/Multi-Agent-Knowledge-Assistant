import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockFetch } from "../testutil";
import { Interview } from "./Interview";
import { layers, Projects } from "./Projects";

afterEach(() => vi.unstubAllGlobals());

const card = { id: "p1", title: "PDF Chatbot", summary: "Ask your PDF", level: "beginner", hours: 3, stack: ["FastAPI"], steps: 2, done: 0 };
const detail = { ...card, architecture: { nodes: ["plan", "search", "check", "END"], edges: [["plan", "search"], ["search", "check"], ["check", "search"], ["check", "END"]] }, folders: "p1/\n└── core.py", done_steps: [1],
  steps: [{ title: "Write core", detail: "Do it", file: "core.py" }, { title: "Test", detail: "Run it" }], files: { "core.py": "print('core')", "test_app.py": "def test_x(): pass" },
  api_tests: [{ title: "Ask", command: "curl http://x/ask" }], deploy: "1. docker build", interview: "I built a RAG service." };

describe("layers", () => {
  it("lays a loop out left-to-right without cycling", () => {
    expect(layers(["plan", "search", "check", "END"], [["plan", "search"], ["search", "check"], ["check", "search"], ["check", "END"]])).toEqual([["plan"], ["search"], ["check"], ["END"]]);
  });
});

describe("Projects", () => {
  it("lists projects, opens one, shows code per file and saves step progress", async () => {
    const { calls } = mockFetch({ "/academy/projects/p1/progress": { body: { done_steps: [0, 1] } }, "/academy/projects/p1": { body: detail }, "/academy/projects": { body: [card] } });
    const changed = vi.fn();
    render(<Projects onChanged={changed} />);
    await userEvent.click(await screen.findByRole("button", { name: /PDF Chatbot/ }));
    expect(await screen.findByRole("heading", { name: "PDF Chatbot" })).toBeInTheDocument();
    expect(screen.getByText(/1\/2 done/)).toBeInTheDocument();
    expect(screen.getByLabelText("Architecture diagram")).toBeInTheDocument();
    expect(screen.getByText("print('core')")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "test_app.py" }));
    expect(screen.getByText("def test_x(): pass")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("checkbox", { name: /Write core/ }));
    await waitFor(() => expect(changed).toHaveBeenCalled());
    const put = calls.find((c) => c.init?.method === "PUT")!;
    expect(JSON.parse(String(put.init.body)).done_steps.sort()).toEqual([0, 1]);
    expect(screen.getByText("I built a RAG service.")).toBeInTheDocument();
  });
});

describe("Interview", () => {
  it("filters by topic and search text", async () => {
    mockFetch({ "/academy/interview": { body: [
      { category: "rag", lesson: "a", level: "beginner", q: "What is chunking?", a: "Splitting text." },
      { category: "agentic", lesson: null, level: "advanced", q: "When not to use an agent?", a: "When a workflow works." }] } });
    render(<Interview categories={{ rag: "RAG", agentic: "Agentic AI" }} />);
    expect(await screen.findByText(/What is chunking/)).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText(/Topic/), "agentic");
    expect(screen.queryByText(/What is chunking/)).not.toBeInTheDocument();
    expect(screen.getByText(/When not to use/)).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText(/Topic/), "");
    await userEvent.type(screen.getByLabelText(/Search/), "chunk");
    expect(within(document.body).getAllByText(/\?/).length).toBe(1);
  });
});
