import { vi } from "vitest";

type Resp = { status?: number; body?: unknown; stream?: string[]; rawStream?: ReadableStream<Uint8Array> };
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
      if (r.rawStream) return new Response(r.rawStream, { status: r.status ?? 200, headers: { "content-type": "text/event-stream" } });
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

/** A /ask/stream whose events are pushed by the test, one at a time, so the UI can be inspected between chunks. Honors AbortController like fetch does. */
export function controlledStream(extra: Record<string, unknown> = {}) {
  const enc = new TextEncoder();
  let ctl!: ReadableStreamDefaultController<Uint8Array>;
  const state = { signal: undefined as AbortSignal | undefined, bodies: [] as Record<string, unknown>[], requests: 0 };
  const base: Record<string, unknown> = { "/conversations": { body: [] }, "/sources": { body: [] } };
  const handlers = {
    ...base, ...extra,
    "POST /ask/stream": (_u: string, init: RequestInit) => {
      state.requests++;
      state.signal = init.signal ?? undefined;
      state.bodies.push(JSON.parse(String(init.body)));
      const body = new ReadableStream<Uint8Array>({ start(c) { ctl = c; init.signal?.addEventListener("abort", () => c.error(new DOMException("Aborted", "AbortError"))); } });
      return { rawStream: body };
    },
  };
  return { handlers, state, push: (s: string) => ctl.enqueue(enc.encode(s)), close: () => ctl.close(), fail: (e: unknown) => ctl.error(e) };
}
