import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Achievements, heatmap } from "./Achievements";
import type { LearningPath, LessonCard, Progress } from "./types";

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });
afterEach(() => vi.restoreAllMocks());

const L = (en: string) => ({ en, hi: en + " (hi)", hinglish: en + " (hinglish)" });
const card = (id: string): LessonCard => ({ id, category: "c", level: "beginner", minutes: 5, title: L("Lesson " + id), summary: "", has_viz: false, has_exercise: true, prereq: [], tags: [] });
const cards = { a: card("a"), b: card("b") };
const path: LearningPath = { id: "p", icon: "🌱", title: L("Starter"), summary: "", lessons: ["a", "b"] };
const prog = (done: string[], extra: Partial<Progress> = {}): Progress => ({
  lessons: Object.fromEntries(done.map((d) => [d, { status: "done" as const, step: 10, bookmarked: false, updated_at: "" }])), done: done.length, total: 2, percent: 0, categories: [], quiz: {}, exercises: {}, streak: 2, active_days: 3,
  weak: [], bookmarks: [], continue: null, recommended: [], projects: {}, best_streak: 4, activity: { "2026-11-20": 2, "2026-11-21": 9 },
  badges: [{ id: "first-lesson", title: L("First lesson"), how: "Complete one lesson", earned: done.length > 0 }, { id: "streak-7", title: L("7-day streak"), how: "Learn on 7 days in a row", earned: false }], ...extra,
});

describe("heatmap", () => {
  it("builds 16 columns of 7 days ending this week, Monday first, marking future days", () => {
    const cols = heatmap({ "2026-11-20": 2, "2026-11-21": 9 }, new Date("2026-11-21T12:00:00Z"));      // a Saturday
    expect(cols).toHaveLength(16);
    expect(cols.every((c) => c.length === 7)).toBe(true);
    const last = cols[15];
    expect(last[0].day).toBe("2026-11-16");                                                           // Monday
    expect(last.map((d) => d.future)).toEqual([false, false, false, false, false, false, true]);      // Sunday 22 is still ahead
    expect(last[4].n).toBe(2);
    expect(last[5].n).toBe(9);
    expect(cols[0][0].day).toBe("2026-08-03");
  });
});

describe("Achievements", () => {
  it("shows earned and locked badges with how to earn them, the calendar and streaks", () => {
    render(<Achievements progress={prog(["a"])} paths={[path]} cards={cards} lang="en" />);
    expect(screen.getByText("1 of 2")).toBeInTheDocument();
    expect(screen.getByText("First lesson").closest(".ac-badge")).toHaveClass("on");
    const locked = screen.getByText("7-day streak").closest(".ac-badge")!;
    expect(locked).not.toHaveClass("on");
    expect(within(locked as HTMLElement).getByText("locked: Learn on 7 days in a row")).toBeInTheDocument();
    expect(screen.getByText(/current streak 2 · best 4 days/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Learning activity over the last 16 weeks/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Certificate/ })).not.toBeInTheDocument();                // path not finished yet
  });

  it("a finished path offers a printable certificate that carries the learner's name and lessons", async () => {
    const print = vi.spyOn(window, "print").mockImplementation(() => undefined);
    render(<Achievements progress={prog(["a", "b"])} paths={[path]} cards={cards} lang="en" />);
    await userEvent.click(screen.getByRole("button", { name: /Certificate: Starter/ }));
    const dlg = screen.getByRole("dialog", { name: "Certificate of completion" });
    await userEvent.type(within(dlg).getByLabelText("Your name"), "Asha Rao");
    expect(within(dlg).getByText("Asha Rao")).toBeInTheDocument();
    expect(localStorage.getItem("mka_academy_name")).toBe("Asha Rao");
    expect(within(dlg).getByText("Lesson a")).toBeInTheDocument();
    expect(within(dlg).getByText(/not an accredited qualification/)).toBeInTheDocument();
    await userEvent.click(within(dlg).getByRole("button", { name: /Print/ }));
    expect(print).toHaveBeenCalled();
    await userEvent.click(within(dlg).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("renders nothing for an older server that sends no badges", () => {
    const { container } = render(<Achievements progress={{ ...prog([]), badges: undefined as never }} paths={[]} cards={cards} lang="en" />);
    expect(container).toBeEmptyDOMElement();
  });
});
