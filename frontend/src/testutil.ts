import { vi } from "vitest";

type Resp = { status?: number; body?: unknown; stream?: string[] };
type Handler = (url: string, init: RequestInit) => Resp | undefined;

/** Minimal fetch router for component tests. Handlers are tried in order; unmatched requests fail loudly. */
export function mockFetch(handlers: Record<string, Handler | Resp>) {
  const calls: { url: string; init: RequestInit }[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input);
    calls.push({ url, init });
    for (const [pattern, h] of Object.entries(handlers)) {
      const [method, path] = pattern.includes(" ") ? pattern.split(" ", 2) : [undefined, pattern];
      if ((method && (init.method ?? "GET") !== method) || !url.includes(path)) continue;
      const r = typeof h === "function" ? h(url, init) : h;
      if (!r) continue;
      if (r.stream) {
        const enc = new TextEncoder();
        const body = new ReadableStream({ start(c) { r.stream!.forEach((s) => c.enqueue(enc.encode(s))); c.close(); } });
        return new Response(body, { status: r.status ?? 200, headers: { "content-type": "text/event-stream" } });
      }
      return new Response(JSON.stringify(r.body ?? null), { status: r.status ?? 200, headers: { "content-type": "application/json" } });
    }
    throw new Error(`unmocked fetch: ${init.method ?? "GET"} ${url}`);
  });
  vi.stubGlobal("fetch", fn);
  return { fn, calls };
}

export const sse = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify({ type: event, ...(data as object) })}\n\n`;
