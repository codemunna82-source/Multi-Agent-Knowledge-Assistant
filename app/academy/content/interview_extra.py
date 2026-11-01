"""Interview questions that are not tied to one lesson (system design, behavioural and scenario questions)."""
EXTRA = [
    {"category": "prod-arch", "lesson": None, "level": "advanced", "q": "Design a document Q&A system for 10,000 employees.",
     "a": "Ingest and chunk documents asynchronously, store vectors and metadata with per-document access control, retrieve with hybrid search plus a reranker, filter by the caller's permissions before the model sees anything, answer with citations, and abstain when evidence is weak. Add caching, rate limits, cost metering, tracing, and an evaluation set that gates every change."},
    {"category": "rag", "lesson": None, "level": "intermediate", "q": "How do you reduce hallucinations in a RAG application?",
     "a": "Improve retrieval first (hybrid search, reranking, good chunking), instruct the model to answer only from sources and to say when it cannot, require citations and verify them, lower temperature, and measure faithfulness on a labelled set. Refusing is a valid answer."},
    {"category": "prod-arch", "lesson": None, "level": "advanced", "q": "Your agent is slow and expensive in production. What do you check?",
     "a": "Trace one request end to end. Count model calls, tokens per call and tool latency. Cache repeated retrievals, shrink prompts, use a smaller model for routing and classification, parallelise independent tool calls, cap the loop steps, and stream so users see progress."},
    {"category": "agentic", "lesson": None, "level": "intermediate", "q": "When should you not use an agent?",
     "a": "When a fixed workflow solves the task. Agents add latency, cost and unpredictability. Use a plain chain or a graph with fixed edges for known steps, and keep a model-driven loop for tasks whose steps cannot be known in advance."},
    {"category": "agentic", "lesson": None, "level": "advanced", "q": "How do you make an agent safe to give tools to?",
     "a": "Allow-list tools, validate arguments with a schema, run with the user's permissions rather than the agent's, require human approval for irreversible actions, set step and time limits, log every call, and treat all retrieved text as untrusted input (prompt injection)."},
    {"category": "fundamentals", "lesson": None, "level": "beginner", "q": "Tell me about a project you built with LLMs and what went wrong.",
     "a": "Pick one project, state the problem and your design in two sentences, then give one concrete failure (for example wrong answers from bad chunking), how you found it (an evaluation set or traces) and what you changed. Interviewers value the debugging story more than the feature list."},
]
