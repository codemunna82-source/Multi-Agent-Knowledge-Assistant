export type Lang = "en" | "hi" | "hinglish";
export type L10n = Record<Lang, string>;
export type Level = "beginner" | "intermediate" | "advanced" | "production";

export interface LessonCard { id: string; category: string; level: Level; minutes: number; title: L10n; summary: string; has_viz: boolean; has_exercise: boolean; prereq: string[]; tags: string[] }
export interface Category { id: string; title: { en: string; hi: string }; summary: string; lessons: LessonCard[] }
export interface Catalog { categories: Category[]; roadmap: Record<Level, { title: string; lesson: string | null; planned: boolean }[]>; languages: Lang[] }

export interface CodeExample { title: string; language: "python" | "javascript"; runnable: boolean; code: string; expected_output?: string; setup?: string; explain: { lines: string; text: string }[] }
export interface QuizQuestion { id: string; q: string; options: string[]; kind: "concept" | "scenario" }
export interface Task { prompt: string; starter: string; hint: string; expected_output: string }
export interface Lesson extends LessonCard {
  next: string[]; objectives: string[]; assignment: string; sources: { title: string; url: string }[];
  text: { definition: L10n; analogy: L10n; technical: L10n; why: L10n; example: L10n; interview: L10n; mistakes: Record<Lang, string[]> };
  viz: string[]; code: CodeExample[]; exercise: Task; debug?: Task; quiz: QuizQuestion[]; interview_questions: { q: string; a: string }[];
}
export interface Term { term: string; en: string; hi: string; hinglish: string }

export interface QuizResult { id: string; lesson: string; selected: number; correct: boolean; answer: number; why: string; why_not: Record<string, string>; options: string[] }
export interface QuizOut { results: QuizResult[]; score: number; total: number; percent: number | null }
export interface Progress {
  lessons: Record<string, { status: "in_progress" | "done"; step: number; bookmarked: boolean; updated_at: string }>; done: number; total: number; percent: number;
  categories: { id: string; title: string; lessons: number; done: number; percent: number }[]; quiz: Record<string, { correct: number; total: number; percent: number }>;
  exercises: Record<string, { passed: boolean; attempts: number }>; streak: number; active_days: number; weak: string[]; bookmarks: string[];
  continue: { lesson: string | null; step: number } | null; recommended: string[]; projects: Record<string, number[]>;
}
export interface RunOut { ok: boolean; stdout: string; stderr: string; exit_code: number | null; ms: number; timed_out: boolean; truncated: boolean; unavailable?: string | null; notes?: string[]; error_help?: string | null; passed?: boolean | null; expected?: string | null }
export interface CodeStatus { available: boolean; reason: string | null; languages: string[]; timeout_s: number; memory_mb: number; network: boolean; setup: string | null; preinstalled: string[]; limits: { code_bytes: number; output_bytes: number } }
export interface ProjectCard { id: string; title: string; summary: string; level: Level; hours: number; stack: string[]; steps: number; done: number }
export interface Project extends ProjectCard { architecture: { nodes: string[]; edges: [string, string][] }; folders: string; steps_detail?: unknown; done_steps: number[]; [k: string]: unknown }
export interface InterviewItem { category: string; lesson: string | null; level: string; q: string; a: string }

// ----------------------------------------------------------------------------- playgrounds
export interface PgCaps {
  llm: { available: boolean; name: string | null; setup: string | null };
  embedder: { name: string; dim: number; semantic: boolean; note: string | null };
  cross_encoder: { available: boolean; model: string; setup: string };
  code_runner: { available: boolean; reason: string | null };
  limits: Record<string, number>;
}
export interface LlmParams { system: string; prompt: string; temperature: number; max_tokens: number }
export interface Usage { llm_calls?: number; prompt_tokens?: number; completion_tokens?: number; cost_usd?: number; estimated?: boolean }
export interface LlmRun { available: boolean; text?: string; model?: string; latency_ms?: number; usage?: Usage; request: { messages: { role: string; content: string }[]; temperature: number; max_tokens: number }; setup?: string }
export type LlmEvent = { type: "token"; text: string } | { type: "done"; model: string; usage: Usage; latency_ms: number; first_token_ms: number | null; chunks: number }
  | { type: "unavailable"; setup: string; request: LlmRun["request"] } | { type: "error"; detail: string };
export interface CompareRun { available: boolean; setup?: string; model?: string; variants: { name: string; text?: string; words?: number; latency_ms?: number; usage?: Usage; similarity_to_first?: number; only_here?: string[]; missing_vs_first?: string[]; request: LlmRun["request"] }[] }
export interface EmbedRun { embedder: string; semantic: boolean; note: string | null; dim: number; latency_ms: number; texts: string[]; vectors: { first_values: number[]; norm: number }[]; similarity: number[][]; ranking_vs_first: { index: number; text: string; cosine: number }[] }
export interface RagRun {
  extract: { file: string; units: number; chars: number; preview: string; warnings: string[] };
  chunks: { count: number; size: number; overlap: number; lengths: number[]; items: { id: number; location: string; chars: number; text: string }[]; truncated_list: boolean };
  embed: { embedder: string; dim: number; ms: number; semantic: boolean; note: string | null };
  store: { vectors: number; bytes: number; persisted: boolean; note: string };
  search: { mode: string; candidates: number; top: { rank: number; chunk: number; cosine: number; bm25: number; score: number; location: string; text: string }[] };
  rerank: { method: string; before: number[]; after: number[]; moved: number[]; items: { rank: number; chunk: number; rerank_score: number | null; was_rank: number; text: string }[] };
  context: { system: string; prompt: string; chars: number };
  answer?: { method: string; text: string; citations: { n: number; location: string; chunk: number }[]; found: boolean; uncited?: boolean; usage?: Usage };
  total_ms: number;
}
export interface LcRun { available: boolean; setup?: string; pattern?: string; model?: string; chain?: string[]; inputs?: Record<string, string>; steps?: { kind: string; name: string; input: string; output: string; ms: number }[]; output?: unknown; error?: string | null; latency_ms?: number }
export interface GraphPreset { label: string; input: Record<string, unknown>; spec: GraphSpec }
export interface GraphSpec {
  state: Record<string, "str" | "int" | "list">;
  nodes: { id: string; type: string; key?: string | null; value?: string | number | null; by?: number; template?: string | null }[];
  edges: [string, string][]; conditional: { source: string; key: string; op: string; value: string | number; then: string; otherwise: string }[]; entry: string; interrupt_before?: string[];
}
export interface GraphRun {
  thread_id: string; status: "finished" | "paused" | "limit_reached" | "error"; message: string | null; pending: string[]; ms: number;
  graph: { nodes: string[]; edges: [string, string, boolean][] };
  steps: { step: number; node: string; update: Record<string, unknown>; state_after: Record<string, unknown>; ms: number }[];
  final_state: Record<string, unknown>; history: { step: number | null; next: string[]; state: Record<string, unknown> }[];
}
export interface AgentRun { policy: string; final: string; ms: number; note: string; steps: { n: number; type: string; text: string; tool?: string; input?: Record<string, unknown>; ms?: number }[] }
