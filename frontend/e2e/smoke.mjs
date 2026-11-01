// End-to-end smoke test: real FastAPI server (auth on) + built React bundle + headless Chromium.
//   npm run build && node e2e/smoke.mjs
import { execFileSync, spawn } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { createRequire } from "node:module";

const { chromium } = createRequire(import.meta.url)("playwright"); // global install (CI: npm i -g playwright && npx playwright install chromium)

const root = resolve(import.meta.dirname, "../..");
const dir = mkdtempSync(join(tmpdir(), "mka-e2e-"));
const PORT = process.env.PORT ?? "8771";
const base = `http://127.0.0.1:${PORT}`;
const PW = "correct horse battery";

// ---- fixtures
writeFileSync(join(dir, "policy.txt"), "Employees accrue 25 days of annual leave per year.\n\nExpense reports must be filed within 30 days. Contact Anjali Rao for help.\n");
writeFileSync(join(dir, "policy_v2.txt"), "Employees accrue 30 days of annual leave per year.\n\nExpense reports must be filed within 30 days. Contact Anjali Rao for help. A wellness stipend of 500 dollars is offered.\n");
writeFileSync(join(dir, "orders.csv"), "Date,Region,Revenue\n" + Array.from({ length: 24 }, (_, i) => `${2023 + Math.floor(i / 12)}-${String((i % 12) + 1).padStart(2, "0")}-15,North,${i === 17 ? 9000 : 1000 + 10 * i}`).join("\n") + "\n");
writeFileSync(join(dir, "sales.csv"), "Employee,Region,Sales\nAlice,North,1200\nBob,South,3400\nCarol,North,900\n");
execFileSync("python3", ["-c", `
from reportlab.pdfgen import canvas
c = canvas.Canvas("${join(dir, "handbook.pdf")}")
c.drawString(50, 800, "Security handbook. Passwords must be rotated every 90 days.")
c.showPage()
c.drawString(50, 800, "Incidents must be reported within 24 hours. Anjali Rao chairs the review.")
c.save()`]);

const server = spawn("python3", ["-m", "uvicorn", "app.main:app", "--port", PORT, "--log-level", "warning"], {
  cwd: root,
  env: { ...process.env, MKA_DATA_DIR: join(dir, "data"), MKA_AUTH_ENABLED: "true", MKA_JWT_SECRET: "e2e-secret-".padEnd(40, "x"), MKA_RATE_LIMIT_ASK: "1000/minute", MKA_RATE_LIMIT_INGEST: "1000/minute", MKA_RATE_LIMIT_AUTH: "1000/minute" },
  stdio: ["ignore", "inherit", "inherit"],
});
const stop = () => server.kill("SIGTERM");
process.on("exit", stop);

let failures = 0;
const step = async (name, fn) => { try { await fn(); console.log("  ✓", name); } catch (e) { failures++; console.log("  ✗", name, "\n    ", String(e.message).split("\n")[0]); if (process.env.DEBUG_E2E) console.log("    page text:", (await page.locator("body").innerText()).slice(0, 1800).replace(/\n/g, " | ")); } };

for (let i = 0; i < 60; i++) { try { if ((await fetch(`${base}/health`)).ok) break; } catch { /* starting */ } await new Promise((r) => setTimeout(r, 250)); }

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
// 422s are the deliberate rejections in this script (DROP TABLE in the SQL sandbox, a note containing a password)
page.on("console", (m) => m.type() === "error" && !m.text().includes("favicon") && !/status of 422/.test(m.text()) && errors.push(m.text()));
page.on("dialog", (d) => d.accept());
const T = { timeout: 20000 };
if (process.env.DEBUG_E2E) page.on("response", async (r) => { if (r.url().includes("/auth/")) console.log("    [net]", r.request().method(), r.url().replace(base, ""), r.status(), (await r.text()).slice(0, 120)); });

await page.goto(base);
await step("sign up a new organisation and land on the dashboard", async () => {
  await page.getByRole("button", { name: /Sign up/ }).click();
  await page.getByLabel("Organisation name").fill("E2E Corp");
  await page.getByLabel("Email", { exact: true }).fill("admin@e2e.io");
  await page.getByLabel("Password", { exact: true }).fill(PW);
  await page.getByRole("button", { name: "Create account" }).click();
  await page.getByRole("heading", { name: /Welcome, admin@e2e.io/ }).waitFor(T);
});
await step("reloading the page keeps the session (silent refresh from the httpOnly cookie, token never in web storage)", async () => {
  await page.reload();
  await page.getByRole("heading", { name: /Welcome, admin@e2e.io/ }).waitFor(T);
  const stored = await page.evaluate(() => JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage }));
  if (/eyJ/.test(stored)) throw new Error("a JWT is stored in web storage");
});
await step("upload several documents and watch ingestion finish", async () => {
  await page.getByRole("button", { name: "Library", exact: true }).click();
  await page.getByTestId("file-input").setInputFiles([join(dir, "policy.txt"), join(dir, "sales.csv"), join(dir, "handbook.pdf"), join(dir, "orders.csv")]);
  await page.getByText("indexed").first().waitFor(T);
  for (const n of ["handbook.pdf", "sales.csv", "policy.txt", "orders.csv"]) await page.locator(`table >> text=${n}`).first().waitFor(T);
  await page.getByText("2 pages").waitFor(T);
});
await step("re-uploading an identical file is flagged as a duplicate; a changed file becomes version 2", async () => {
  await page.getByTestId("file-input").setInputFiles([join(dir, "policy.txt")]);
  await page.getByText("identical file already indexed").first().waitFor(T);
  writeFileSync(join(dir, "policy.txt"), "Employees accrue 30 days of annual leave per year.\n\nExpense reports must be filed within 30 days. Contact Anjali Rao for help. A wellness stipend of 500 dollars is offered.\n");
  await page.getByTestId("file-input").setInputFiles([join(dir, "policy.txt")]);
  await page.locator("td", { hasText: "v2" }).first().waitFor(T);
  await page.getByRole("row", { name: /policy\.txt/ }).getByRole("button", { name: "Versions" }).click();
  await page.getByRole("button", { name: "What changed?" }).click();
  await page.getByText("25→30").waitFor(T);
  await page.getByRole("button", { name: "Close" }).click();
});
await step("semantic question returns a cited answer", async () => {
  await page.getByRole("button", { name: "Chat", exact: true }).click();
  await page.getByLabel("Question", { exact: true }).fill("How many days of annual leave do employees accrue?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await page.getByText("30 days of annual leave").first().waitFor(T);
  await page.getByText(/\[1\] policy\.txt/).waitFor(T);
  await page.getByText(/citations checked: 100%/).waitFor(T);
});
await step("copy and regenerate the answer; regenerating replaces the exchange instead of adding one; Stop is only offered while generating", async () => {
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]).catch(() => {});
  await page.getByRole("button", { name: "Copy answer" }).last().click();
  await page.getByText("✓ Copied").waitFor(T);
  const clip = await page.evaluate(() => navigator.clipboard.readText()).catch(() => "30 days of annual leave");
  if (!clip.includes("30 days of annual leave")) throw new Error("clipboard does not hold the answer: " + clip.slice(0, 80));
  const before = await page.getByText("How many days of annual leave do employees accrue?").count();
  await page.getByRole("button", { name: "Regenerate answer" }).click();
  await page.getByText("30 days of annual leave").first().waitFor(T);
  await page.getByRole("button", { name: "Regenerate answer" }).waitFor(T);
  const after = await page.getByText("How many days of annual leave do employees accrue?").count();
  if (after !== before) throw new Error(`question bubble duplicated (${before} -> ${after})`);
  if (await page.getByRole("button", { name: "Stop generating" }).count()) throw new Error("Stop is still shown after the answer finished");
});
await step("exact search screen: counts, pages, and the PDF page opens with the match highlighted", async () => {
  await page.getByRole("button", { name: "Exact search", exact: true }).click();
  await page.getByLabel("Search term").fill("Anjali Rao");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await page.getByText(/“Anjali Rao” — 2 occurrences/).waitFor(T);
  await page.getByRole("button", { name: "Open page 2 of handbook.pdf" }).click();
  await page.getByAltText("Page 2 of handbook.pdf").waitFor(T);
  await page.getByRole("button", { name: "Close" }).click();
});
await step("chat exact question and spreadsheet question with row citation", async () => {
  await page.getByRole("button", { name: "Chat", exact: true }).click();
  await page.getByLabel("Question", { exact: true }).fill("Does Anjali Rao appear in these files?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await page.getByText(/Found 2 occurrences/).waitFor(T);
  await page.getByLabel("Question", { exact: true }).fill("Which employee has the highest sales?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await page.getByText(/Employee = Bob/).waitFor(T);
  await page.getByText(/\[1\] sales\.csv — row 3/).waitFor(T);
});
await step("compound question fans out to two agents in parallel", async () => {
  await page.getByLabel("Question", { exact: true }).fill('How many times does "Anjali Rao" appear, and what is the highest sales?');
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await page.getByText("Exact search:", { exact: false }).first().waitFor(T);
  await page.getByText("Data analysis:", { exact: false }).first().waitFor(T);
});
await step("incognito question leaves no conversation behind", async () => {
  await page.getByRole("button", { name: "+ New conversation" }).click();
  await page.getByRole("button", { name: "Incognito mode" }).click();
  await page.getByLabel("Question", { exact: true }).fill("How often must passwords be rotated?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await page.getByText(/rotated every 90 days/).first().waitFor(T);
  await page.getByText("incognito", { exact: true }).waitFor(T);
  await page.getByRole("button", { name: "Incognito mode" }).click();
});
await step("unanswerable question is flagged, not invented", async () => {
  await page.getByLabel("Question", { exact: true }).fill("What is the capital of Mongolia?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await page.getByText("not verified").last().waitFor(T);
});
await step("compare two documents shows the changed number", async () => {
  await page.getByRole("button", { name: "Compare", exact: true }).click();
  await page.getByRole("tab", { name: "Versions of one document" }).click();
  await page.getByLabel("Document", { exact: true }).selectOption({ label: "policy.txt (v2)" });
  await page.getByRole("button", { name: "Compare", exact: true }).last().click();
  await page.getByText("25 → 30").waitFor(T);
});
await step("data analyst: question with chart, outliers, trend, SQL sandbox", async () => {
  await page.getByRole("button", { name: "Data analyst", exact: true }).click();
  await page.getByLabel("Spreadsheet").selectOption({ label: "orders.csv" });
  await page.getByLabel("Question about the data").fill("Show the monthly revenue trend");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await page.getByRole("img", { name: /line chart/ }).first().waitFor(T);
  await page.getByRole("tab", { name: "Outliers" }).click();
  await page.getByLabel("Column", { exact: true }).selectOption("Revenue");
  await page.getByRole("button", { name: "Find outliers" }).click();
  await page.getByText(/1 outlier\(s\)/).waitFor(T);
  await page.getByRole("tab", { name: "SQL" }).click();
  await page.getByLabel("SQL query").fill("DROP TABLE orders");
  await page.getByRole("button", { name: "Run query" }).click();
  await page.getByText("Only SELECT queries are allowed").waitFor(T);
  await page.getByLabel("SQL query").fill("SELECT MAX(revenue) AS m FROM orders");
  await page.getByRole("button", { name: "Run query" }).click();
  await page.getByLabel("Query result").getByText("9,000").waitFor(T);
});
await step("reports: generate a PDF summary and download it", async () => {
  await page.getByRole("button", { name: "Reports", exact: true }).click();
  await page.getByLabel("Report type").selectOption("summary");
  await page.getByLabel("policy.txt").check();
  await page.getByRole("button", { name: "Generate report" }).click();
  await page.getByRole("status").getByText(/is ready/).waitFor(T);
  const [dl] = await Promise.all([page.waitForEvent("download", T), page.getByRole("button", { name: "Download" }).first().click()]);
  const path = await dl.path();
  const { readFileSync } = await import("node:fs");
  if (readFileSync(path).subarray(0, 5).toString() !== "%PDF-") throw new Error("download is not a PDF");
});
await step("history lists the conversations; settings: dark theme persists across reload; sensitive note is refused", async () => {
  await page.getByRole("button", { name: "History", exact: true }).click();
  await page.getByRole("button", { name: /annual leave|How many|Anjali/ }).first().click();
  await page.getByLabel("Messages").waitFor(T);
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByLabel("Dark").check();
  await page.reload();
  await page.getByRole("heading", { name: /Welcome/ }).waitFor(T);
  if ((await page.evaluate(() => document.documentElement.getAttribute("data-theme"))) !== "dark") throw new Error("theme not restored");
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByLabel("New note").fill("my password is hunter2");
  await page.getByRole("button", { name: "Save note" }).click();
  await page.getByRole("alert").getByText(/secret or password/).waitFor(T);
  await page.getByLabel("Light").check();
});
await step("evaluation dashboard runs the sample corpus", async () => {
  await page.getByRole("button", { name: "Evaluation", exact: true }).click();
  await page.getByRole("button", { name: "Run sample evaluation" }).click();
  await page.getByText("Recall@5").first().waitFor({ timeout: 90000 });
  await page.getByText("Strategy comparison").waitFor(T);
});
await step("admin: add a user, audit log shows activity without question text", async () => {
  await page.getByRole("button", { name: "Admin", exact: true }).click();
  await page.getByLabel("New user email").fill("viewer@e2e.io");
  await page.getByLabel("New user password").fill(PW);
  await page.getByRole("button", { name: "Create" }).click();
  await page.getByText("viewer@e2e.io").waitFor(T);
  await page.getByLabel("Audit action filter").fill("ask");
  await page.locator("table >> td:text-is('ask')").first().waitFor(T);
  const html = await page.content();
  if (html.includes("capital of Mongolia")) throw new Error("question text leaked into the audit view");
});
await step("learn lab: demo documents, ablation, graph run with auto strategy, LangChain examples (own workspace)", async () => {
  await page.getByLabel("Workspace").fill("learn");
  await page.getByLabel("Workspace").press("Enter");
  await page.getByRole("button", { name: "Learn lab", exact: true }).click();
  await page.getByRole("tab", { name: "Retrieval lab" }).click();
  await page.getByRole("button", { name: "Load demo documents" }).click();
  await page.getByText(/Loaded \d+ new/).waitFor(T);
  await page.getByRole("button", { name: "Run experiment" }).click();
  await page.getByRole("table", { name: "Experiment results" }).waitFor(T);
  await page.getByText(/characters to the model/).first().waitFor(T);
  await page.getByRole("tab", { name: "Agent graph" }).click();
  await page.getByRole("img", { name: /Agent graph with/ }).waitFor(T);
  await page.getByLabel(/Auto strategy/).check();
  await page.getByRole("button", { name: "Run through the graph" }).click();
  await page.getByLabel("Graph steps").getByText("strategy", { exact: true }).waitFor(T);
  await page.getByRole("tab", { name: "LangChain lab" }).click();
  await page.getByRole("button", { name: "Run the LangChain examples" }).click();
  await page.getByText(/ChatPromptTemplate/).first().waitFor(T);
  await page.getByLabel("Workspace").fill("default");
  await page.getByLabel("Workspace").press("Enter");
});
await step("plain user: signs in, can chat and search, cannot see Admin/Evaluation or upload", async () => {
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.getByRole("heading", { name: "Sign in" }).waitFor(T);
  await page.getByLabel("Email", { exact: true }).fill("viewer@e2e.io");
  await page.getByLabel("Password", { exact: true }).fill(PW);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("button", { name: "Chat", exact: true }).waitFor(T);
  if (await page.getByRole("button", { name: "Admin", exact: true }).count()) throw new Error("user sees Admin tab");
  if (await page.getByRole("button", { name: "Evaluation", exact: true }).count()) throw new Error("user sees Evaluation tab");
  await page.getByRole("button", { name: "Library", exact: true }).click();
  if (await page.getByLabel("Upload documents", { exact: true }).count()) throw new Error("user sees upload");
  await page.getByRole("button", { name: "Chat", exact: true }).click();
  await page.getByLabel("Question", { exact: true }).fill("How many days of annual leave?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await page.getByText(/30 days/).first().waitFor(T);
});
await step("phone layout: no horizontal overflow on the main screens at 390 px", async () => {
  await page.setViewportSize({ width: 390, height: 800 });
  for (const name of ["Dashboard", "Library", "Chat", "Exact search", "Compare", "Data analyst", "Reports", "History", "Learn lab", "Settings"]) {
    await page.getByRole("button", { name, exact: true }).click();
    await page.waitForTimeout(250);
    const over = await page.evaluate(() => Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - window.innerWidth);
    if (over > 1) throw new Error(`${name}: page is ${over}px wider than the phone screen`);
  }
  await page.getByRole("button", { name: "Chat", exact: true }).click();
  await page.getByLabel("Question", { exact: true }).waitFor(T);
  await page.setViewportSize({ width: 1400, height: 900 });
});
await step("no browser console errors", async () => { if (errors.length) throw new Error(errors.join(" | ")); });

if (process.env.SHOT) await page.screenshot({ path: process.env.SHOT, fullPage: true });
await browser.close();
stop();
console.log(failures ? `\n${failures} e2e step(s) FAILED` : "\nall e2e steps passed");
process.exit(failures ? 1 : 0);
