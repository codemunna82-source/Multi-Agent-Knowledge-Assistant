import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mockFetch } from "../testutil";
import { CodeLab, resetCodeStatus, TaskLab } from "./CodeLab";
import type { CodeExample, Task } from "./types";

vi.mock("./CodeEditor", () => ({ default: ({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) => <textarea aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} /> }));
afterEach(() => vi.unstubAllGlobals());
beforeEach(() => resetCodeStatus());

const status = (available = true) => ({ available, reason: available ? null : "unprivileged namespaces are not permitted here", languages: available ? ["python"] : [], timeout_s: 10, memory_mb: 1536, network: false, setup: available ? null : "Enable user namespaces", preinstalled: [], limits: { code_bytes: 20000, output_bytes: 64000 } });
const run = (extra: object = {}) => ({ ok: true, stdout: "42\n", stderr: "", exit_code: 0, ms: 31, timed_out: false, truncated: false, unavailable: null, notes: [], error_help: null, passed: true, expected: "42", ...extra });
const example: CodeExample = { title: "Answer", language: "python", runnable: true, code: "print(6 * 7)", expected_output: "42", explain: [{ lines: "1", text: "prints the answer" }] };
const task: Task = { prompt: "Print 42.", starter: "# TODO", hint: "Use print.", expected_output: "42" };

describe("CodeLab", () => {
  it("runs the example in the sandbox, shows the console and tells that it matches the expected output", async () => {
    const { calls } = mockFetch({ "/academy/code/status": { body: status() }, "POST /academy/code/run": { body: run() } });
    render(<CodeLab example={example} lessonId="demo" index={0} />);
    await userEvent.click(await screen.findByRole("button", { name: /Run code/ }));
    const con = await screen.findByRole("region", { name: "Output console" });
    expect(within(con).getByText("42")).toBeInTheDocument();
    expect(within(con).getByText(/exit code 0 · 31 ms/)).toBeInTheDocument();
    expect(within(con).getByText(/matches the expected output/)).toBeInTheDocument();
    expect(JSON.parse(String(calls.find((c) => c.url.endsWith("/code/run"))!.init.body))).toEqual({ language: "python", code: "print(6 * 7)", lesson_id: "demo", task: "example", example: 0 });
  });

  it("edited code is a scratch run; reset restores the original; copy works", async () => {
    const writeText = vi.fn(async () => {});
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const { calls } = mockFetch({ "/academy/code/status": { body: status() }, "POST /academy/code/run": { body: run({ passed: null }) } });
    render(<CodeLab example={example} lessonId="demo" index={0} />);
    const ed = await screen.findByLabelText("Code: Answer");
    expect(screen.getByRole("button", { name: /Reset code/ })).toBeDisabled();
    await userEvent.clear(ed);
    await userEvent.type(ed, "print(1)");
    await userEvent.click(screen.getByRole("button", { name: /Run code/ }));
    await waitFor(() => expect(JSON.parse(String(calls.find((c) => c.url.endsWith("/code/run"))!.init.body)).task).toBe("scratch"));
    expect(screen.getByText(/your output can differ/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Copy code/ }));
    expect(writeText).toHaveBeenCalledWith("print(1)");
    await userEvent.click(screen.getByRole("button", { name: /Reset code/ }));
    expect(screen.getByLabelText("Code: Answer")).toHaveValue("print(6 * 7)");
  });

  it("explains errors in plain language and shows the expected output", async () => {
    mockFetch({ "/academy/code/status": { body: status() }, "POST /academy/code/run": { body: run({ ok: false, stdout: "", stderr: "NameError: name 'total' is not defined", exit_code: 1, passed: false, error_help: "The name 'total' is used before it exists.  |  Naam 'total' bana hone se pehle use hua." }) } });
    render(<CodeLab example={example} lessonId="demo" index={0} />);
    await userEvent.click(await screen.findByRole("button", { name: /Run code/ }));
    expect(await screen.findByText(/What this error means/)).toBeInTheDocument();
    expect(screen.getByText(/NameError/)).toBeInTheDocument();
    expect(screen.getByText(/Naam 'total'/)).toBeInTheDocument();
    expect(screen.getByText("Expected output")).toBeInTheDocument();
  });

  it("reports timeouts", async () => {
    mockFetch({ "/academy/code/status": { body: status() }, "POST /academy/code/run": { body: run({ ok: false, stdout: "", exit_code: null, timed_out: true, passed: false }) } });
    render(<CodeLab example={example} lessonId="demo" index={0} />);
    await userEvent.click(await screen.findByRole("button", { name: /Run code/ }));
    expect(await screen.findByText(/endless loop/)).toBeInTheDocument();
  });

  it("when the runner is unavailable it says so honestly and does not pretend to run", async () => {
    mockFetch({ "/academy/code/status": { body: status(false) } });
    render(<CodeLab example={example} lessonId="demo" index={0} />);
    expect(await screen.findByText(/The code runner is off on this server/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Run code/ })).toBeDisabled();
    expect(screen.getByText(/run it on your own machine/)).toBeInTheDocument();
  });

  it("non-runnable examples show their setup and no Run button", async () => {
    mockFetch({ "/academy/code/status": { body: status() } });
    render(<CodeLab example={{ ...example, runnable: false, setup: "pip install openai and set OPENAI_API_KEY", expected_output: undefined }} lessonId="demo" index={1} />);
    expect(await screen.findByText(/pip install openai/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Run code/ })).not.toBeInTheDocument();
    expect(screen.getByText(/no expected output is shown/)).toBeInTheDocument();
  });

  it("shows the line-by-line explanation on demand", async () => {
    mockFetch({ "/academy/code/status": { body: status() } });
    render(<CodeLab example={example} lessonId="demo" index={0} />);
    await userEvent.click(screen.getByRole("button", { name: /Line-by-line explanation/ }));
    expect(screen.getByText(/prints the answer/)).toBeInTheDocument();
    expect(screen.getByText("lines 1")).toBeInTheDocument();
  });
});

describe("TaskLab", () => {
  it("grades by running, keeps the solution locked until an attempt, then shows it", async () => {
    let attempts = 0;
    const { calls } = mockFetch({
      "/academy/code/status": { body: status() },
      "POST /academy/code/run": () => { attempts++; return { body: run({ passed: false, stdout: "41\n" }) }; },
      "/solution/exercise": () => (attempts ? { body: { solution: "print(42)", expected_output: "42" } } : { status: 403, body: { detail: "Try the task at least once first - then the solution is unlocked." } }),
    });
    const onResult = vi.fn();
    render(<TaskLab task={task} kind="exercise" lessonId="demo" title="Practical exercise" onResult={onResult} />);
    await userEvent.click(await screen.findByRole("button", { name: "Show solution" }));
    expect(await screen.findByText(/Try the task at least once first/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Run and check/ }));
    expect(await screen.findByText(/Not yet/)).toBeInTheDocument();
    expect(screen.getByText("41")).toBeInTheDocument();
    expect(JSON.parse(String(calls.find((c) => c.url.endsWith("/code/run"))!.init.body))).toMatchObject({ task: "exercise", lesson_id: "demo", code: "# TODO" });
    expect(onResult).toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Show solution" }));
    expect(await screen.findByLabelText("Practical exercise solution")).toHaveValue("print(42)");
  });

  it("hint toggles and a passing run is celebrated", async () => {
    mockFetch({ "/academy/code/status": { body: status() }, "POST /academy/code/run": { body: run({ passed: true }) } });
    render(<TaskLab task={task} kind="debug" lessonId="demo" title="Debugging challenge" />);
    await userEvent.click(screen.getByRole("button", { name: "Hint" }));
    expect(screen.getByText(/Use print/)).toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: /Run and check/ }));
    expect(await screen.findByText(/matches the expected output/)).toBeInTheDocument();
  });
});
