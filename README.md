# Agent Architect — AI-Powered POC Generator

An end-to-end agentic application that turns a project transcript (meeting notes, requirements doc, voice recording summary) into a full POC deliverable — requirements, architecture plan, feasibility analysis, work breakdown structure, and a downloadable report — all through a conversational chat interface.

---

## What It Does

1. **Upload a transcript** — paste or upload any document describing your project idea
2. **Task Agent** — extracts and structures requirements from the transcript
3. **Planning Agent** — designs the architecture (tech stack, components, data flow, diagrams)
4. **Feasibility Agent** — analyses risks, complexity, effort, and go/no-go recommendation
5. **Estimation Agent** — produces a full Work Breakdown Structure (WBS) broken down by Functionality → Module → Feature → Task → Sub Task, with engineer roles and interface types
6. **Report Agent** — generates a professional POC report downloadable as PDF, DOCX, Markdown, or JSON
7. **Q&A** — ask questions about the project using RAG over all uploaded documents and agent outputs

At every stage you can approve the output, regenerate with feedback, or edit before moving on (Human-in-the-Loop).

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend / Chat UI | Chainlit (port 8501) |
| Backend API | FastAPI + Uvicorn (port 8000) |
| Primary LLM | Google Gemini 2.0 Flash |
| LLM Fallback | OpenRouter (7 free models, parallel batching) |
| Embeddings | Gemini Embedding 001 (768-dim) |
| Database | Supabase (PostgreSQL + pgvector) |
| Vector Search | pgvector with HNSW index |
| Semantic Cache | Supabase `qa_cache` table + pgvector similarity |
| Report Generation | fpdf2 (PDF), python-docx (DOCX) |
| WBS Export | openpyxl (Excel) |
| Diagrams | Excalidraw |
| Observability | Langfuse |
| Auth | Supabase Auth |

---

## Project Structure

```
Agent-Architect/
├── frontend/
│   └── chainlit_app.py          # Main Chainlit UI — all chat flows and callbacks
├── backend/
│   ├── agents/
│   │   ├── task_agent.py        # Requirements extraction
│   │   ├── planning_agent.py    # Architecture planning
│   │   ├── feasibility_agent.py # Feasibility analysis
│   │   ├── estimation_agent.py  # Work breakdown structure
│   │   ├── report_agent.py      # Report generation
│   │   └── json_utils.py        # Robust JSON extraction (handles truncated LLM output)
│   ├── schemas/
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
│   │   └── main.py              # FastAPI routes
│   ├── llm_client.py            # Gemini primary + OpenRouter fallback chain
│   ├── report_generator.py      # PDF / DOCX / Markdown / JSON export
│   ├── supabase.py              # Supabase client
│   ├── langfuse_client.py       # Langfuse tracing
│   └── hitl.py                  # Human-in-the-Loop helpers
├── .chainlit/
│   └── config.toml              # Chainlit settings
├── supabase_rag_migration.sql   # RAG tables (document_chunks)
├── pipeline_runs_migration.sql  # Pipeline persistence table
├── qa_cache_migration.sql       # Semantic cache table + match function
└── run.ps1                      # One-command startup script
```

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

Create a `.env` file in the project root:

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
1. supabase_rag_migration.sql      ← document storage + vector search
2. pipeline_runs_migration.sql     ← pipeline state persistence
3. qa_cache_migration.sql          ← semantic Q&A cache
```

### 4. Start the app

```powershell
.\run.ps1
```

This opens two terminal windows:
- **FastAPI** → http://localhost:8000
- **Chainlit UI** → http://localhost:8501

Open http://localhost:8501 in your browser.

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
7. **Ask questions** about the project in the Q&A tab — answers are RAG-powered from all your documents

---

## Key Features

### Multi-model LLM fallback
Gemini is tried first. On quota/rate-limit, the app automatically falls back through 7 OpenRouter free models, tried **3 at a time in parallel** — first success wins. This keeps agents fast even when Gemini is exhausted.

### Semantic Q&A cache
Repeated or similar questions are answered instantly from a pgvector cache (similarity threshold 0.92) — no LLM call needed.

### RAG over project documents
Upload reference docs (PDF, DOCX, TXT, or any format) alongside your transcript. All documents are chunked, embedded, and stored in Supabase. The Q&A agent retrieves the most relevant chunks before answering.

### Pipeline persistence
Pipeline state is saved to Supabase after every step. Returning to a project resumes exactly where you left off.

### Robust JSON recovery
Agent outputs (especially the large WBS) are often truncated by free LLMs. The app uses a multi-stage repair strategy — including item-by-item extraction — so partial outputs are never lost.

---

## Environment Variables Reference

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | Yes | Google Gemini API key |
| `OPENROUTER_API_KEY` | Yes | OpenRouter API key (fallback LLMs) |
| `SUPABASE_URL` | Yes | Your Supabase project URL |
| `SUPABASE_KEY` | Yes | Supabase anon/service key |
| `LANGFUSE_PUBLIC_KEY` | No | Langfuse observability (optional) |
| `LANGFUSE_SECRET_KEY` | No | Langfuse observability (optional) |
| `MISTRAL_API_KEY` | No | Mistral direct API (optional fallback for estimation) |
| `HF_TOKEN` | No | HuggingFace token (fallback embeddings) |
