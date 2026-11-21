# AI Learning Academy

Open **AI Learning Academy** in the sidebar. It reuses the app's login, theme and API; chat, RAG and streaming are untouched.

## What is inside

| Part | Notes |
|---|---|
| Lessons | 28 lessons across the 15 categories (fundamentals → production). Each has definition, analogy, technical explanation, why it matters, example, code, interview answer, common mistakes and related topics, in **English, Hindi and Hinglish**. Switching language keeps your progress. Terms written as `{{term|label}}` open a glossary entry. |
| Simple steps | New learners see each lesson as 5 small steps (Understand → See an example → Try the code → Practice → Check yourself) with an "In one line" summary; technical depth, interview answers and common mistakes sit under "Go deeper". **Show full lesson** restores the single long page. The choice is remembered per browser and the resume point is shared by both views. |
| Roadmap | Beginner → Intermediate → Advanced → Production. Topics without a lesson yet are labelled **planned**. |
| Visualisations | Every lesson has at least one animation (19 scenes + 5 special views). Play / Pause / Step / Reset with editable inputs. They are **teaching models** (tiny deterministic models), not real LLMs – each says so. |
| Quizzes | Per-option explanations, weak-topic tracking; answers are never sent to the browser before you submit. |
| Code lessons | CodeMirror editor, Run / Reset / Copy, console, plain-language error help, expected output, line-by-line explanation. Exercises and debug challenges reveal the solution only after an attempt. |
| Playgrounds | LLM, Prompt, Embedding, RAG (upload PDF/TXT/CSV, chunk size/overlap, top-K, rerank before/after, grounded answer with citations), LangChain, LangGraph (presets + editable graph, pause/resume), Agentic (tool traces). |
| Projects | 10 guided projects (architecture, stack, folders, steps, complete code, API tests, deployment, interview explanation). Every project's tests run in CI (`tests/test_academy_projects.py`). They use an offline hash embedder and a rule-based planner; each step says where to plug in a real model. |
| Interview prep, daily practice | Question bank filtered by topic/level; five daily questions, weak topics first. |

## Honest limits

* 28 lessons are not the whole curriculum. A roadmap topic without a lesson is labelled planned (currently none). Lessons about Docker, AWS, Redis and PostgreSQL teach the concepts with stdlib simulations that run in the sandbox; the real services (Docker, AWS, Redis, PostgreSQL) were never run against here, and their code is marked as not runnable.
* Real LLM, embedding and cross-encoder paths were exercised only with scripted test doubles, never against a live provider or model download.
* The sandbox needs unprivileged user namespaces; otherwise code execution is disabled (see `OPERATIONS.md`). It has no cgroups/seccomp.
* Hindi/Hinglish cover lesson text, glossary and some visualisation labels; other UI text is English.
* Source links were not re-checked online at build time.

## Authoring a lesson

Add a module under `app/academy/content/`, register it in `content/__init__.py`, then run `python scripts/check_academy.py` (schema, quiz integrity, every runnable example executes, starter code of exercises must fail) and `pytest tests/test_academy*.py`.
