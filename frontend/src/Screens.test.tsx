import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Admin } from "./Admin";
import { Analyst } from "./Analyst";
import { Chart } from "./Chart";
import { Compare } from "./Compare";
import { Dashboard } from "./Dashboard";
import { ExactSearch } from "./ExactSearch";
import { History } from "./History";
import { Preview } from "./Preview";
import { Reports } from "./Reports";
import { Settings } from "./Settings";
import { applyTheme, loadTheme } from "./theme";
import { mockFetch } from "./testutil";
import type { ChartSpec, User } from "./types";

afterEach(() => vi.unstubAllGlobals());
const me: User = { id: "u1", tenant_id: "t", email: "a@x.io", role: "admin" };
const pdf = { id: "s1", name: "policy.pdf", kind: "pdf", status: "ready", tabular: false, warnings: [], needs_reindex: false, visibility: "tenant", created_at: "", version: 1 };
const sheet = { id: "x1", name: "orders.csv", kind: "csv", status: "ready", tabular: true, warnings: [], needs_reindex: false, visibility: "tenant", created_at: "", tables: [{ sheet: null, columns: ["Date", "Revenue"], rows: 24 }] };

describe("Chart", () => {
  const spec: ChartSpec = { type: "bar", title: "Revenue by region", x_label: "region", y_label: "Revenue", labels: ["North", "South"], series: [{ name: "Revenue", values: [10, 30] }] };
  it("renders an accessible SVG with a text summary and per-point tooltips", () => {
    const { container } = render(<Chart spec={spec} />);
    expect(screen.getByRole("img", { name: /bar chart "Revenue by region".*from 10 to 30/ })).toBeInTheDocument();
    expect(container.querySelectorAll("rect").length).toBe(2);
    expect(container.querySelector("title")?.textContent).toBe("North: 10 (Revenue)");
  });
  it("draws lines, handles gaps and empty data", () => {
    const { container, rerender } = render(<Chart spec={{ ...spec, type: "line", labels: ["a", "b", "c"], series: [{ name: "s", values: [1, null, 3] }] }} />);
    expect(container.querySelectorAll("circle").length).toBe(2);
    rerender(<Chart spec={{ ...spec, labels: [], series: [] }} />);
    expect(screen.getByText("No data to chart.")).toBeInTheDocument();
  });
});

describe("Dashboard", () => {
  it("summarises the library, jobs and problems", async () => {
    mockFetch({
      "/sources": { body: [{ ...pdf, classification: { label: "policy", confidence: 0.9, method: "keywords" } }, { ...sheet, needs_reindex: true }] },
      "/jobs": { body: [{ id: "j", name: "big.pdf", status: "running", progress: 10, attempts: 1, kind: "file" }, { id: "k", name: "bad.pdf", status: "failed", error: "corrupt", progress: 0, attempts: 1, kind: "file" }] },
      "/conversations": { body: [{ id: "c", workspace: "w", title: "Leave policy", updated_at: "2026-01-02T03:04:05" }] }, "/reports": { body: [] },
    });
    const go = vi.fn();
    render(<Dashboard workspace="w" user={me} health={{ status: "ok", version: "3.0.0", embedder: "hash", llm: "none", vector_store: "local", auth_enabled: true }} go={go} />);
    expect(await screen.findByText("Leave policy")).toBeInTheDocument();
    const tiles = screen.getByLabelText("Key figures");
    expect(within(tiles).getByText("documents in “w”").previousSibling).toHaveTextContent("2");
    expect(within(tiles).getByText("ingestion jobs running").previousSibling).toHaveTextContent("1");
    expect(screen.getByText(/bad\.pdf: corrupt/)).toBeInTheDocument();
    expect(screen.getByText(/orders\.csv: needs re-index/)).toBeInTheDocument();
    expect(screen.getByText("policy: 1")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Upload documents" }));
    expect(go).toHaveBeenCalledWith("documents");
  });
});

describe("Exact search", () => {
  it("shows counts per document, clickable pages, matches and pagination", async () => {
    const { calls } = mockFetch({
      "POST /search/exact": (url) => ({ body: { term: "Anjali Rao", count: 45, locations_with_match: 45, by_source: [{ name: "policy.pdf", count: 45 }], pages: { "policy.pdf": [3, 7] }, limit: 20, offset: url.includes("offset=20") ? 20 : 0,
        matches: [{ source_id: "s1", source: "policy.pdf", location: url.includes("offset=20") ? "page 9" : "page 3", loc: { page: 3 }, excerpt: "…contact Anjali Rao…" }], rules: "case-insensitive, whole-word matching", sources_searched: 1 } }),
      "/pages/3/image": { body: null }, "/sources": { body: [pdf] },
    });
    render(<ExactSearch workspace="w" />);
    await userEvent.type(screen.getByLabelText("Search term"), "Anjali Rao");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByText(/45 occurrences in 45 locations/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open page 7 of policy.pdf" })).toBeInTheDocument();
    expect(screen.getByText(/policy\.pdf — page 3/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Next/ }));
    expect(await screen.findByText(/policy\.pdf — page 9/)).toBeInTheDocument();
    expect(calls.some((c) => c.url.includes("limit=20&offset=20"))).toBe(true);
  });
  it("reports a zero count honestly and surfaces errors", async () => {
    mockFetch({ "POST /search/exact": { body: { term: "zzz", count: 0, locations_with_match: 0, by_source: [], pages: {}, matches: [], limit: 20, offset: 0, rules: "r", sources_searched: 2 } }, "/sources": { body: [] } });
    render(<ExactSearch workspace="w" />);
    await userEvent.type(screen.getByLabelText("Search term"), "zzz{enter}");
    expect(await screen.findByText(/No occurrences found/)).toBeInTheDocument();
    mockFetch({ "POST /search/exact": { status: 404, body: { detail: "No sources available" } }, "/sources": { body: [] } });
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No sources available");
  });
});

describe("Citation preview", () => {
  beforeEach(() => { vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: () => "blob:page", revokeObjectURL: () => {} })); });
  it("shows the highlighted PDF page and navigates between pages", async () => {
    const { calls } = mockFetch({ "/pages/": { body: "png" } });
    render(<Preview workspace="w" citation={{ source_id: "s1", source: "policy.pdf", location: "page 2", excerpt: "annual leave", loc: { page: 2 } }} onClose={() => {}} />);
    expect(await screen.findByAltText("Page 2 of policy.pdf")).toBeInTheDocument();
    expect(calls[0].url).toContain("/sources/s1/pages/2/image?highlight=annual%20leave");
    await userEvent.click(screen.getByRole("button", { name: /Page 3/ }));
    await waitFor(() => expect(calls.some((c) => c.url.includes("/pages/3/image") && !c.url.includes("highlight"))).toBe(true));
  });
  it("falls back to the stored passage for non-PDF sources and web citations", async () => {
    mockFetch({ "/passage": { body: { source: "notes.txt", kind: "txt", location: "line 4", text: "the cited sentence", before: "earlier", after: "later" } } });
    render(<Preview workspace="w" citation={{ source_id: "s2", source: "notes.txt", location: "line 4", excerpt: "the cited", loc: { line: 4 } }} onClose={() => {}} />);
    expect(await screen.findByText("the cited sentence")).toBeInTheDocument();
    expect(screen.getByText(/earlier/)).toBeInTheDocument();
    render(<Preview workspace="w" citation={{ source_id: "web", source: "https://example.com/p", location: "https://example.com/p", excerpt: "web text", origin: "web" }} onClose={() => {}} />);
    expect(screen.getByText(/External web page/)).toBeInTheDocument();
  });
});

describe("Compare", () => {
  it("diffs two documents and shows number changes", async () => {
    const { calls } = mockFetch({
      "POST /compare": { body: { left: { name: "a.txt" }, right: { name: "b.txt" }, summary: { segments_a: 3, segments_b: 4, unchanged: 2, changed: 1, added: 1, removed: 0, similarity: 0.5 }, truncated: false,
        changed: [{ before: { text: "25 days", loc: {} }, after: { text: "30 days", loc: {} }, similarity: 0.8, number_changes: [{ from: "25", to: "30" }] }], added: [{ text: "A new stipend", loc: {} }], removed: [] } },
      "/sources": { body: [{ ...pdf, id: "a", name: "a.txt" }, { ...pdf, id: "b", name: "b.txt" }] },
    });
    render(<Compare workspace="w" />);
    await screen.findAllByRole("option", { name: "a.txt" });
    await userEvent.selectOptions(screen.getByLabelText("Document A"), "a");
    await userEvent.selectOptions(screen.getByLabelText("Document B"), "b");
    await userEvent.click(screen.getByRole("button", { name: "Compare" }));
    expect(await screen.findByText("25 → 30")).toBeInTheDocument();
    expect(screen.getByText("A new stipend")).toBeInTheDocument();
    expect(screen.getByText("50%")).toBeInTheDocument();
    expect(JSON.parse(String(calls.find((c) => c.url.includes("/compare"))!.init.body))).toEqual({ source_ids: ["a", "b"], mode: "diff" });
  });
  it("labels heuristic contradictions as candidates", async () => {
    mockFetch({
      "POST /compare": { body: { method: "heuristic", candidates_examined: 1, note: "Heuristic candidates - review each pair.", contradictions: [{ type: "numeric", overlap: 0.9, verdict: "candidate", a: { source: "hr.txt", text: "25 days", location: "line 1" }, b: { source: "faq.txt", text: "30 days", location: "line 1" } }] } },
      "/sources": { body: [{ ...pdf, id: "a", name: "hr.txt" }, { ...pdf, id: "b", name: "faq.txt" }] },
    });
    render(<Compare workspace="w" />);
    await userEvent.click(screen.getByRole("tab", { name: "Find contradictions" }));
    await userEvent.click(await screen.findByLabelText("hr.txt"));
    await userEvent.click(screen.getByLabelText("faq.txt"));
    await userEvent.click(screen.getByRole("button", { name: "Compare" }));
    expect(await screen.findByText("1 candidate contradiction(s)")).toBeInTheDocument();
    expect(screen.getByText(/Heuristic candidates/)).toBeInTheDocument();
  });
});

describe("Data analyst", () => {
  it("answers questions with a chart, profiles, flags outliers and runs read-only SQL", async () => {
    const chart: ChartSpec = { type: "line", title: "sum of Revenue by month", x_label: "month", y_label: "Revenue", labels: ["2023-01", "2023-02"], series: [{ name: "Revenue", values: [1000, 1010] }] };
    const { calls } = mockFetch({
      "POST /analytics/ask": { body: { answer: "Sum of Revenue by month: up", route: "data", confidence: "high", verified: true, citations: [{ source_id: "x1", source: "orders.csv", location: "row 3", excerpt: "Date: 2023-02-15" }], limitations: [], details: { chart }, needs_input: false, followups: [], usage: {} } },
      "/analytics/profile": { body: { rows: 24, columns: [{ name: "Revenue", type: "number", missing: 0, missing_pct: 0, unique: 24, min: 1000, max: 9000, mean: 1500 }], duplicate_rows: 0, duplicate_row_numbers: [] } },
      "/analytics/anomalies": { body: { column: "Revenue", method: "iqr", count: 1, bounds: { low: 900, high: 1400 }, rows: [{ row: 19, value: 9000, score: 12, values: { Date: "2024-06-15" } }] } },
      "POST /analytics/sql": (_u, init) => String(init.body).includes("DROP") ? { status: 422, body: { detail: "Only SELECT queries are allowed" } } : { body: { sql: "SELECT 1", columns: ["m"], rows: [[9000]], row_count: 1, truncated: false } },
      "/analytics/tables": { body: { tables: [{ table: "orders", source: "orders.csv", sheet: null, rows: 24, columns: [{ name: "revenue", original: "Revenue", type: "REAL" }] }] } },
      "/sources": { body: [sheet] },
    });
    render(<Analyst workspace="w" />);
    await userEvent.type(await screen.findByLabelText("Question about the data"), "monthly trend{enter}");
    expect(await screen.findByRole("img", { name: /line chart "sum of Revenue by month"/ })).toBeInTheDocument();
    expect(screen.getByText(/1 source row/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Profile" }));
    expect(await screen.findByText("1,000")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Outliers" }));
    await userEvent.selectOptions(screen.getByLabelText("Column"), "Revenue");
    await userEvent.click(screen.getByRole("button", { name: "Find outliers" }));
    expect(await screen.findByText(/1 outlier\(s\); normal range 900 to 1,400/)).toBeInTheDocument();
    expect(screen.getByText("Date: 2024-06-15")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "SQL" }));
    await userEvent.clear(screen.getByLabelText("SQL query"));
    await userEvent.type(screen.getByLabelText("SQL query"), "DROP TABLE orders");
    await userEvent.click(screen.getByRole("button", { name: "Run query" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Only SELECT queries are allowed");
    await userEvent.clear(screen.getByLabelText("SQL query"));
    await userEvent.type(screen.getByLabelText("SQL query"), "SELECT MAX(revenue) m FROM orders");
    await userEvent.click(screen.getByRole("button", { name: "Run query" }));
    expect(await screen.findByLabelText("Query result")).toHaveTextContent("9,000");
    expect(calls.some((c) => c.url.includes("/analytics/anomalies") && c.url.includes("column=Revenue"))).toBe(true);
  });
  it("explains what to do when there is no spreadsheet", async () => {
    mockFetch({ "/sources": { body: [pdf] } });
    render(<Analyst workspace="w" />);
    expect(await screen.findByText(/Upload a CSV or Excel file/)).toBeInTheDocument();
  });
});

describe("Reports", () => {
  it("creates a report with the chosen options and lists it with a download button", async () => {
    let created = false;
    const item = { id: "r1", kind: "comparison", format: "docx", title: "Comparison report", status: "ready", size_bytes: 20480, created_at: "2026-01-02T03:04:05", workspace: "w", owner_id: "u", download_url: "/reports/r1/download" };
    const { calls } = mockFetch({
      "POST /reports": () => { created = true; return { status: 201, body: item }; },
      "/reports": () => ({ body: created ? [item] : [] }), "/sources": { body: [{ ...pdf, id: "a", name: "a.txt" }, { ...pdf, id: "b", name: "b.txt" }, sheet] },
    });
    render(<Reports workspace="w" />);
    await screen.findByText("No reports yet.");
    await userEvent.selectOptions(screen.getByLabelText("Report type"), "comparison");
    await userEvent.selectOptions(screen.getByLabelText("Format"), "docx");
    expect(screen.queryByLabelText("orders.csv")).toBeNull();              // comparison offers documents only
    await userEvent.click(screen.getByLabelText("a.txt"));
    await userEvent.click(screen.getByLabelText("b.txt"));
    await userEvent.click(screen.getByRole("button", { name: "Generate report" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Comparison report” is ready");
    expect(await screen.findByRole("button", { name: "Download" })).toBeInTheDocument();
    expect(JSON.parse(String(calls.find((c) => c.init.method === "POST" && c.url.endsWith("/reports"))!.init.body))).toMatchObject({ kind: "comparison", format: "docx", source_ids: ["a", "b"], params: { mode: "diff" } });
  });
  it("shows server validation errors", async () => {
    mockFetch({ "POST /reports": { status: 422, body: { detail: "A document comparison needs exactly two documents." } }, "/reports": { body: [] }, "/sources": { body: [] } });
    render(<Reports workspace="w" />);
    await userEvent.click(screen.getByRole("button", { name: "Generate report" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("exactly two documents");
  });
});

describe("History", () => {
  it("lists, filters and opens conversations; can make one private", async () => {
    const { calls } = mockFetch({
      "PATCH /conversations/c1": { body: { id: "c1", workspace: "w", title: "Leave", updated_at: "2026-01-01T00:00:00", memory_enabled: false } },
      "/conversations/c1/messages": { body: [{ id: 1, role: "user", content: "How many days?", created_at: "" }, { id: 2, role: "assistant", content: "25 days", meta: { citations: [{ source_id: "s1", source: "policy.pdf", location: "page 1", excerpt: "25 days", loc: { page: 1 } }] }, created_at: "" }] },
      "/conversations": { body: [{ id: "c1", workspace: "w", title: "Leave", updated_at: "2026-01-01T00:00:00", memory_enabled: true }, { id: "c2", workspace: "w", title: "Travel", updated_at: "2026-01-02T00:00:00" }] },
    });
    render(<History workspace="w" />);
    await userEvent.type(await screen.findByLabelText("Search conversations"), "leav");
    expect(screen.queryByText("Travel")).toBeNull();
    await userEvent.click(screen.getByText("Leave"));
    expect((await screen.findAllByText(/25 days/)).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Open citation 1 in context" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Make private/ }));
    expect(await screen.findByText("private")).toBeInTheDocument();
    expect(JSON.parse(String(calls.find((c) => c.init.method === "PATCH")!.init.body))).toEqual({ memory_enabled: false });
  });
});

describe("Settings", () => {
  beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });
  it("switches the theme and persists it", async () => {
    mockFetch({ "/memory/preferences": { body: { memory_enabled: true, long_term_memory: false } }, "/memory/facts": { body: [] }, "/admin/tenant-settings": { body: { retention_days_documents: null, retention_days_conversations: null, retention_days_audit: null, retention_days_reports: null, web_allowed: true, web_allowed_domains: [], redact_stored_messages: false } } });
    render(<Settings user={{ ...me, role: "user" }} authEnabled />);
    await userEvent.click(screen.getByLabelText("Dark"));
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(loadTheme()).toBe("dark");
    await userEvent.click(screen.getByLabelText("Follow my device"));
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
    expect(screen.queryByText("Organisation policy")).toBeNull();                 // admin-only
    applyTheme("light");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });
  it("manages memory notes and shows why a sensitive note was refused", async () => {
    let notes: object[] = [];
    mockFetch({
      "POST /memory/facts": (_u, init) => String(init.body).includes("password") ? { status: 422, body: { detail: "This looks like it contains secret or password" } } : (notes = [{ id: 1, text: "short answers", created_at: "" }], { status: 201, body: notes[0] }),
      "DELETE /memory/facts/1": () => { notes = []; return { body: { deleted: 1 } }; },
      "/memory/preferences": { body: { memory_enabled: true, long_term_memory: false } }, "/memory/facts": () => ({ body: notes }),
    });
    render(<Settings user={{ ...me, role: "user" }} authEnabled />);
    await userEvent.type(screen.getByLabelText("New note"), "my password is x{enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("secret or password");
    await userEvent.clear(screen.getByLabelText("New note"));
    await userEvent.type(screen.getByLabelText("New note"), "short answers{enter}");
    expect(await screen.findByText("short answers")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Delete note short answers" }));
    await waitFor(() => expect(screen.queryByText("short answers")).toBeNull());
  });
  it("lets admins save the organisation policy and preview a retention sweep", async () => {
    const saved: object[] = [];
    mockFetch({
      "PUT /admin/tenant-settings": (_u, init) => { saved.push(JSON.parse(String(init.body))); return { body: saved[0] }; },
      "/admin/tenant-settings": { body: { retention_days_documents: 90, retention_days_conversations: null, retention_days_audit: null, retention_days_reports: null, web_allowed: true, web_allowed_domains: ["example.com"], redact_stored_messages: false } },
      "POST /admin/maintenance/run": { body: { dry_run: true, results: { retention_documents: { removed: 3 }, cleanup_tokens: { removed: 0 } } } },
      "/memory/preferences": { body: { memory_enabled: true, long_term_memory: false } }, "/memory/facts": { body: [] },
    });
    render(<Settings user={me} authEnabled />);
    const days = await screen.findByLabelText("Documents");
    expect(days).toHaveValue(90);
    await userEvent.clear(screen.getByLabelText(/Approved domains/));
    await userEvent.type(screen.getByLabelText(/Approved domains/), "docs.python.org, example.org");
    await userEvent.click(screen.getByLabelText(/Mask e-mail addresses/));
    await userEvent.click(screen.getByRole("button", { name: "Save policy" }));
    await waitFor(() => expect(saved).toHaveLength(1));
    expect(saved[0]).toMatchObject({ retention_days_documents: 90, web_allowed_domains: ["docs.python.org", "example.org"], redact_stored_messages: true });
    await userEvent.click(screen.getByRole("button", { name: "Preview sweep" }));
    expect(await screen.findByText("3 would be removed")).toBeInTheDocument();
  });
});

describe("Security (two-step sign-in)", () => {
  it("enrols, shows recovery codes once, and requires password + code to turn off", async () => {
    let enabled = false;
    const { calls } = mockFetch({
      "/health": { body: {} }, "/memory/preferences": { body: { memory_enabled: true, long_term_memory: false } }, "/memory/facts": { body: [] },
      "/admin/tenant-settings": { body: {} },
      "GET /auth/mfa": () => ({ body: { enabled, recovery_codes_left: enabled ? 10 : 0 } }),
      "POST /auth/mfa/setup": { body: { secret: "JBSWY3DPEHPK3PXP", otpauth_uri: "otpauth://totp/x:a?secret=JBSWY3DPEHPK3PXP" } },
      "POST /auth/mfa/enable": () => { enabled = true; return { body: { enabled: true, recovery_codes: ["aaaa-bbbb-cccc", "dddd-eeee-ffff"] } }; },
      "POST /auth/mfa/disable": () => { enabled = false; return { body: { enabled: false } }; },
    });
    render(<Settings user={{ ...me, role: "user" }} authEnabled />);
    await userEvent.click(await screen.findByRole("button", { name: "Set up" }));
    expect(await screen.findByLabelText("Setup key")).toHaveTextContent("JBSWY3DPEHPK3PXP");
    await userEvent.type(screen.getByLabelText(/6-digit code it shows/), "123456");
    await userEvent.click(screen.getByRole("button", { name: "Turn on" }));
    expect(await screen.findByText(/shown only once/)).toBeInTheDocument();
    expect(screen.getByText(/aaaa-bbbb-cccc/)).toBeInTheDocument();
    await userEvent.type(await screen.findByLabelText("Password"), "correct horse battery");
    await userEvent.type(screen.getByLabelText("Code"), "654321");
    await userEvent.click(screen.getByRole("button", { name: "Turn off" }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/auth/mfa/disable"))).toBe(true));
    expect(JSON.parse(String(calls.find((c) => c.url.endsWith("/auth/mfa/disable"))!.init.body))).toEqual({ password: "correct horse battery", code: "654321" });
  });
});

describe("Admin insights", () => {
  it("shows usage, verified rate, feedback and the most cited documents", async () => {
    mockFetch({
      "/admin/insights": { body: { days: 30, answers: 12, verified_rate: 0.75, unverified: 3, without_citations: 2, per_day: [{ day: "2026-10-30", answers: 5 }, { day: "2026-10-31", answers: 7 }],
        routes: { semantic: 9, exact: 3 }, confidence: { high: 8 }, top_sources: [{ source: "policy.pdf", answers: 6 }], cost_usd: 0.0123, tokens: 4200,
        feedback: { up: 4, down: 1, down_by_route: { semantic: 1 } }, note: "Counts only conversations that were stored." } },
      "/admin/users": { body: [] }, "/admin/audit": { body: [] }, "/admin/tenant-settings": { body: {} }, "/admin/settings": { body: {} },
    });
    render(<Admin me={me} />);
    const panel = await screen.findByLabelText("Usage insights");
    expect(await within(panel).findByText("75%")).toBeInTheDocument();
    expect(within(panel).getByText("policy.pdf: 6")).toBeInTheDocument();
    expect(within(panel).getByText(/👍 4 \/ 👎 1/)).toBeInTheDocument();
    expect(within(panel).getByText("semantic: 9")).toBeInTheDocument();
  });
});
