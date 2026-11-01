import { useState } from "react";
import type { CodeExample } from "./types";

/** Read-only code with a copy button and a line-by-line explanation. (The runnable editor replaces this in the code-execution phase.) */
export function CodeLab({ example }: { example: CodeExample; lessonId: string; index: number }) {
  const [copied, setCopied] = useState(false);
  async function copy() { try { await navigator.clipboard.writeText(example.code); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* ignore */ } }
  return (
    <div className="ac-code">
      <div className="row"><b>{example.title}</b><span className="grow" /><button className="small" onClick={() => void copy()}>{copied ? "✓ Copied" : "Copy code"}</button></div>
      <pre><code>{example.code}</code></pre>
    </div>
  );
}
