import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mockFetch } from "../testutil";
import { resetCodeStatus, TaskLab } from "./CodeLab";
import { FeedbackBox, Glossary, ListenButton, loadPrefs, PrefsBar, prefsClass } from "./Extras";
import { pathProgress, Paths, recommendPath } from "./Paths";
import type { LearningPath, Lang, LessonCard, Progress, Task } from "./types";

vi.mock("./CodeEditor", () => ({ default: ({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) => <textarea aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} /> }));
afterEach(() => { vi.unstubAllGlobals(); resetCodeStatus(); });
beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

const L = (en: string) => ({ en, hi: en + " (hi)", hinglish: en + " (hinglish)" });
const card = (id: string, title: string): LessonCard => ({ id, category: "c", level: "beginner", minutes: 10, title: L(title), summary: "s", has_viz: false, has_exercise: true, prereq: [], tags: [] });
const cards = Object.fromEntries([card("a", "Lesson A"), card("b", "Lesson B"), card("c", "Lesson C")].map((c) => [c.id, c]));
const path: LearningPath = { id: "new-to-ai", icon: "🌱", title: L("Starter path"), summary: "Learn the basics", lessons: ["a", "b", "c"] };
const progress = (done: string[]): Progress => ({ lessons: Object.fromEntries(done.map((d) => [d, { status: "done" as const, step: 10, bookmarked: false, updated_at: "" }])), done: done.length, total: 3, percent: 0, categories: [], quiz: {}, exercises: {}, streak: 0, active_days: 0, weak: [], bookmarks: [], continue: null, recommended: [], projects: {} });

describe("recommendPath", () => {
  it("a complete beginner starts with the basics unless they only want interview prep", () => {
    expect(recommendPath("new", "chatbot")).toBe("new-to-ai");
    expect(recommendPath("new", "interview")).toBe("interview-ready");
    expect(recommendPath("dev", "agents")).toBe("agent-builder");
    expect(recommendPath("some", "production")).toBe("go-live");
    expect(recommendPath("dev", "understand")).toBe("new-to-ai");
  });
  it("pathProgress finds the first unfinished lesson", () => {
    expect(pathProgress(path, progress(["a"]))).toEqual({ done: 1, total: 3, next: "b" });
    expect(pathProgress(path, progress(["a", "b", "c"])).next).toBeNull();
  });
});

describe("Paths", () => {
  const props = { paths: [path], progress: progress([]), cards, lang: "en" as Lang, onOpen: vi.fn() };

  it("shows the goals, and a two-question quiz recommends one", async () => {
    const onChoose = vi.fn();
    render(<Paths {...props} chosen={null} onChoose={onChoose} />);
    expect(screen.getByRole("button", { name: /Starter path/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Not sure/ }));
    await userEvent.click(screen.getByRole("button", { name: "I am new to AI and programming" }));
    await userEvent.click(screen.getByRole("button", { name: "Build AI agents" }));
    expect(screen.getByText(/We suggest: Starter path/)).toBeInTheDocument();                // complete beginner -> basics, whatever the goal
    await userEvent.click(screen.getByRole("button", { name: "Use this path" }));
    expect(onChoose).toHaveBeenCalledWith("new-to-ai");
  });

  it("a chosen path lists its lessons with progress and opens the next one", async () => {
    const onOpen = vi.fn();
    render(<Paths {...props} chosen="new-to-ai" onChoose={() => undefined} progress={progress(["a"])} onOpen={onOpen} />);
    expect(screen.getByText("1 of 3 lessons done")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Next on your path: Lesson B/ }));
    expect(onOpen).toHaveBeenCalledWith("b");
  });
});

describe("reading options", () => {
  it("text size and easy-read are remembered and map to CSS classes", async () => {
    expect(prefsClass(loadPrefs())).toBe("ac-size-0");
    const onChange = vi.fn();
    render(<PrefsBar prefs={{ size: 0, dyslexia: false }} onChange={onChange} />);
    await userEvent.click(screen.getByRole("button", { name: "Larger text" }));
    expect(onChange).toHaveBeenCalledWith({ size: 1, dyslexia: false });
    expect(screen.getByRole("button", { name: "Smaller text" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Easy-read" }));
    expect(onChange).toHaveBeenLastCalledWith({ size: 0, dyslexia: true });
    expect(prefsClass({ size: 2, dyslexia: true })).toBe("ac-size-2 ac-dyslexia");
  });
});

describe("ListenButton", () => {
  it("is hidden when the browser cannot speak, and otherwise reads the text in the learner's language and can stop", async () => {
    const { container } = render(<ListenButton text="hello" lang="en" />);
    expect(container).toBeEmptyDOMElement();
    const spoken: { text: string; lang: string }[] = [];
    const cancel = vi.fn();
    class U { text: string; lang = ""; onend: (() => void) | null = null; onerror: (() => void) | null = null; constructor(t: string) { this.text = t; } }
    vi.stubGlobal("SpeechSynthesisUtterance", U);
    vi.stubGlobal("speechSynthesis", { speak: (u: U) => spoken.push({ text: u.text, lang: u.lang }), cancel });
    Object.defineProperty(window, "speechSynthesis", { value: { speak: (u: U) => spoken.push({ text: u.text, lang: u.lang }), cancel }, configurable: true });
    render(<ListenButton text="An {{llm|LLM}} predicts tokens." lang="hi" />);
    await userEvent.click(screen.getByRole("button", { name: /Listen/ }));
    expect(spoken).toEqual([{ text: "An LLM predicts tokens.", lang: "hi-IN" }]);
    await userEvent.click(screen.getByRole("button", { name: /Stop/ }));
    expect(cancel).toHaveBeenCalled();
  });
});

describe("FeedbackBox", () => {
  it("a thumbs up is sent at once; a thumbs down asks which step was confusing", async () => {
    const f = mockFetch({ "POST /academy/feedback": { status: 201, body: { ok: true } } });
    const { unmount } = render(<FeedbackBox lessonId="a" />);
    await userEvent.click(screen.getByRole("button", { name: /Yes/ }));
    expect(await screen.findByText(/Thank you/)).toBeInTheDocument();
    expect(JSON.parse(String(f.calls[0].init.body))).toEqual({ lesson_id: "a", helpful: true });
    unmount();
    render(<FeedbackBox lessonId="b" />);
    await userEvent.click(screen.getByRole("button", { name: /Not really/ }));
    await userEvent.click(screen.getByRole("radio", { name: "The code" }));
    await userEvent.type(screen.getByLabelText("Tell us more (optional)"), "too fast");
    await userEvent.click(screen.getByRole("button", { name: "Send feedback" }));
    await screen.findByText(/Thank you/);
    expect(JSON.parse(String(f.calls[1].init.body))).toEqual({ lesson_id: "b", helpful: false, step: "code", comment: "too fast" });
  });
});

describe("Glossary", () => {
  it("lists terms in the chosen language, filters, and opens a term", async () => {
    const onTerm = vi.fn();
    const gl = { llm: { term: "LLM", en: "Large model", hi: "बड़ा model", hinglish: "Bada model" }, rag: { term: "RAG", en: "Retrieval", hi: "खोज", hinglish: "Khoj" } };
    render(<Glossary glossary={gl} lang="hinglish" onTerm={onTerm} />);
    expect(screen.getByText("Bada model")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Search the glossary"), "khoj");
    expect(screen.queryByText("Bada model")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "RAG" }));
    expect(onTerm).toHaveBeenCalledWith("rag");
  });
});

describe("TaskLab: bigger hint and extra checks", () => {
  const task: Task = { prompt: "Write f", starter: "def f(): pass", hint: "Use return", expected_output: "4", tests: [{ name: "double 2", hidden: false, call: "f(2)", expect: "4" }, { name: "secret", hidden: true }] };
  const status = { "/academy/code/status": { body: { available: true, reason: null, languages: ["python"], timeout_s: 10, memory_mb: 1536, network: false, setup: null, preinstalled: [], limits: { code_bytes: 20000, output_bytes: 64000 } } } };

  it("lists the checks before running, then shows each result with expected/got and hides hidden values", async () => {
    mockFetch({ ...status, "POST /academy/code/run": { body: { ok: true, stdout: "", stderr: "", exit_code: 0, ms: 5, timed_out: false, truncated: false, passed: false, tests: [{ name: "double 2", passed: false, hidden: false, expect: "4", got: "None" }, { name: "secret", passed: false, hidden: true }] } } });
    render(<TaskLab task={task} kind="exercise" lessonId="x" title="Practical exercise" />);
    expect(screen.getByText(/2 extra checks will run: 1 visible, 1 hidden/)).toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: /Run and check/ }));
    const box = await screen.findByRole("region", { name: "Extra checks" });
    expect(within(box).getByText("0 of 2 checks passed")).toBeInTheDocument();
    expect(within(box).getByText(/expected/)).toHaveTextContent("expected 4, got None");
    expect(within(box).getByText("secret")).toBeInTheDocument();
    expect(box.textContent).not.toMatch(/secret.*expected/);
  });

  it("Bigger hint appears after Hint and shows part of the solution; it explains when it is still locked", async () => {
    const f = mockFetch({ ...status, "/academy/lessons/x/hint/exercise": { body: { hint: "return 2 * x\n# ... the rest is for you", lines_shown: 1, lines_total: 2 } } });
    render(<TaskLab task={task} kind="exercise" lessonId="x" title="Practical exercise" />);
    expect(screen.queryByRole("button", { name: "Bigger hint" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Hint" }));
    await userEvent.click(screen.getByRole("button", { name: "Bigger hint" }));
    expect(await screen.findByText(/return 2 \* x/)).toBeInTheDocument();
    expect(f.calls.some((c) => c.url.endsWith("/hint/exercise"))).toBe(true);
  });

  it("a locked bigger hint shows the server's message", async () => {
    mockFetch({ ...status, "/academy/lessons/x/hint/exercise": { status: 403, body: { detail: "Try the task at least once first - then a bigger hint is unlocked." } } });
    render(<TaskLab task={task} kind="exercise" lessonId="x" title="Practical exercise" />);
    await userEvent.click(screen.getByRole("button", { name: "Hint" }));
    await userEvent.click(screen.getByRole("button", { name: "Bigger hint" }));
    expect(await screen.findByText(/Try the task at least once first/)).toBeInTheDocument();
  });
});
