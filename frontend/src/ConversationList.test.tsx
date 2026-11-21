import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ConversationList, groupByDay } from "./ConversationList";
import type { Conversation } from "./types";

const NOW = new Date("2026-11-21T15:00:00");
const iso = (d: Date) => d.toISOString();
const days = (n: number) => iso(new Date(NOW.getTime() - n * 86_400_000));
const c = (id: string, title: string, updated_at: string): Conversation => ({ id, workspace: "w", title, updated_at });

describe("groupByDay", () => {
  it("groups by Today / Yesterday / Previous 7 days / Older, newest first, and tolerates empty or zone-less dates", () => {
    const g = groupByDay([c("a", "old", days(30)), c("b", "today", iso(new Date(NOW.getTime() - 3_600_000))), c("c", "yest", days(1)), c("d", "week", days(4)), c("e", "none", ""), c("f", "naive", iso(new Date(NOW.getTime() - 7_200_000)).slice(0, -1))], NOW);
    expect(g.map(([n, l]) => [n, l.map((x) => x.id)])).toEqual([["Today", ["b", "f"]], ["Yesterday", ["c"]], ["Previous 7 days", ["d"]], ["Older", ["a", "e"]]]);
  });
});

describe("ConversationList", () => {
  const items = [c("1", "Leave policy", new Date().toISOString()), c("2", "Quarterly sales", days(40))];

  it("shows group headings, highlights the active chat and opens one", async () => {
    const onOpen = vi.fn();
    render(<ConversationList items={items} active="1" onOpen={onOpen} onNew={() => undefined} onDelete={() => undefined} />);
    expect(screen.getByRole("heading", { name: "Today" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Older" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Leave policy" })).toHaveAttribute("aria-current", "true");
    await userEvent.click(screen.getByRole("button", { name: "Quarterly sales" }));
    expect(onOpen).toHaveBeenCalledWith("2");
  });

  it("searches by title", async () => {
    render(<ConversationList items={items} active={null} onOpen={() => undefined} onNew={() => undefined} onDelete={() => undefined} />);
    await userEvent.type(screen.getByLabelText("Search conversations"), "sales");
    expect(screen.queryByText("Leave policy")).not.toBeInTheDocument();
    expect(screen.getByText("Quarterly sales")).toBeInTheDocument();
    await userEvent.clear(screen.getByLabelText("Search conversations"));
    await userEvent.type(screen.getByLabelText("Search conversations"), "zzz");
    expect(screen.getByText(/No chats match/)).toBeInTheDocument();
  });

  it("deleting needs a second click, and Cancel keeps the chat", async () => {
    const onDelete = vi.fn();
    render(<ConversationList items={items} active={null} onOpen={() => undefined} onNew={() => undefined} onDelete={onDelete} />);
    await userEvent.click(screen.getByRole("button", { name: "Delete conversation Leave policy" }));
    expect(onDelete).not.toHaveBeenCalled();
    const box = screen.getByRole("group", { name: /Delete Leave policy/ });
    await userEvent.click(within(box).getByRole("button", { name: "Cancel" }));
    expect(onDelete).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Delete conversation Leave policy" }));
    await userEvent.click(within(screen.getByRole("group", { name: /Delete Leave policy/ })).getByRole("button", { name: "Delete" }));
    expect(onDelete).toHaveBeenCalledWith(items[0]);
  });

  it("has a friendly empty state and a new-conversation button", async () => {
    const onNew = vi.fn();
    render(<ConversationList items={[]} active={null} onOpen={() => undefined} onNew={onNew} onDelete={() => undefined} />);
    expect(screen.getByText("No conversations yet")).toBeInTheDocument();
    expect(screen.queryByLabelText("Search conversations")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "+ New conversation" }));
    expect(onNew).toHaveBeenCalled();
  });
});
