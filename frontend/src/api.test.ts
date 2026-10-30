import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, askStream, hasToken, setToken } from "./api";
import { mockFetch, sse } from "./testutil";

afterEach(() => { vi.unstubAllGlobals(); setToken(null); });

describe("api client", () => {
  it("sends the bearer token and workspace header", async () => {
    const { calls } = mockFetch({ "/sources": { body: [] } });
    setToken("tok123");
    await api.sources("hr-team");
    const h = calls[0].init.headers as Record<string, string>;
    expect(h.Authorization).toBe("Bearer tok123");
    expect(h["X-Session-ID"]).toBe("hr-team");
  });

  it("turns FastAPI errors into readable messages and drops the token on 401", async () => {
    mockFetch({ "/sources": { status: 401, body: { detail: "Token expired" } } });
    setToken("old");
    await expect(api.sources("w")).rejects.toMatchObject({ status: 401, message: "Token expired" });
    expect(hasToken()).toBe(false);
    mockFetch({ "/ask": { status: 422, body: { detail: [{ msg: "String should have at least 1 character" }] } } });
    await expect(api.ask("w", { question: "" })).rejects.toThrow("String should have at least 1 character");
    mockFetch({ "/ask": { status: 429, body: { detail: "Rate limit exceeded (30/minute). Retry in 12s." } } });
    await expect(api.ask("w", { question: "x" })).rejects.toBeInstanceOf(ApiError);
  });

  it("uploads with async=true as multipart", async () => {
    const { calls } = mockFetch({ "POST /sources/upload": { status: 202, body: [{ name: "a.txt", job_id: "j1", status: "queued", error: null }] } });
    const r = await api.uploadFiles("w", [new File(["x"], "a.txt")], "private");
    expect(r[0].job_id).toBe("j1");
    expect(calls[0].url).toContain("async=true");
    expect(calls[0].init.body).toBeInstanceOf(FormData);
    expect((calls[0].init.body as FormData).get("visibility")).toBe("private");
  });

  it("parses SSE events even when they are split across network chunks", async () => {
    const full = sse("step", { node: "supervisor", detail: "route=exact" }) + sse("token", { text: "Hel" }) + sse("token", { text: "lo" }) + sse("final", { response: { answer: "Hello" } });
    const mid = Math.floor(full.length / 2);
    mockFetch({ "/ask/stream": () => ({ stream: [full.slice(0, mid), full.slice(mid)] }) });
    const seen: string[] = [];
    await askStream("w", { question: "hi" }, (e) => seen.push(e.type));
    expect(seen).toEqual(["step", "token", "token", "final"]);
  });

  it("rejects when the stream endpoint refuses", async () => {
    mockFetch({ "/ask/stream": { status: 403, body: { detail: "Your role (viewer) may not perform 'ask'" } } });
    await expect(askStream("w", { question: "x" }, () => {})).rejects.toThrow("may not perform");
  });
});
