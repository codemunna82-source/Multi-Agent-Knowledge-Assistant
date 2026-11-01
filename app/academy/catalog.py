"""Static structure of the AI Learning Academy: categories, roadmap levels and which topics have a full lesson yet."""
from __future__ import annotations

LANGS = ("en", "hi", "hinglish")
LEVELS = ("beginner", "intermediate", "advanced", "production")

# id, English title, Hindi title, one-line English summary
CATEGORIES = [
    ("fundamentals", "AI and Machine Learning Fundamentals", "AI और Machine Learning की बुनियाद", "What AI, ML and deep learning are and how they differ."),
    ("llm", "LLM Fundamentals", "LLM की बुनियाद", "How large language models read, think in tokens and write text."),
    ("prompting", "Prompt Engineering", "Prompt Engineering", "How to ask a model so that it answers well."),
    ("embeddings", "Embeddings and Vector Databases", "Embeddings और Vector Databases", "Turning meaning into numbers and searching by meaning."),
    ("langchain", "LangChain", "LangChain", "Building model pipelines from small, composable parts."),
    ("rag", "RAG", "RAG", "Answering from your own documents instead of from memory."),
    ("adv-rag", "Advanced RAG", "Advanced RAG", "Hybrid search, query rewriting and reranking for better answers."),
    ("langgraph", "LangGraph", "LangGraph", "Stateful workflows with branches, loops and human approval."),
    ("agentic", "Agentic AI", "Agentic AI", "Systems that plan, use tools, observe and reflect."),
    ("multi-agent", "Multi-Agent Systems", "Multi-Agent Systems", "Several specialised agents guided by a supervisor."),
    ("mcp", "MCP", "MCP", "A standard way to connect models to tools and data."),
    ("tools", "AI Agents with Tools", "Tools वाले AI Agents", "Letting a model call real functions safely."),
    ("evaluation", "LLM Evaluation", "LLM Evaluation", "Measuring whether answers are actually good."),
    ("prod-arch", "Production AI Architecture", "Production AI Architecture", "The parts a real AI service needs around the model."),
    ("deploy", "Deployment and Monitoring", "Deployment और Monitoring", "Shipping, observing and securing an AI service."),
]

# Roadmap: topic title -> lesson id (None = on the roadmap but no full lesson yet; the UI says so honestly).
ROADMAP = {
    "beginner": [("AI fundamentals", "ai-ml-dl"), ("Machine Learning vs Deep Learning", "ai-ml-dl"), ("LLM", "what-is-llm"), ("Tokens", "tokens-context"),
                 ("Context window", "tokens-context"), ("Sampling and temperature", "sampling-temperature"), ("Prompt engineering", "prompt-basics"), ("API usage", "prompt-roles-api")],
    "intermediate": [("Embeddings", "what-are-embeddings"), ("Vector databases", "vector-search"), ("LangChain", "lcel-basics"), ("Document loaders", "chunking-loading"),
                     ("Text splitters", "chunking-loading"), ("RAG", "rag-pipeline"), ("Retriever", "rag-pipeline"), ("Tools and function calling", "function-calling"),
                     ("Structured output", "tools-structured-output")],
    "advanced": [("Advanced RAG", "hybrid-rerank"), ("Hybrid search", "hybrid-rerank"), ("Multi-query retrieval", "query-transform"), ("HyDE", "query-transform"), ("Reranking", "hybrid-rerank"),
                 ("LangGraph", "graph-state-nodes"), ("State management", "graph-state-nodes"), ("Checkpointing", "checkpoint-hitl"), ("Agentic AI", "agent-loop"),
                 ("Planning and reflection", "reflection-planning"), ("Multi-agent architecture", "supervisor"), ("MCP", "mcp-intro")],
    "production": [("Production architecture", "prod-architecture"), ("Evaluation", "rag-eval"), ("Streaming", "deploy-monitor"), ("Monitoring", "deploy-monitor"), ("Security", "deploy-monitor"),
                   ("FastAPI and async processing", None), ("Redis and PostgreSQL", None), ("Docker", None), ("AWS", None)],
}

# Which technology progress bars the dashboard shows (category ids).
PROGRESS_GROUPS = [c[0] for c in CATEGORIES]
