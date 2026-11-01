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
export interface RunOut { ok: boolean; stdout: string; stderr: string; exit_code: number | null; ms: number; timed_out: boolean; truncated: boolean; unavailable?: string; error_help?: string; passed?: boolean | null; expected?: string }
export interface ProjectCard { id: string; title: string; summary: string; level: Level; hours: number; stack: string[]; steps: number; done: number }
export interface Project extends ProjectCard { architecture: { nodes: string[]; edges: [string, string][] }; folders: string; steps_detail?: unknown; done_steps: number[]; [k: string]: unknown }
export interface InterviewItem { category: string; lesson: string | null; level: string; q: string; a: string }
