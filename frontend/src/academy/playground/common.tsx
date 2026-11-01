import type { LlmRun, PgCaps, Usage } from "../types";

export function Unavailable({ what, setup, request }: { what: string; setup?: string | null; request?: LlmRun["request"] }) {
  return (
    <div className="ac-setup" role="status">
      <b>{what} is not configured on this server, so nothing was run.</b>
      {setup && <p className="small">{setup}</p>}
      {request && <details open><summary className="small">The request that would be sent</summary><pre className="out">{JSON.stringify(request, null, 2)}</pre></details>}
    </div>
  );
}

export function UsageLine({ model, usage, ms, first }: { model?: string; usage?: Usage; ms?: number; first?: number | null }) {
  const p = usage?.prompt_tokens ?? 0, c = usage?.completion_tokens ?? 0;
  return (
    <p className="muted small" aria-label="Run statistics">
      {model && <>model {model} · </>}{p + c > 0 ? <>{p} prompt + {c} completion tokens{usage?.estimated ? " (estimated)" : ""} · </> : null}
      {first != null && <>first token after {first} ms · </>}{ms != null && <>total {ms} ms</>}{usage?.cost_usd ? <> · ${usage.cost_usd.toFixed(5)}</> : null}
    </p>
  );
}

export function CapsBanner({ caps }: { caps: PgCaps | null }) {
  if (!caps) return null;
  return (
    <ul className="ac-caps small" aria-label="What is available on this server">
      <li className={caps.llm.available ? "ok" : "warn"}>{caps.llm.available ? `✓ Language model: ${caps.llm.name}` : "○ No language model configured (prompts, answers and agent choices need one)"}</li>
      <li className={caps.embedder.semantic ? "ok" : "warn"}>{caps.embedder.semantic ? `✓ Semantic embedder: ${caps.embedder.name}` : `○ Embedder: ${caps.embedder.name} (word overlap, not meaning)`}</li>
      <li className={caps.cross_encoder.available ? "ok" : "warn"}>{caps.cross_encoder.available ? "✓ Cross-encoder reranking available" : "○ Cross-encoder not installed (reranking falls back to lexical)"}</li>
      <li className={caps.code_runner.available ? "ok" : "warn"}>{caps.code_runner.available ? "✓ Sandboxed code runner" : "○ Code runner off"}</li>
    </ul>
  );
}

export const fmt = (n: number, d = 2) => (Math.round(n * 10 ** d) / 10 ** d).toFixed(d);
