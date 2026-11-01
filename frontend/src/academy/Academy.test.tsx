import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mockFetch } from "../testutil";
import { Academy } from "./Academy";

afterEach(() => vi.unstubAllGlobals());
beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

const L = (en: string, hi = en + " (hi)", hinglish = en + " (hinglish)") => ({ en, hi, hinglish });
const card = { id: "what-is-llm", category: "llm", level: "beginner", minutes: 18, title: L("What is an LLM?", "LLM क्या है?"), summary: "Next-token predictor", has_viz: false, has_exercise: true, prereq: [], tags: [] };
const catalog = {
  categories: [{ id: "llm", title: { en: "LLM Fundamentals", hi: "LLM की बुनियाद" }, summary: "", lessons: [card] }, { id: "rag", title: { en: "RAG", hi: "RAG" }, summary: "", lessons: [] }],
  roadmap: { beginner: [{ title: "LLM", lesson: "what-is-llm", planned: false }], intermediate: [], advanced: [], production: [{ title: "Docker", lesson: null, planned: true }] }, languages: ["en", "hi", "hinglish"],
};
const lesson = {
  ...card, next: [], objectives: ["Describe an LLM"], assignment: "Try the playground", sources: [{ title: "Docs", url: "https://example.com" }], viz: [], interview_questions: [{ q: "How does an LLM work?", a: "Next token." }],
  text: { definition: L("An {{llm|LLM}} predicts the next token.", "{{llm|LLM}} अगला token predict करता है।", "{{llm|LLM}} agla token predict karta hai."), analogy: L("Autocomplete"), technical: L("Transformers"), why: L("Flexibility"), example: L("Chatbot"), interview: L("Short answer"), mistakes: { en: ["m1", "m2"], hi: ["h1", "h2"], hinglish: ["x1", "x2"] } },
  code: [{ title: "Toy", language: "python", runnable: true, code: "print(1)", expected_output: "1", explain: [{ lines: "1", text: "prints" }] }],
  exercise: { prompt: "p", starter: "s", hint: "h", expected_output: "o" },
  quiz: [{ id: "what-is-llm.q1", q: "What does an LLM predict?", options: ["Whole answer", "Next token"], kind: "concept" }],
};
const progress = (extra: object = {}) => ({ lessons: {}, done: 0, total: 1, percent: 0, categories: [{ id: "llm", title: "LLM Fundamentals", lessons: 1, done: 0, percent: 0 }], quiz: {}, exercises: {}, streak: 2, active_days: 2, weak: [], bookmarks: [], continue: { lesson: "what-is-llm", step: 0 }, recommended: ["what-is-llm"], projects: {}, ...extra });
const glossary = { llm: { term: "LLM", en: "Large Language Model", hi: "बड़ा भाषा model", hinglish: "Bada language model" } };

function setup(extra: Record<string, unknown> = {}) {
  return mockFetch({
    "/academy/catalog": { body: catalog }, "/academy/glossary": { body: glossary }, "/academy/lessons/what-is-llm": { body: lesson },
    "PUT /academy/progress": { body: { lesson: "what-is-llm", status: "in_progress", step: 0, bookmarked: false } }, "GET /academy/progress": { body: progress() }, ...extra,
  });
}

describe("Academy", () => {
  it("shows the dashboard with continue learning, progress per category and the roadmap", async () => {
    setup();
    render(<Academy workspace="w" />);
    expect(await screen.findByRole("heading", { name: "AI Learning Academy" })).toBeInTheDocument();
    const cont = screen.getByRole("region", { name: "Continue learning" });
    expect(within(cont).getByText("What is an LLM?")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();                                       // streak
    expect(screen.getByRole("progressbar", { name: "LLM Fundamentals progress" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Beginner/ }));
    expect(screen.getByText(/Docker/)).toBeInTheDocument();
    expect(screen.getByText("(planned)")).toBeInTheDocument();                                // topics without a lesson are labelled, not faked
  });

  it("opens a lesson, switches language without losing progress, and opens term definitions", async () => {
    const { calls } = setup();
    render(<Academy workspace="w" />);
    await userEvent.click(await screen.findByRole("button", { name: /Start/ }));
    expect(await screen.findByRole("heading", { level: 1, name: "What is an LLM?" })).toBeInTheDocument();
    expect(screen.getByText(/predicts the next token/)).toBeInTheDocument();
    const before = calls.filter((c) => c.init.method === "PUT").length;
    await userEvent.click(screen.getByRole("button", { name: "हिंदी" }));
    expect(await screen.findByRole("heading", { level: 1, name: "LLM क्या है?" })).toBeInTheDocument();
    expect(screen.getByText(/अगला token predict करता है/)).toBeInTheDocument();
    expect(calls.filter((c) => c.init.method === "PUT").length).toBe(before);              // switching language never writes progress
    expect(localStorage.getItem("mka_academy_lang")).toBe("hi");
    await userEvent.click(screen.getByRole("button", { name: "Hinglish" }));
    expect(screen.getByText(/agla token predict karta hai/)).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("button", { name: "LLM" })[0]);
    const panel = await screen.findByRole("region", { name: "Definition of LLM" });
    expect(within(panel).getByText("Bada language model")).toBeInTheDocument();
    await userEvent.click(within(panel).getByRole("button", { name: "Show all languages" }));
    expect(within(panel).getByText(/Large Language Model/)).toBeInTheDocument();
  });

  it("remembers the chosen language and the lesson list reflects completion", async () => {
    localStorage.setItem("mka_academy_lang", "hi");
    setup({ "GET /academy/progress": { body: progress({ lessons: { "what-is-llm": { status: "done", step: 5, bookmarked: true, updated_at: "" } }, done: 1, percent: 100, bookmarks: ["what-is-llm"] }) } });
    render(<Academy workspace="w" />);
    await screen.findByRole("heading", { name: "AI Learning Academy" });
    await userEvent.click(within(screen.getByRole("navigation", { name: "Academy navigation" })).getByText(/LLM की बुनियाद/));
    expect(await screen.findByRole("button", { name: /✓ LLM क्या है\?/ })).toBeInTheDocument();
  });

  it("marks a lesson complete and bookmarks it through the API", async () => {
    const { calls } = setup();
    render(<Academy workspace="w" />);
    await userEvent.click(await screen.findByRole("button", { name: /Start/ }));
    await screen.findByRole("heading", { level: 1, name: "What is an LLM?" });
    await userEvent.click(screen.getByRole("button", { name: "Mark complete" }));
    await userEvent.click(screen.getByRole("button", { name: /Bookmark/ }));
    await waitFor(() => {
      const bodies = calls.filter((c) => c.init.method === "PUT").map((c) => JSON.parse(String(c.init.body)));
      expect(bodies).toContainEqual({ status: "done" });
      expect(bodies).toContainEqual({ bookmarked: true });
    });
  });

  it("grades the quiz on the server and shows why every option is right or wrong", async () => {
    const { calls } = setup({
      "POST /academy/quiz/submit": { body: { score: 1, total: 1, percent: 100, results: [{ id: "what-is-llm.q1", lesson: "what-is-llm", selected: 1, correct: true, answer: 1, why: "It loops token by token.", why_not: { "0": "Not the whole answer at once." }, options: ["Whole answer", "Next token"] }] } },
    });
    render(<Academy workspace="w" />);
    await userEvent.click(await screen.findByRole("button", { name: /Start/ }));
    const quiz = await screen.findByRole("region", { name: /Quiz: What is an LLM/ });
    await userEvent.click(within(quiz).getByRole("radio", { name: "Next token" }));
    await userEvent.click(within(quiz).getByRole("button", { name: "Submit answers" }));
    expect(await within(quiz).findByText(/It loops token by token/)).toBeInTheDocument();
    expect(within(quiz).getByText(/Not the whole answer at once/)).toBeInTheDocument();
    expect(within(quiz).getByText(/Score: 1 \/ 1 \(100%\)/)).toBeInTheDocument();
    expect(JSON.parse(String(calls.find((c) => c.url.endsWith("/quiz/submit"))!.init.body))).toEqual({ answers: { "what-is-llm.q1": 1 } });
  });

  it("searches lessons and glossary terms", async () => {
    setup({ "/academy/search": { body: [card, { glossary: "llm", term: "LLM" }] } });
    render(<Academy workspace="w" />);
    await userEvent.type(await screen.findByLabelText("Search lessons"), "llm");
    const res = await screen.findByRole("listbox", { name: "Search results" });
    expect(await within(res).findByRole("button", { name: "What is an LLM?" })).toBeInTheDocument();
    await userEvent.click(within(res).getByRole("button", { name: /📖 LLM/ }));
    expect(await screen.findByRole("region", { name: "Definition of LLM" })).toBeInTheDocument();
  });
});
