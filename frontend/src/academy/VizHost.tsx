import { useState } from "react";
import type { Lang } from "./types";
import { SCENES } from "./viz/scenes";
import { AttentionViz, ContextWindowViz, EmbeddingViz, TemperatureViz, TokenGenerationViz } from "./viz/specials";
import { Workflow } from "./viz/Workflow";

const TITLES: Record<string, string> = { "llm-pipeline": "Prompt to token", "token-generation": "Token generation", attention: "Attention", "context-window": "Context window", temperature: "Temperature", "embedding-similarity": "Embeddings", chunking: "Chunking", "rag-pipeline": "RAG pipeline", "hybrid-rerank": "Hybrid + rerank", "query-transform": "Query rewriting", "langchain-lcel": "LangChain", "langgraph-flow": "LangGraph", "agent-loop": "Agent loop" };

export function Viz({ id, lang }: { id: string; lang: Lang }) {
  if (SCENES[id]) return <Workflow scene={SCENES[id]} lang={lang} />;
  if (id === "temperature") return <TemperatureViz lang={lang} />;
  if (id === "token-generation") return <TokenGenerationViz lang={lang} />;
  if (id === "attention") return <AttentionViz lang={lang} />;
  if (id === "context-window") return <ContextWindowViz lang={lang} />;
  if (id === "embedding-similarity") return <EmbeddingViz lang={lang} />;
  return <p className="muted small">Unknown visualisation “{id}”.</p>;
}

/** The visualisations of a lesson: tabs when there are several. */
export function VizHost({ ids, lang = "en" }: { ids: string[]; lang?: Lang }) {
  const [on, setOn] = useState(ids[0]);
  if (!ids.length) return null;
  return (
    <div className="viz-host">
      {ids.length > 1 && <div className="seg" role="tablist" aria-label="Visualisations">{ids.map((i) => <button key={i} role="tab" aria-selected={on === i} className={on === i ? "on" : ""} onClick={() => setOn(i)}>{TITLES[i] ?? i}</button>)}</div>}
      <Viz key={on} id={on} lang={lang} />
    </div>
  );
}
