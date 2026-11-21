import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { SCENES, say, type Values } from "./scenes";
import { Workflow } from "./Workflow";

const NEW = ["ai-vs-ml", "prompt-anatomy", "messages-api", "mcp-flow", "rag-eval-metrics", "prod-request", "deploy-pipeline", "async-timeline", "cache-aside", "docker-layers", "aws-architecture", "python-data", "vector-arrows", "sql-pipeline", "injection-flow", "finetune-choice", "cost-calc", "image-patches"];
const vals = (id: string, over: Values = {}): Values => ({ ...Object.fromEntries(SCENES[id].inputs.map((i) => [i.key, i.default])), ...over });
const run = (id: string, over: Values = {}, variant = SCENES[id].variants?.[0]?.id ?? "") => SCENES[id].build(vals(id, over), variant);

describe("new academy animations", () => {
  it("every scene (and variant) builds stages with all three languages and unique ids", () => {
    for (const id of NEW) {
      const variants = SCENES[id].variants?.map((v) => v.id) ?? [""];
      for (const variant of variants) {
        const stages = run(id, {}, variant);
        expect(stages.length, `${id}/${variant}`).toBeGreaterThanOrEqual(4);
        expect(new Set(stages.map((s) => s.id)).size).toBe(stages.length);
        for (const s of stages) for (const l of ["en", "hi", "hinglish"] as const) expect(say(s.simple, l).length, `${id}/${s.id}/${l}`).toBeGreaterThan(5);
      }
    }
  });

  it("rules vs learning: the learned score reacts to the message", () => {
    expect(run("ai-vs-ml", { msg: "win a free prize" }).find((s) => s.id === "score")!.output).toContain("SPAM");
    expect(run("ai-vs-ml", { msg: "meeting at noon" }).find((s) => s.id === "score")!.output).toContain("NOT SPAM");
  });

  it("prompt anatomy flags missing parts and grows the prompt", () => {
    const s = run("prompt-anatomy", { context: "" });
    expect(s.at(-1)!.lines!.join("\n")).toContain("✗ context");
    expect(s[3].output).toContain("Answer format:");
  });

  it("messages API: without history the second request has no first message", () => {
    expect(run("messages-api", { hist: "yes" })[2].output).toContain("My name is Asha.");
    expect(run("messages-api", { hist: "no" })[2].output).not.toContain("My name is Asha.");
  });

  it("MCP: a request with no matching tool calls nothing", () => {
    const s = run("mcp-flow", { q: "Delete my files" });
    expect(s.find((x) => x.id === "pick")!.output).toBe("no tool selected");
    expect(run("mcp-flow", { q: "Read notes.txt" }).find((x) => x.id === "call")!.output).toContain("read_file");
  });

  it("RAG metrics match the lesson's numbers at K=3 and change with K", () => {
    expect(run("rag-eval-metrics", { k: 3 }).at(-1)!.output).toBe("hit rate@3 = 0.67   recall@3 = 0.67   MRR = 0.50");
    expect(run("rag-eval-metrics", { k: 1 }).at(-1)!.output).toContain("hit rate@1 = 0.33");
  });

  it("production request: retries back off exponentially; an open breaker ends in an honest fallback; uploads use the queue", () => {
    const retry = run("prod-request", { fails: 3 }, "retry");
    expect(retry.filter((x) => x.id.startsWith("r")).map((x) => x.output)).toEqual(["429 → wait ≈ 1s", "429 → wait ≈ 2s", "429 → wait ≈ 4s"]);
    expect(run("prod-request", {}, "down").at(-1)!.output).toContain("503");
    expect(run("prod-request", {}, "upload").some((x) => x.id === "queue")).toBe(true);
  });

  it("deploy: a bad release is rolled back, a good one is watched", () => {
    expect(run("deploy-pipeline", {}, "bad").at(-1)!.id).toBe("rollback");
    expect(run("deploy-pipeline", { ver: "v9" }, "good").at(-1)!.id).toBe("watch");
    expect(run("deploy-pipeline", { ver: "v9" })[0].output).toContain("v9");
  });

  it("async: concurrent total is one wait; sync total is n waits", () => {
    const s = run("async-timeline", { n: 5, ms: 400 });
    expect(s[0].output).toBe("total = 5 × 400 ms = 2000 ms");
    expect(s[1].output).toContain("≈ 400 ms");
  });

  it("cache-aside: TTL decides hit/miss and the stale read is flagged until invalidated", () => {
    const s = run("cache-aside", { ttl: 2 });
    expect(s[0].output).toContain("MISS");
    expect(s[1].output).toContain("HIT");
    expect(s.find((x) => x.output.includes("stale"))).toBeTruthy();
    expect(run("cache-aside", { ttl: 1 })[1].output).toContain("MISS");
  });

  it("docker layers: changing code rebuilds 2 layers, requirements 4, base image 6, nothing 0", () => {
    const n = (chg: string) => run("docker-layers", { chg }).at(-1)!.output;
    expect(n("app code (app.py)")).toBe("2 of 6 layers rebuilt");
    expect(n("requirements.txt")).toBe("4 of 6 layers rebuilt");
    expect(n("base image tag")).toBe("6 of 6 layers rebuilt");
    expect(n("nothing")).toBe("0 of 6 layers rebuilt");
  });

  it("python-data counts words into a dictionary", () => {
    const s = run("python-data", { text: "the cat sat on the mat" });
    expect(s.find((x) => x.id === "loop")!.output).toBe('{"the":2,"cat":1,"sat":1,"on":1,"mat":1}');
    expect(s.find((x) => x.id === "sort")!.output).toBe("the (2), cat (1), sat (1)");
  });

  it("vector-arrows: same direction is 1, perpendicular is 0, opposite is -1, a zero vector is undefined", () => {
    const cos = (o: Values) => run("vector-arrows", o).find((x) => x.id === "cos")!.output;
    expect(cos({ ax: 3, ay: 4, bx: 6, by: 8 })).toContain("cosine = 1.000");
    expect(cos({ ax: 1, ay: 0, bx: 0, by: 1 })).toContain("cosine = 0.000");
    expect(cos({ ax: 1, ay: 1, bx: -1, by: -1 })).toContain("cosine = -1.000");
    expect(cos({ ax: 0, ay: 0, bx: 1, by: 1 })).toBe("undefined");
    expect(run("vector-arrows", { ax: 3, ay: 4, bx: 4, by: 3 }).find((x) => x.id === "dot")!.output).toBe("3×4 + 4×3 = 24");
  });

  it("sql-pipeline: the WHERE threshold changes what survives and the final ordering", () => {
    expect(run("sql-pipeline", { min: 30 }).find((x) => x.id === "where")!.output).toBe("5 of 5 rows left");
    expect(run("sql-pipeline", { min: 60 }).find((x) => x.id === "where")!.output).toBe("3 of 5 rows left");
    expect(run("sql-pipeline", { min: 30 }).find((x) => x.id === "order")!.output.split(/\r?\n/)[0]).toBe("Asha  300");
    expect(run("sql-pipeline", { min: 250 }).find((x) => x.id === "order")!.output).toBe("(no rows)");
  });

  it("injection-flow: only a code-level allow-list stops the planted email", () => {
    const out = (doc: string, defence: string) => run("injection-flow", { doc, defence }).at(-1)!.output;
    expect(out("Hidden attack", "none")).toContain("DANGER");
    expect(out("Hidden attack", "data fence only")).toContain("DANGER");                      // a fence alone is not a guarantee
    expect(out("Hidden attack", "allow-list in code")).toContain("Blocked");
    expect(out("Hidden attack", "allow-list + human approval")).toContain("human");
    expect(out("Clean policy", "none")).toBe("Normal answer: 25 days.");
  });

  it("finetune-choice recommends RAG for changing facts and fine-tuning only with enough examples", () => {
    const pick = (need: string, examples: number) => run("finetune-choice", { need, examples }).at(-1)!.output;
    expect(pick("Answers from our changing documents", 5000)).toBe("RAG");
    expect(pick("A fixed tone and output format", 50)).toContain("better prompt");
    expect(pick("A fixed tone and output format", 400)).toContain("Fine-tuning");
    expect(pick("Cheaper model for one task", 100)).toContain("Collect more");
  });

  it("cost-calc matches the lesson's numbers: 0.00145 per request, 1.45 per day, 55% saved", () => {
    const s = run("cost-calc", {});
    expect(s[0].output).toBe("0.001450 per request");
    expect(s[1].output).toContain("1.45 per day");
    expect(s.at(-1)!.output).toContain("0.65 per day instead of 1.45 (55% saved)");
    expect(run("cost-calc", { cache: 100 }).at(-1)!.output).toContain("0.00 per day");
  });

  it("image-patches: patch counts follow the patch size and the edge filter finds the dark/bright border", () => {
    const n = (size: string) => run("image-patches", { size }).find((x) => x.id === "cut")!.output;
    expect(n("3")).toBe("4 patches");
    expect(n("2")).toBe("9 patches");
    expect(n("6")).toBe("1 patches");
    expect(run("image-patches", { img: "dark | bright" }).at(-1)!.output).toBe("edges found (non-zero values)");
    expect(run("image-patches", { img: "dark | bright" }).at(-1)!.lines![0]).toBe("0 0 9 0 0");
  });

  it("renders in the player with Play/Step and shows the explanation", async () => {
    render(<Workflow scene={SCENES["docker-layers"]} lang="hinglish" />);
    expect(screen.getByRole("button", { name: /Agla step|Step/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Agla step/ }));
    expect(screen.getByText(/Aasan shabdon mein/)).toBeInTheDocument();
  });
});
