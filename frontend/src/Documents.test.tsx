import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Documents } from "./Documents";
import { mockFetch } from "./testutil";

afterEach(() => vi.unstubAllGlobals());

describe("Documents", () => {
  it("uploads multiple files, shows job progress, then refreshes the list", async () => {
    let polls = 0;
    let listed: object[] = [];
    mockFetch({
      "POST /sources/upload": { status: 202, body: [{ name: "a.pdf", job_id: "j1", status: "queued", error: null }, { name: "b.txt", job_id: null, status: "failed", error: "The file is empty" }] },
      "/jobs/j1": () => { polls++; return { body: polls < 2 ? { id: "j1", name: "a.pdf", status: "running", stage: "embedding", progress: 60, attempts: 1 } : { id: "j1", name: "a.pdf", status: "ready", stage: "done", progress: 100, attempts: 1, source_id: "s1" } }; },
      "/sources": () => { if (polls >= 2) listed = [{ id: "s1", name: "a.pdf", kind: "pdf", pages: 3, chunks: 5, tabular: false, warnings: ["1 page had no text"], needs_reindex: false, visibility: "tenant", status: "ready", created_at: "" }]; return { body: listed }; },
    });
    render(<Documents workspace="w" canIngest onAsk={() => {}} />);
    await screen.findByText("Nothing indexed in this workspace yet.");
    await userEvent.upload(screen.getByTestId("file-input"), [new File(["x"], "a.pdf"), new File([""], "b.txt")]);
    expect(await screen.findByText("embedding 60%")).toBeInTheDocument();
    expect(screen.getByText("The file is empty")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("indexed")).toBeInTheDocument(), { timeout: 4000 });
    expect(await screen.findByText("3 pages · 5 chunks")).toBeInTheDocument();
    expect(screen.getByText(/1 page had no text/)).toBeInTheDocument();
  });

  it("hides ingestion controls for viewers", async () => {
    mockFetch({ "/sources": { body: [] } });
    render(<Documents workspace="w" canIngest={false} onAsk={() => {}} />);
    await screen.findByText("Nothing indexed in this workspace yet.");
    expect(screen.queryByLabelText("Upload documents")).toBeNull();
  });

  it("deletes after confirmation and offers suggested questions", async () => {
    const src = { id: "s1", name: "memo.txt", kind: "txt", chunks: 1, tabular: false, warnings: [], needs_reindex: true, visibility: "private", status: "ready", created_at: "" };
    const { calls } = mockFetch({
      "DELETE /sources/s1": { body: { deleted: "s1" } }, "/sources/s1/questions": { body: { method: "template", questions: ["Summarize memo.txt?"] } },
      "/sources": { body: [src] },
    });
    vi.stubGlobal("confirm", () => true);
    const asked: string[] = [];
    render(<Documents workspace="w" canIngest onAsk={(q) => asked.push(q)} />);
    expect(await screen.findByText("needs re-index")).toBeInTheDocument();
    expect(screen.getByText("private")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Questions" }));
    await userEvent.click(await screen.findByRole("button", { name: "Summarize memo.txt?" }));
    expect(asked).toEqual(["Summarize memo.txt?"]);
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(calls.some((c) => c.init.method === "DELETE" && c.url.endsWith("/sources/s1"))).toBe(true));
  });
});
