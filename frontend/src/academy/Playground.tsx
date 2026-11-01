import { useState } from "react";
import { academy } from "../api";
import { useLoad } from "../ui";
import { AgentPlayground } from "./playground/AgentTab";
import { CapsBanner } from "./playground/common";
import { EmbeddingPlayground } from "./playground/EmbeddingTab";
import { LangChainPlayground } from "./playground/LangChainTab";
import { LangGraphPlayground } from "./playground/GraphTab";
import { LlmPlayground, PromptPlayground } from "./playground/LlmTab";
import { RagPlayground } from "./playground/RagTab";

const TABS = [["llm", "LLM"], ["prompt", "Prompt engineering"], ["embeddings", "Embeddings"], ["rag", "RAG"], ["langchain", "LangChain"], ["langgraph", "LangGraph"], ["agent", "Agentic AI"]] as const;
type Tab = (typeof TABS)[number][0];

/** The Interactive AI Playground: seven hands-on modules that call the real backend (and say so when a component is not configured). */
export function Playground({ workspace, initial = "llm" }: { workspace: string; initial?: Tab }) {
  const [tab, setTab] = useState<Tab>(initial);
  const caps = useLoad(() => academy.pgCaps(), []);
  const props = { ws: workspace, caps: caps.data };
  return (
    <div className="ac-block">
      <h1>Interactive AI Playground</h1>
      <CapsBanner caps={caps.data} />
      {caps.error && <div className="error" role="alert">{caps.error}</div>}
      <div className="seg ac-pgtabs" role="tablist" aria-label="Playground modules">{TABS.map(([id, label]) => <button key={id} role="tab" aria-selected={tab === id} className={tab === id ? "on" : ""} onClick={() => setTab(id)}>{label}</button>)}</div>
      {tab === "llm" && <LlmPlayground {...props} />}
      {tab === "prompt" && <PromptPlayground {...props} />}
      {tab === "embeddings" && <EmbeddingPlayground {...props} />}
      {tab === "rag" && <RagPlayground {...props} />}
      {tab === "langchain" && <LangChainPlayground {...props} />}
      {tab === "langgraph" && <LangGraphPlayground ws={workspace} />}
      {tab === "agent" && <AgentPlayground {...props} />}
    </div>
  );
}
