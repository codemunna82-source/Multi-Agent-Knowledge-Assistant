# Learning guide — RAG, LangGraph and LangChain on your own documents

Open **Learn lab** in the UI (`/learn/*` in the API). Everything it shows is real code of this project running on the documents of your workspace; click **Load demo documents** first if you have none (safe to repeat).
Without a language model the model-dependent steps (multi-query, HyDE, LLM re-ranking, Self-RAG) run deterministic fallbacks and the lab labels them — add `OPENAI_API_KEY` to see their full effect.

## Tabs

| Tab | What it teaches | API |
|---|---|---|
| **Lessons** | ~30 concept cards (RAG, LangGraph, LangChain): what it is, why it matters, which file implements it, a "Try it" button | `GET /learn/lessons` |
| **Retrieval lab** | *Add techniques one by one* (cumulative ablation) or *compare settings side by side*: grade, passages, top passage, characters sent to the model, time, and **what changed** versus the previous/baseline row; expand a row for passages, scores and pipeline steps | `POST /learn/retrieval/ablation`, `/compare` |
| **Agent graph** | The compiled LangGraph drawn from the real object (dashed = conditional edges), Mermaid source, node descriptions; **run a question** and see each superstep: node, time, state keys written, summary, checkpoints | `GET /learn/graph`, `POST /learn/graph/run` |
| **LangChain lab** | real `langchain_core` objects: a retriever wrapping this pipeline, an LCEL chain (prompt \| model \| parser) with a callback recorder, a tool schema with validated calls, a Pydantic output parser, a message window | `POST /learn/langchain` |

## Exercises (use the demo documents)

1. **Compression.** Retrieval lab → *Add techniques one by one*, question *How many weeks of parental leave do partners get?* — rows 1–7 send the same 861 characters to the model; row 8 (*+ contextual compression*) sends 658 for the same passage (measured on the demo corpus). Same evidence, less noise.
2. **Keyword vs meaning.** Question *Anjali Rao* — every setting finds `hr_policy.pdf` (a name is a keyword). Now try *How much vacation time do staff get yearly?* — with the offline hash embedder **every** setting abstains (grade `incorrect`): the words differ from the text ("annual leave"). That is the lesson: configure a real embedder and re-run; semantic search should now succeed where BM25 cannot *(not verified here – needs a provider key)*.
3. **Grades and abstention.** In any row with grade `incorrect`, the system would answer "I could not verify" instead of guessing — corrective RAG's last resort.
4. **Auto strategy.** Agent graph tab → tick *Auto strategy* → run *"INV-2041"*-style (quoted/ID) and a conceptual question. Look at the `strategy` step: candidates, why each was proposed, grade/score, which was kept. Ties keep the earlier, simpler candidate.
5. **Parallel agents.** Run *How many times does "Anjali Rao" appear, and what is the highest sales?* — see `branch` ×2 then `merge`.
6. **Retry loop.** Verification can send the run back to the answering node (first retry widens retrieval, then strict extraction); the checkpoints list shows every saved state.
7. **LangChain mapping.** LangChain lab: compare the recorded steps (`MkaRetriever → format_docs → ChatPromptTemplate → model → StrOutputParser`) with the same stages in `app/agents/nodes.py::semantic`; see how an invalid tool call is rejected *before* the function runs.

## Where to read the code

`app/rag/pipeline.py` (`_once`), `app/rag/steps.py`, `app/rag/selfrag.py`, `app/rag/autoplan.py`, `app/agents/graph.py`, `app/agents/nodes.py`, `app/agents/state.py`, `app/learn/lc.py`, `app/learn/lab.py`. The project uses **LangGraph directly**; it does not build its chains with LangChain — the LangChain lab shows the equivalent LangChain code on the same data.

## Honest limits

The demo corpus is tiny and synthetic: techniques that matter on large collections (re-ranking depth, graph expansion, multi-query recall) often show *no difference* on it — that is itself informative, but run the labs on your own documents too. Latencies are for this machine.
