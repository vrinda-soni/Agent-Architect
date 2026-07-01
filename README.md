# Agent Architect — AI-Powered POC Generator

An end-to-end agentic application that turns a project transcript (meeting notes, requirements doc, voice recording summary) into a full POC deliverable — requirements, architecture plan, feasibility analysis, work breakdown structure, and a downloadable report — all through a conversational chat interface.

---

## What It Does

1. **Upload a transcript** — paste or upload any document describing your project idea
2. **Task Agent** — extracts and structures requirements from the transcript
3. **Planning Agent** — designs the architecture (tech stack, components, data flow, diagrams)
4. **Feasibility Agent** — analyses risks, complexity, and go/no-go confidence
5. **Estimation Agent** — produces a full Work Breakdown Structure (WBS) broken down by Functionality → Module → Task → Sub-task, with stack involvement and effort hours
6. **Report Agent** — generates a professional 11-section POC report downloadable as PDF, DOCX, Markdown, or JSON
7. **Q&A** — ask questions about the project using RAG over all uploaded documents and agent outputs

At every stage you can approve the output, regenerate with feedback, or edit before moving on (Human-in-the-Loop).

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend / Chat UI | Chainlit (port 8501) |
| Agent Orchestration | Direct agent calls via `asyncio.to_thread` |
| Primary LLM | Google Gemini 2.0 Flash |
| LLM Fallback | Mistral → OpenRouter (7 free models, parallel batching) |
| Embeddings | Gemini Embedding 001 (768-dim) / BGE-M3 fallback |
| Database | Supabase (PostgreSQL + pgvector) |
| Vector Search | pgvector with HNSW index |
| Semantic Cache | Supabase `qa_cache` + pgvector similarity (threshold 0.92) |
| Report Generation | fpdf2 (PDF), python-docx (DOCX) |
| WBS Export | openpyxl (Excel) |
| Diagrams | Excalidraw JSON → PIL PNG render |
| Observability | Langfuse |
| Auth | Supabase Auth |

---

## Project Structure

```
Agent-Architect/
├── frontend/
│   └── chainlit_app.py          # Chainlit UI — all chat flows, buttons, HITL screens
├── backend/
│   ├── agents/
│   │   ├── task_agent.py        # Requirements extraction
│   │   ├── planning_agent.py    # Architecture planning + diagram generation
│   │   ├── feasibility_agent.py # Risk analysis + complexity scoring
│   │   ├── estimation_agent.py  # Two-pass WBS generation (parallel)
│   │   ├── report_agent.py      # 11-section consulting report
│   │   └── json_utils.py        # Robust JSON extraction (handles truncated LLM output)
│   ├── schemas/
│   │   ├── state_schema.py      # LangGraph AgentState TypedDict
│   │   ├── task_schema.py
│   │   ├── plan_schema.py
│   │   ├── feasibility_schema.py
│   │   ├── estimation_schema.py
│   │   └── report_schema.py
│   ├── rag/
│   │   ├── ingestion.py         # Chunk + embed documents into Supabase
│   │   ├── retrival.py          # Vector similarity search
│   │   └── cache.py             # Semantic Q&A cache
│   ├── api/
│   │   ├── main.py              # Optional FastAPI REST endpoints
│   │   └── client.py            # HTTP client for the FastAPI layer
│   ├── workflow.py              # LangGraph graph — nodes, HITL routing, checkpointer
│   ├── llm_client.py            # Gemini → Mistral → OpenRouter fallback chain
│   ├── langfuse_client.py       # Langfuse tracing helpers
│   ├── supabase.py              # Supabase client + DB helpers
│   ├── report_generator.py      # PDF / DOCX / Markdown / JSON export
│   ├── excalidraw_utils.py      # Excalidraw JSON → PIL PNG renderer
│   └── mcp_excalidraw.py        # MCP server for diagram generation
├── database/
│   ├── supabase_rag_migration.sql    # document_chunks table + pgvector + RPC
│   ├── pipeline_runs_migration.sql   # pipeline state persistence table
│   └── qa_cache_migration.sql        # semantic Q&A cache table + RPC
├── tests/
│   ├── test_feasibility.py
│   ├── test_plan.py
│   └── test_planning.py
├── scripts/
│   └── add_decorator.py
├── .chainlit/
│   └── config.toml              # Chainlit settings
├── chainlit.md                  # Chainlit welcome / login screen
├── requirements.txt
└── PROJECT_STRUCTURE.md         # Full file-by-file description of the codebase
```

> See **[PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)** for a detailed description of every file and folder.

---

## Prerequisites

- Python 3.12
- A Supabase project (free tier works)
- A Google Gemini API key (free tier works)
- An OpenRouter API key (free tier, used as LLM fallback)

---

## Setup

### 1. Clone and install dependencies

```powershell
cd "Agent-Architect"
pip install -r requirements.txt
```

### 2. Create `.env` file

```env
GEMINI_API_KEY=your_gemini_api_key
OPENROUTER_API_KEY=your_openrouter_api_key
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_supabase_anon_key

# Optional
LANGFUSE_PUBLIC_KEY=your_langfuse_public_key
LANGFUSE_SECRET_KEY=your_langfuse_secret_key
MISTRAL_API_KEY=your_mistral_api_key
HF_TOKEN=your_huggingface_token
```

### 3. Run Supabase migrations

In your Supabase dashboard → SQL Editor, run these three files **in order**:

```
1. database/supabase_rag_migration.sql      ← document storage + vector search
2. database/pipeline_runs_migration.sql     ← pipeline state persistence
3. database/qa_cache_migration.sql          ← semantic Q&A cache
```

### 4. Start the app

```powershell
chainlit run frontend/chainlit_app.py --port 8501
```

Open [http://localhost:8501](http://localhost:8501) in your browser.

---

## How to Use

1. **Sign up / Log in** using the Chainlit auth screen
2. **Create a new project** or open an existing one
3. **Upload your transcript** — meeting notes, requirements doc, any text file
4. Work through the **5-agent pipeline**:
   - Review and approve (or regenerate with feedback) each agent's output
   - Each stage shows a Human-in-the-Loop confirmation before moving on
5. **Download the WBS** as Excel from the Estimation step
6. **Download the report** as PDF / DOCX / Markdown / JSON from the Report step
7. **Ask questions** about the project in Q&A mode — answers are RAG-powered from all your documents

---

## Key Features

### Agent orchestration
Each agent is called directly from `chainlit_app.py` via `asyncio.to_thread`, which runs the synchronous agent function off the async event loop without blocking the UI. Chainlit session state (`s`) holds all pipeline data between steps, and Supabase persists it across sessions. Human-in-the-Loop (HITL) pauses are handled natively by Chainlit action callbacks — the UI shows each agent's output, waits for the user to approve or regenerate, then calls the next agent directly.

> `backend/workflow.py` contains a full LangGraph `StateGraph` implementation of the same pipeline (with `interrupt()` HITL nodes and `MemorySaver` checkpointing) and is kept as a reference. It is not the active code path — LangGraph 1.2.4's interrupt/resume mechanism was incompatible with Chainlit's `asyncio.to_thread` execution model.

### Multi-model LLM fallback
Gemini is tried first (Q&A/streaming). For heavy agents, Mistral is tried next (higher output token limits). On failure, the app falls back through 7 OpenRouter free models tried **3 at a time in parallel** — first success wins. This keeps agents fast even when Gemini is rate-limited.

### Two-pass estimation
Estimation runs in two focused LLM calls: Pass 1 identifies functionalities and modules (small, fast output); Pass 2 decomposes each functionality into tasks in parallel (one LLM call per functionality via `ThreadPoolExecutor`). This avoids single-call truncation on large projects.

### Semantic Q&A cache
Repeated or similar questions are answered instantly from a pgvector cache (similarity threshold 0.92) — no LLM call needed.

### RAG over project documents
Upload reference docs (PDF, DOCX, TXT) alongside your transcript. All documents are chunked, embedded, and stored in Supabase. The Q&A agent retrieves the most relevant chunks before answering.

### Pipeline persistence
Pipeline state is saved to Supabase after every step. Returning to a project resumes exactly where you left off.

### Robust JSON recovery
Agent outputs (especially the large WBS) are often truncated by free LLMs. A multi-stage repair strategy — including item-by-item extraction — ensures partial outputs are never silently lost.

---

## Environment Variables Reference

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | Yes | Google Gemini API key |
| `OPENROUTER_API_KEY` | Yes | OpenRouter API key (fallback LLMs) |
| `SUPABASE_URL` | Yes | Your Supabase project URL |
| `SUPABASE_KEY` | Yes | Supabase anon/service key |
| `LANGFUSE_PUBLIC_KEY` | No | Langfuse observability |
| `LANGFUSE_SECRET_KEY` | No | Langfuse observability |
| `MISTRAL_API_KEY` | No | Mistral direct API (estimation fallback) |
| `HF_TOKEN` | No | HuggingFace token (BGE-M3 embedding fallback) |
