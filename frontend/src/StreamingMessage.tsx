import { Children, isValidElement, memo, useMemo, type ReactNode } from "react";
import Markdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";

/** Splits Markdown into top-level blocks at blank lines that are NOT inside a code fence. While an answer streams only the LAST block changes,
 *  so every earlier block (memoised below) is never parsed or rendered again. An unterminated fence is closed for rendering only. */
export function splitBlocks(text: string): string[] {
  const blocks: string[] = [];
  let cur: string[] = [];
  let fence: string | null = null;
  for (const line of text.split("\n")) {
    const m = /^\s*(`{3,}|~{3,})/.exec(line);
    if (m) {
      if (fence === null) fence = m[1][0];
      else if (m[1][0] === fence) fence = null;
    }
    if (fence === null && line.trim() === "" && cur.length) { blocks.push(cur.join("\n")); cur = []; continue; }
    if (line.trim() === "" && fence === null) continue;
    cur.push(line);
  }
  if (cur.length) blocks.push(cur.join("\n"));
  return blocks;
}

const openFence = (block: string): string | null => {
  let fence: string | null = null;
  for (const line of block.split("\n")) {
    const m = /^\s*(`{3,}|~{3,})/.exec(line);
    if (m) fence = fence === null ? m[1] : m[1][0] === fence[0] ? null : fence;
  }
  return fence;
};

/** Only http(s), mailto and in-page links survive; anything else (javascript:, data:) is dropped. Raw HTML is never rendered (no rehype-raw). */
const safeUrl = (u: string) => (/^(https?:|mailto:|#)/i.test(u) ? u : "");

const components = {
  a: ({ href, children }: { href?: string; children?: ReactNode }) => <a href={href} target="_blank" rel="noopener noreferrer nofollow">{children}</a>,
  table: ({ children }: { children?: ReactNode }) => <div className="md-table"><table>{children}</table></div>,
  pre: ({ children }: { children?: ReactNode }) => {
    const code = Children.toArray(children)[0];
    const lang = isValidElement(code) ? /language-(\w+)/.exec(String((code.props as { className?: string }).className ?? ""))?.[1] : undefined;
    return <div className="md-code">{lang && <div className="md-lang" aria-hidden="true">{lang}</div>}<pre>{children}</pre></div>;
  },
};

const Block = memo(function Block({ source }: { source: string }) {
  const fence = openFence(source);
  const md = fence ? source + "\n" + fence : source;        // partial code block while streaming: render it as an (open-ended) code block
  return <Markdown remarkPlugins={[remarkGfm]} rehypePlugins={[[rehypeHighlight, { detect: false, ignoreMissing: true }]]} urlTransform={safeUrl} components={components}>{md}</Markdown>;
});

/** An assistant answer: Markdown (headings, lists, tables, links, inline code, highlighted code blocks), rendered incrementally. */
export const StreamingMessage = memo(function StreamingMessage({ text, streaming = false }: { text: string; streaming?: boolean }) {
  const blocks = useMemo(() => splitBlocks(text), [text]);
  return (
    <div className={`md ${streaming ? "streaming" : ""}`}>
      {blocks.map((b, i) => <Block key={i} source={b} />)}
      {streaming && <span className="caret" aria-hidden="true" />}
    </div>
  );
});
