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
const step = async (name, fn) => { try { await fn(); console.log("  ✓", name); } catch (e) { failures++; console.log("  ✗", name, "\n    ", String(e.message).split("\n")[0]); if (process.env.DEBUG_E2E) console.log("    page text:", (await page.locator("body").innerText()).slice(0, 400).replace(/\n/g, " | ")); } };

for (let i = 0; i < 60; i++) { try { if ((await fetch(`${base}/health`)).ok) break; } catch { /* starting */ } await new Promise((r) => setTimeout(r, 250)); }

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
page.on("console", (m) => m.type() === "error" && !m.text().includes("favicon") && errors.push(m.text()));
page.on("dialog", (d) => d.accept());
const T = { timeout: 20000 };
if (process.env.DEBUG_E2E) page.on("response", async (r) => { if (r.url().includes("/auth/")) console.log("    [net]", r.request().method(), r.url().replace(base, ""), r.status(), (await r.text()).slice(0, 120)); });

await page.goto(base);
await step("sign up a new organisation", async () => {
  await page.getByRole("button", { name: /Sign up/ }).click();
  await page.getByLabel("Organisation name").fill("E2E Corp");
  await page.getByLabel("Email", { exact: true }).fill("admin@e2e.io");
  await page.getByLabel("Password", { exact: true }).fill(PW);
  await page.getByRole("button", { name: "Create account" }).click();
  await page.getByRole("button", { name: "Documents", exact: true }).waitFor(T);
});
await step("upload several documents and watch ingestion finish", async () => {
  await page.getByTestId("file-input").setInputFiles([join(dir, "policy.txt"), join(dir, "sales.csv"), join(dir, "handbook.pdf")]);
  await page.getByText("indexed").first().waitFor(T);
  await page.locator("table >> text=handbook.pdf").waitFor(T);
  await page.locator("table >> text=sales.csv").waitFor(T);
  await page.locator("table >> text=policy.txt").waitFor(T);
  await page.getByText("2 pages").waitFor(T);
});
await step("semantic question returns a cited answer", async () => {
  await page.getByRole("button", { name: "Chat", exact: true }).click();
  await page.getByLabel("Question", { exact: true }).fill("How many days of annual leave do employees accrue?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await page.getByText("25 days of annual leave").first().waitFor(T);
  await page.getByText(/\[1\] policy\.txt/).waitFor(T);
  await page.getByText(/confidence:/).first().waitFor(T);
});
await step("exact search reports the count and PDF page numbers", async () => {
  await page.getByLabel("Question", { exact: true }).fill("Does Anjali Rao appear in these files?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await page.getByText(/Found 2 occurrences/).waitFor(T);
  await page.getByText(/Pages — handbook\.pdf: 2/).waitFor(T);
});
await step("spreadsheet question is computed, with a row citation", async () => {
  await page.getByLabel("Question", { exact: true }).fill("Which employee has the highest sales?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await page.getByText(/Employee = Bob/).waitFor(T);
  await page.getByText(/\[1\] sales\.csv — row 3/).waitFor(T);
});
await step("search filters restrict retrieval to a file type", async () => {
  await page.getByRole("button", { name: "pdf", exact: true }).click();
  await page.getByLabel("Question", { exact: true }).fill("How often must passwords be rotated?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await page.getByText(/rotated every 90 days/).first().waitFor(T);
  await page.getByText(/handbook\.pdf — page 1/).first().waitFor(T);
});
await step("unanswerable question is flagged, not invented", async () => {
  await page.getByRole("button", { name: "pdf", exact: true }).click();  // clear filter
  await page.getByLabel("Question", { exact: true }).fill("What is the capital of Mongolia?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await page.getByText("not verified").waitFor(T);
});
await step("conversation history is kept and reopenable", async () => {
  const hist = page.getByLabel("Conversations").getByRole("button", { name: /annual leave|How many/ });
  await hist.first().waitFor(T);
  await page.getByRole("button", { name: "+ New conversation" }).click();
  await hist.first().click();
  await page.getByText(/25 days of annual leave/).first().waitFor(T);
});
await step("evaluation dashboard runs the sample corpus", async () => {
  await page.getByRole("button", { name: "Evaluation", exact: true }).click();
  await page.getByRole("button", { name: "Run sample evaluation" }).click();
  await page.getByText("Recall@5").first().waitFor({ timeout: 90000 });
  await page.getByText("Strategy comparison").waitFor(T);
  await page.getByText("hybrid + rerank + parent-child + corrective").waitFor(T);
});
await step("admin: add a viewer, audit log shows activity without question text", async () => {
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
await step("viewer: signs in, can chat, cannot see Admin/Evaluation/upload", async () => {
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.getByRole("heading", { name: "Sign in" }).waitFor(T);
  await page.getByLabel("Email", { exact: true }).fill("viewer@e2e.io");
  await page.getByLabel("Password", { exact: true }).fill(PW);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("button", { name: "Chat", exact: true }).waitFor(T);
  if (await page.getByRole("button", { name: "Admin", exact: true }).count()) throw new Error("viewer sees Admin tab");
  if (await page.getByRole("button", { name: "Evaluation", exact: true }).count()) throw new Error("viewer sees Evaluation tab");
  if (await page.getByLabel("Upload documents", { exact: true }).count()) throw new Error("viewer sees upload");
  await page.getByRole("button", { name: "Chat", exact: true }).click();
  await page.getByLabel("Question", { exact: true }).fill("How many days of annual leave?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await page.getByText(/25 days/).first().waitFor(T);
});
await step("no browser console errors", async () => { if (errors.length) throw new Error(errors.join(" | ")); });

if (process.env.SHOT) await page.screenshot({ path: process.env.SHOT, fullPage: true });
await browser.close();
stop();
console.log(failures ? `\n${failures} e2e step(s) FAILED` : "\nall e2e steps passed");
process.exit(failures ? 1 : 0);
