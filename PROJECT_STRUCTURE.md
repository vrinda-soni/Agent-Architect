# Project Structure — Agent Architect

A complete, file-by-file reference for every part of the codebase. Written so that someone new to the project can understand what each file does, why it exists, and how it connects to everything else.

---

## How the app works (overview)

```
User uploads transcript
        ↓
Task Agent  →  extracts requirements, pain points, constraints, tech context
        ↓  [HITL #1 — user approves or regenerates with feedback]
Planning Agent  →  designs architecture, tech stack, Excalidraw diagram
        ↓
Feasibility Agent  →  assesses risks, complexity, confidence
        ↓  [HITL #2 — user approves plan+feasibility, or reruns either]
Estimation Agent (Pass 1 + Pass 2)  →  generates full WBS with effort hours
        ↓  [HITL #3 — user approves or regenerates estimation]
Report Agent  →  generates 11-section consulting report
        ↓
Downloads: PDF, DOCX, Markdown, JSON, Excel WBS
```

All Human-in-the-Loop (HITL) pauses are handled by **Chainlit action callbacks** — each button click in the UI triggers the next agent directly. Pipeline state lives in the Chainlit session and is persisted to Supabase after every step so sessions can be resumed.

---

## Folder map

```
Agent-Architect/
├── frontend/
│   └── chainlit_app.py            # Entire UI — chat flow, all buttons, HITL screens
├── backend/
│   ├── agents/
│   │   ├── task_agent.py          # Agent 1 — requirements extraction
│   │   ├── planning_agent.py      # Agent 2 — architecture design
│   │   ├── feasibility_agent.py   # Agent 3 — risk + feasibility assessment
│   │   ├── estimation_agent.py    # Agent 4 — two-pass WBS generation
│   │   ├── report_agent.py        # Agent 5 — 11-section consulting report
│   │   └── json_utils.py          # Shared JSON repair / extraction utility
│   ├── schemas/
│   │   ├── state_schema.py        # LangGraph AgentState TypedDict (reference)
│   │   ├── task_schema.py         # Pydantic output model for task_agent
│   │   ├── plan_schema.py         # Pydantic output model for planning_agent
│   │   ├── feasibility_schema.py  # Pydantic output model for feasibility_agent
│   │   ├── estimation_schema.py   # Pydantic output models for estimation_agent
│   │   └── report_schema.py       # Pydantic output model for report_agent
│   ├── rag/
│   │   ├── ingestion.py           # Chunk + embed documents → Supabase
│   │   ├── retrival.py            # Vector similarity search (query → top-k chunks)
│   │   └── cache.py               # Semantic Q&A cache (pgvector, threshold 0.92)
│   ├── api/
│   │   ├── main.py                # Optional FastAPI REST layer
│   │   └── client.py              # HTTP client for the FastAPI layer
│   ├── workflow.py                # LangGraph graph — kept as reference, not active
│   ├── llm_client.py              # Gemini → Mistral → OpenRouter fallback chain
│   ├── langfuse_client.py         # Langfuse tracing helpers (traces, spans, no-ops)
│   ├── supabase.py                # Supabase client + all DB helper functions
│   ├── report_generator.py        # PDF / DOCX / Markdown / JSON export
│   ├── excalidraw_utils.py        # Excalidraw JSON → PIL PNG renderer
│   └── mcp_excalidraw.py          # MCP server for diagram generation tool
├── database/
│   ├── supabase_rag_migration.sql     # document_chunks table + pgvector + RPC
│   ├── pipeline_runs_migration.sql    # pipeline state persistence table
│   └── qa_cache_migration.sql         # semantic Q&A cache table + RPC
├── tests/
│   ├── test_feasibility.py
│   ├── test_plan.py
│   └── test_planning.py
├── scripts/
│   └── add_decorator.py
├── .chainlit/
│   └── config.toml                # Chainlit settings (theme, auth, features)
├── chainlit.md                    # Login/welcome screen text
├── requirements.txt               # All Python dependencies
├── README.md                      # Setup guide and feature overview
└── PROJECT_STRUCTURE.md           # This file
```

---

## frontend/

### `frontend/chainlit_app.py`

The entire UI layer. This single file contains every user-facing interaction — auth, project management, the 7-step pipeline wizard, all HITL review screens, Q&A mode, file uploads, and report downloads. It is the entry point for `chainlit run frontend/chainlit_app.py --port 8501`.

#### Key responsibilities

**Authentication**
- `auth_callback` — Chainlit password auth hook. Tries `sign_in` first; if the user doesn't exist it auto-provisions their account with `sign_up`. On success stores the user record in the Chainlit session.

**Session state (`s` dict)**
- A single Python dict stored in `cl.user_session` under the key `"state"`. Holds everything: selected project, transcript, all agent outputs, approved copies, pipeline step, include_mvp toggle, Langfuse trace reference.
- `_state()` — reads and returns `s`; initializes it if not present.
- `_save(s)` — writes `s` back to the session.
- `_db_save(s)` — serializes `s` and persists it to Supabase `pipeline_runs` table so the session survives page refreshes.
- `_reset_pipeline(s)` — clears all agent outputs and approved copies when a new run starts.

**Pipeline flow (7 steps)**

| Step | What happens |
|------|-------------|
| 1 — Project select | User picks an existing project or creates a new one. Project ID is stored in `s`. |
| 2 — Transcript upload | User pastes or uploads a `.txt`/`.pdf`/`.docx` file. Transcript is saved to Supabase and optionally ingested into RAG. |
| 3 — Task Agent | `on_run_task_agent` — calls `run_task_agent(transcript, "", trace)` via `asyncio.to_thread`. Output shown as structured message. HITL #1 buttons appear. |
| 4 — HITL #1 | Approve → triggers planning + feasibility agents in sequence. Regenerate → asks for feedback, reruns task agent. |
| 5 — Planning + Feasibility | `on_hitl1_approve` — calls `run_planning_agent` then `run_feasibility_agent` sequentially. Architecture diagram rendered as PNG. HITL #2 buttons appear. |
| 6 — Estimation | `on_hitl2_approve` — calls `run_estimation_pass1` then `run_estimation_pass2`. WBS summary + Excel download shown. HITL #3 buttons appear. |
| 7 — Report | `on_hitl3_approve` → `run_report_agent` → 11-section report rendered in chat. Download buttons for PDF, DOCX, Markdown, JSON. |

**HITL callbacks (all `@cl.action_callback` + `@prevent_concurrent`)**

| Callback | What it does |
|----------|-------------|
| `on_hitl1_approve` | Stores approved requirements in `s`, builds RAG context for the project, calls planning then feasibility agents |
| `on_hitl1_regen` | Asks for feedback via `cl.AskUserMessage`, reruns task agent with that feedback |
| `on_hitl2_approve` | Stores approved plan + feasibility, runs estimation pass 1 → pass 2 |
| `on_hitl2_regen_plan` | Reruns planning agent with feedback, then reruns feasibility on the new plan |
| `on_hitl2_rerun_feas` | Reruns feasibility agent only, keeping the existing plan |
| `on_hitl3_approve` | Runs report agent with all four approved outputs |
| `on_hitl3_regen` | Asks for feedback, reruns estimation pass 1 → pass 2 with that feedback |

**Concurrency guard**
- `@prevent_concurrent` decorator — uses a per-session threading lock to block double-clicks. If a callback is already running, the second invocation immediately returns without doing anything.

**RAG integration**
- After transcript upload, text is ingested into Supabase via `_bg(_ingest_to_rag(...))` — runs in a background thread so it doesn't block the UI.
- Before planning+feasibility, `_build_rag_context(pid, requirements)` retrieves the top-k relevant chunks from the project's documents and formats them as a context block injected into the agent prompts.
- Q&A mode: user messages not matching pipeline actions are handled as questions — checked against the semantic cache first, then answered by Gemini with RAG context if not cached.

**Display helpers**
- `_show_task_result(s)` — renders requirements, pain points, constraints, business goals, technology context as formatted Chainlit messages.
- `_show_plan_result(s)` — renders tech stack table, architecture summary, Excalidraw diagram as PNG, reference docs.
- `_show_feasibility_result(s)` — renders complexity level, confidence ratings, technical risks table.
- `_show_estimation_result(s)` — renders WBS summary card (functionalities + tech disciplines), assumptions, and Excel download.
- `_show_report_result(s)` — renders all 11 report sections as individual Chainlit messages, then shows PDF/DOCX/Markdown/JSON download buttons.

**Utility functions**
- `_to_dict(obj)` — converts a Pydantic model or dict to a plain dict for passing into agent functions.
- `_build_estimation_df(estimation)` — builds a pandas DataFrame from the `EstimationAgentOutput` for Excel export.
- `_get_all_tasks(est)` — flattens all tasks across all functionalities for total count display.
- `_df_to_md(df)` — converts a DataFrame to markdown table string for report section display.
- `_start_trace(s)` / `_trace(s)` — creates and retrieves the Langfuse trace for the current pipeline run.
- `_bg(coro)` — schedules a coroutine as a background asyncio task (fire and forget).

---

## backend/agents/

One file per AI agent. Each file contains the prompt template, the LLM call, JSON parsing, Pydantic validation, and any schema-normalization helpers needed for that agent.

---

### `backend/agents/task_agent.py`

**Purpose:** Reads the raw client meeting transcript and extracts structured project intelligence.

**Output fields:**
- `pain_points` — list of problems and frustrations the client mentioned (explicit and implied)
- `requirements` — functional and non-functional requirements extracted line by line
- `constraints` — budget caps, deadlines, team limits, compliance requirements, tech lock-in
- `business_goals` — strategic objectives: revenue, automation, market expansion, etc.
- `technology_context` — key-value dict of existing infrastructure, preferred cloud, required technologies, integrations, compliance tools, DevOps tools, data platforms

**How it works:**
1. Formats the prompt with the transcript and optional regeneration feedback
2. Calls `generate_with_fallback(use_search=False)` — no web search needed, all info is in the transcript
3. Calls `extract_json()` on the raw LLM response
4. Validates against `TaskAgentOutput` Pydantic model
5. Creates a Langfuse span under the pipeline trace for observability

**Key detail:** The prompt instructs the LLM to do exhaustive line-by-line analysis and capture partial/ambiguous mentions rather than summarizing them away.

---

### `backend/agents/planning_agent.py`

**Purpose:** Reads approved requirements and designs a complete technical architecture for the project.

**Output fields:**
- `architecture_type` — e.g., "Microservices", "Monolithic", "Serverless"
- `tech_stack` — dynamic dict of categories (backend, frontend, database, etc.) → specific technology choices
- `recommendation_reason` — dict matching each tech_stack key → concrete justification tied to requirements
- `architecture_summary` — `{overview, workflow, data_flow}` describing how the system works end-to-end
- `reference_docs` — list of `{title, url}` pointing to real documentation for chosen technologies
- `excalidraw_diagram` — `{nodes[], edges[]}` representing the architecture as a layered component diagram

**How it works:**
1. Injects the requirements and any RAG context (reference docs the user uploaded) into the prompt
2. Calls `generate_with_fallback(use_search=True)` — Google Search grounding is enabled so the LLM can pull real pricing, docs, and current service names
3. Calls `_coerce_plan()` to normalize fields that fallback LLMs sometimes return in wrong types (`architecture_summary` as string → dict, `reference_docs` as strings → dicts)
4. Validates against `PlanningAgentOutput`
5. Primary LLM is Gemini 2.0 Flash; first fallback is Mistral Medium (handles the ~6,000–7,000 token output); then OpenRouter chain

**Key detail:** The prompt enforces that the tech stack must match the client's existing infrastructure and technology_context — it must not default to a generic React + FastAPI + AWS stack if the client said they're on Azure.

---

### `backend/agents/feasibility_agent.py`

**Purpose:** Evaluates the proposed architecture against the project constraints and scores its deliverability.

**Output fields:**
- `feasibility_summary` — 3–5 sentence overall assessment
- `complexity_level` — one of: `Low`, `Medium`, `High`, `Very High`
- `architecture_confidence` — how well the architecture fits the stated requirements: `Low`, `Medium`, `High`
- `feasibility_confidence` — how deliverable the plan is within budget/timeline/team: `Low`, `Medium`, `High`
- `technical_risks` — list of `{risk, impact, mitigation}` dicts — specific and actionable, not generic

**How it works:**
1. Receives both the approved requirements and the planning agent's output
2. Calls `generate_with_fallback(use_search=True)` with Gemini (web search for current tech facts)
3. Calls `_coerce_risks()` — fallback LLMs sometimes return `technical_risks` as plain strings like `"Budget overrun: description..."` instead of structured dicts. `_coerce_risks()` recovers them by splitting on `": "` and mapping to `{risk, impact, mitigation}`.
4. Validates against `FeasibilityAgentOutput`

---

### `backend/agents/estimation_agent.py`

**Purpose:** Generates a full Work Breakdown Structure (WBS) with effort hours broken down by functionality → module → task → sub-task. Uses two focused LLM calls to avoid truncation on large projects.

**Pass 1 — Skeleton mapping (`run_estimation_pass1`)**
- Input: approved requirements, plan, feasibility, RAG context, optional feedback
- Identifies which tech disciplines the project genuinely needs (Frontend, Backend, AI/ML, DevOps, Cloud, Mobile, etc.)
- Maps the project into 3–6 high-level functionalities (e.g., "User Auth", "Analytics Dashboard") each with 3–5 modules
- Output: small, fast JSON with just the skeleton — no tasks yet
- Why: Separating this into Pass 1 keeps the output small (~1,000–2,000 tokens) so it never gets truncated

**Pass 2 — Full decomposition (`run_estimation_pass2`)**
- Input: Pass 1 skeleton, `include_mvp` flag
- Runs one LLM call **per functionality** in parallel via `ThreadPoolExecutor`
- Each call decomposes that functionality into tasks and sub-tasks with: complexity, estimated hours, stack involvement (which disciplines are involved), interface type (Frontend/Backend/Integration), BA remarks, tech remarks
- Results are merged and validated against `EstimationAgentOutput`
- If `include_mvp=True`, tasks are flagged as MVP or non-MVP

**Truncation recovery (`_recover_items`)**
- Estimation produces the largest JSON output of any agent (often 5,000–10,000 tokens)
- If the LLM truncates mid-response, `_recover_items()` scans the partial text and extracts every fully-closed task object that was completed before the cutoff — never silently loses completed tasks

**Key exports:** `run_estimation_pass1`, `run_estimation_pass2`, `extract_context_from_docs`

---

### `backend/agents/report_agent.py`

**Purpose:** Reads all four prior agent outputs and generates a complete 11-section professional consulting report.

**Report sections:**
1. Executive Summary
2. Background Summary
3. Problem / Need Analysis (table)
4. Requirements (Functional + Non-Functional tables)
5. Constraints & Assumptions
6. Feature & Module Breakdown (table)
7. Proposed Architecture
8. Feasibility Assessment (table)
9. Risk Assessment (table)
10. Work Breakdown Structure Summary
11. Recommendations & Next Steps

**How it works:**
1. All four agent outputs (requirements, plan, feasibility, estimation) are serialized to JSON and injected into the prompt
2. Single LLM call — `generate_with_fallback(use_search=False)` since all information is already present
3. Output is a structured JSON matching `ReportAgentOutput` with one field per section
4. `chainlit_app.py` renders each section as a separate Chainlit message and uses `report_generator.py` to create downloadable files

---

### `backend/agents/json_utils.py`

**Purpose:** Robustly extract and repair a JSON object from raw LLM output. Shared by all five agents.

**The problem it solves:** Free LLMs on OpenRouter frequently:
- Wrap JSON in markdown code fences (` ```json ... ``` `)
- Return Python literals (`None`, `True`, `False`) instead of JSON (`null`, `true`, `false`)
- Leave trailing commas in arrays/objects
- Truncate large outputs mid-response (especially on 2048-token-cap models)
- Add explanatory text before or after the JSON object

**Repair strategy (7 stages, tried in order):**

| Stage | What it tries |
|-------|--------------|
| 1 | Strip markdown code fences |
| 2 | Find outermost `{...}` by brace-counting (skips text before/after) |
| 3 | Standard `json.loads()` — fastest path, works for clean responses |
| 4 | Replace Python literals, strip trailing commas, retry `json.loads()` |
| 5 | `_close_truncated_json()` — tracks open strings/arrays/objects and appends the right closing characters, then retries |
| 6 | `json_repair` library (optional dependency) — if installed, tries its more aggressive repair |
| 7 | Last-resort: close + repair on the full original text from `{` onward |
| 8 | Nuclear fallback: `_recover_complete_items()` — extracts every fully-closed JSON object from the `items` array in truncated text, returns whatever was completed |

**Key functions:**
- `extract_json(text)` — the main public function called by all agents
- `_close_truncated_json(text)` — appends correct closers to incomplete JSON by tracking the bracket/brace stack
- `_recover_complete_items(text)` — item-by-item extraction from truncated array output; stops at the first incomplete object rather than guessing

---

## backend/schemas/

Pydantic models that define and validate the input/output shape of each agent. Every agent function returns a validated Pydantic model instance — if the LLM returns something that doesn't match the schema, the validation error is raised before bad data reaches the UI.

---

### `backend/schemas/state_schema.py`

Defines `AgentState` — a `TypedDict` that was the shared state container for the LangGraph graph in `workflow.py`. Still used by `workflow.py` as the type annotation for all graph nodes.

**Field groups:**
- **Pipeline inputs**: `transcript`, `project_id`, `include_mvp`, `rag_context`
- **Raw agent outputs**: `requirements`, `plan`, `feasibility`, `estimation`, `report` (set by each agent node)
- **HITL-approved copies**: `approved_requirements`, `approved_plan`, `approved_feasibility`, `approved_estimation` (set by HITL nodes after user approval)
- **HITL control**: `hitl_action` (approve / regenerate / regen_plan / regen_feas), `feedback` (user's free-text guidance), `cancel_requested` (Stop button flag)

`total=False` makes every key optional — this is required by LangGraph's `MemorySaver` so partial state updates don't overwrite unrelated keys.

---

### `backend/schemas/task_schema.py`

`TaskAgentOutput`:
- `pain_points: list[str]`
- `requirements: list[str]`
- `constraints: list[str]`
- `business_goals: list[str]`
- `technology_context: dict[str, str]`

---

### `backend/schemas/plan_schema.py`

`PlanningAgentOutput`:
- `architecture_type: str`
- `tech_stack: dict[str, str]` — category → technology name
- `recommendation_reason: dict[str, str]` — category → justification
- `architecture_summary: ArchitectureSummary` — `{overview, workflow, data_flow}`
- `reference_docs: list[ReferenceDoc]` — `[{title, url}]`
- `excalidraw_diagram: ExcalidrawDiagram` — `{nodes: [{id, label, type, layer}], edges: [{from, to, label}]}`

---

### `backend/schemas/feasibility_schema.py`

`FeasibilityAgentOutput`:
- `feasibility_summary: str`
- `complexity_level: Literal["Low", "Medium", "High", "Very High"]`
- `architecture_confidence: Literal["Low", "Medium", "High"]`
- `feasibility_confidence: Literal["Low", "Medium", "High"]`
- `technical_risks: list[TechnicalRisk]` — `[{risk, impact, mitigation}]`

---

### `backend/schemas/estimation_schema.py`

Four nested models:

| Model | Fields |
|-------|--------|
| `EstimationTask` | `no`, `task`, `sub_tasks`, `features`, `interface_type`, `complexity`, `estimated_hours`, `tech_remarks`, `ba_remarks`, `stack_involvement: dict[str, bool]`, `is_mvp: bool` |
| `EstimationModule` | `module`, `tasks: list[EstimationTask]` |
| `EstimationFunctionality` | `letter`, `name`, `type`, `modules: list[EstimationModule]` |
| `EstimationAgentOutput` | `functionalities: list[EstimationFunctionality]`, `stack_columns: list[str]`, `assumptions: list[str]`, `total_hours: int` |

---

### `backend/schemas/report_schema.py`

`ReportAgentOutput` — one field per report section:
- `executive_summary: str`
- `background_summary: str`
- `problem_need_analysis: list[{problem_need, business_impact}]`
- `functional_requirements: list[{id, requirement}]`
- `non_functional_requirements: list[{category, requirement}]`
- `constraints: list[str]`
- `feature_module_breakdown: list[{module, feature_functionality, technologies_used}]`
- `proposed_architecture: str`
- `feasibility_table: list[{metric, value, reason}]`
- `risk_assessment: list[{risk, impact, mitigation_strategy}]`
- `recommendations: str`

---

## backend/rag/

The Retrieval-Augmented Generation pipeline. Allows agents and the Q&A mode to use the content from documents the user uploaded (PDFs, DOCX, TXT files) as additional context — rather than relying purely on what the LLM was trained on.

---

### `backend/rag/ingestion.py`

**Purpose:** Takes a raw document, extracts its text, splits it into chunks, embeds each chunk, and stores the chunks + vectors in Supabase.

**Process:**
1. `extract_text(file_path_or_bytes, filename)` — detects format from extension and extracts raw text:
   - `.pdf` → PyMuPDF (`fitz`)
   - `.docx` → python-docx
   - `.txt` / fallback → plain UTF-8 read
2. `ingest_document(project_id, text, document_name)`:
   - Splits text into ~800-character chunks with 150-character overlap using LangChain's `RecursiveCharacterTextSplitter`
   - Embeds each chunk via `_embed()` (Gemini Embedding 001, 768-dim; BGE-M3 fallback)
   - Upserts each chunk to Supabase `document_chunks` table with `(project_id, document_name, chunk_text, embedding)`
3. `list_project_documents(project_id)` — returns distinct document names ingested for a project

**Why chunking?** LLMs have context limits and embedding models have token limits. Chunking with overlap ensures long documents are fully indexed without any part being silently dropped.

---

### `backend/rag/retrival.py`

**Purpose:** Given a query string and a project ID, finds the most semantically similar document chunks from Supabase and returns them as formatted context.

**How it works:**
1. `retrieve_context(project_id, query, top_k=5)`:
   - Checks `_retrieval_cache` first (5-minute TTL keyed on `(project_id, query)`) — avoids redundant Supabase calls for the same question
   - Embeds the query text via `_embed()` (with in-memory `_embed_cache` to avoid re-embedding the same string)
   - Calls the Supabase `match_document_chunks` RPC with the query vector — this runs a pgvector HNSW similarity search on the server side
   - Returns the top-k chunks above the similarity threshold
2. `format_context_for_prompt(chunks)` — formats the retrieved chunks as a readable block for injection into agent prompts
3. `get_all_project_doc_text(project_id)` — fetches all document chunks for a project (used by estimation agent to extract broader context)

**Caches:**
- `_embed_cache` — in-memory dict: `text → vector`. Avoids re-calling the embedding API for the same string within a session.
- `_retrieval_cache` — in-memory dict: `(project_id, query) → (chunks, timestamp)`. 5-minute TTL. Avoids re-querying Supabase for repeated questions.

---

### `backend/rag/cache.py`

**Purpose:** Semantic Q&A cache — stores question/answer pairs in Supabase with pgvector embeddings. When a user asks a question that's semantically similar (≥ 0.92 cosine similarity) to a previously answered question, the cached answer is returned instantly without calling the LLM.

**Functions:**
- `search_cache(project_id, question)` — embeds the question, calls `match_qa_cache` Supabase RPC, returns the cached answer if similarity ≥ 0.92, else `None`
- `store_cache(project_id, question, answer)` — embeds the question and upserts `(project_id, question, answer, embedding)` to `qa_cache`

**Why 0.92?** At 0.92 cosine similarity, two questions are nearly identical in meaning (e.g., "what is the tech stack?" vs "what technologies are used?"). Lower thresholds would return stale answers for different questions.

---

## backend/llm_client.py

**Purpose:** Single, unified LLM call function used by all agents. Handles the full Gemini → Mistral → OpenRouter fallback chain automatically.

**Fallback chain:**

```
1. Gemini 2.0 Flash (google-genai SDK)
        ↓ (if rate-limited, quota exceeded, or error)
2. Mistral Medium 2505 (direct Mistral API) — for planning_agent and estimation_agent only
        ↓ (if Mistral fails or key not set)
3. OpenRouter free model chain — tried 3 at a time in parallel via ThreadPoolExecutor
   First successful response wins.
```

**Per-agent fallback lists (`_AGENT_FALLBACKS`):**
Each agent has a curated list of 7 OpenRouter models ordered by reliability for that agent's output size and reasoning needs:
- `estimation_agent` — excludes llama-3.3 (has a 2048 output token cap that truncates large WBS JSON)
- `planning_agent` — prefers models with strong reasoning (nemotron, gpt-oss-120b)
- `qa_agent` — short answers so cheap/fast models work fine
- All other agents use the default chain

**Public function:**
```python
generate_with_fallback(
    prompt: str,
    use_search: bool = False,    # enable Google Search grounding on Gemini call
    trace = None,                # Langfuse trace/span for observability
    agent_name: str = "default"  # selects the per-agent fallback list
) -> str
```

**Google Search grounding:** When `use_search=True`, the Gemini call is made with the `google_search` tool enabled. This allows the LLM to pull real-time web content (pricing, documentation URLs, current service names) into its response. Used by `planning_agent` and `feasibility_agent`.

---

## backend/langfuse_client.py

**Purpose:** Thin wrapper around Langfuse for LLM observability. Every agent call, LLM invocation, and major pipeline step is traced so the entire execution can be inspected in the Langfuse dashboard.

**How it's structured:**
- `get_langfuse()` — returns the singleton `Langfuse` client. Returns `None` if keys are not set or are placeholder values. Supports both Langfuse v2/v3 and v4+ APIs.
- `create_trace(name, session_id, metadata, user_id)` — opens a new top-level trace. Called once per pipeline run in `_start_trace(s)`. Returns a trace object or a `_NoOpTrace` stub.
- `create_span(parent, name, input, metadata)` — opens a child span under a trace or another span. Called inside each agent function.
- `flush()` — flushes buffered events to Langfuse (called at session end).

**No-op stubs (`_NoOpTrace`, `_NoOpSpan`, `_NoOpGeneration`):**
When Langfuse is not configured, all `create_trace` / `create_span` calls return these stubs. The stubs have `.end()`, `.span()`, `.generation()`, and `.update()` methods that do nothing — so agents never need to check `if trace is not None` before calling trace methods.

**What gets traced:**
- One trace per pipeline run (`"poc-pipeline"`)
- One span per agent invocation (`"task_agent"`, `"planning_agent"`, etc.)
- Each LLM call (Gemini / Mistral / OpenRouter) is recorded as a generation under the agent span with input tokens, output, model name, and latency

---

## backend/supabase.py

**Purpose:** Supabase client initialization and all database helper functions. Initializes a single `supabase: Client` on import using `SUPABASE_URL` and `SUPABASE_KEY` from `.env`.

**Auth functions:**
- `sign_up(email, password)` — creates a new Supabase Auth user
- `sign_in(email, password)` — authenticates and returns a session
- `sign_out()` — invalidates the current session

**Project management:**
- `create_project(user_id, name)` → inserts into `projects` table
- `get_projects(user_id)` → fetches all projects for a user, ordered by `created_at` descending
- `update_project(project_id, name)`, `delete_project(project_id)`

**Transcript:**
- `upload_transcript(project_id, content)` → upserts into `transcripts` table (one transcript per project)
- `get_transcript(project_id)` → returns the transcript dict

**Pipeline state persistence:**
- `save_pipeline_state(project_id, state_data)` → upserts the serialized session dict to `pipeline_runs`
- `load_pipeline_state(project_id)` → returns the last saved state for a project
- Used by `_db_save(s)` in `chainlit_app.py` after every pipeline step so sessions survive page refreshes

**Report:**
- `save_report(project_id, report_data)` → persists the final report JSON

---

## backend/report_generator.py

**Purpose:** Converts the `ReportAgentOutput` data into downloadable files in four formats.

| Function | Output | Library |
|----------|--------|---------|
| `generate_pdf(report, project_name)` | `.pdf` bytes | fpdf2 |
| `generate_docx(report, project_name)` | `.docx` bytes | python-docx |
| `generate_markdown(report, project_name)` | `.md` string | plain string formatting |
| `generate_json(report)` | `.json` bytes | `json.dumps` |

All functions take the report as a plain dict and return bytes (or string for Markdown) that `chainlit_app.py` wraps in a `cl.File` element and sends as a downloadable attachment.

**PDF formatting:** fpdf2 handles multi-page layout with section headers, paragraph text, and tables. Unicode-safe with UTF-8 encoding throughout to handle special characters in client names or technology names.

---

## backend/excalidraw_utils.py

**Purpose:** Renders the Excalidraw JSON diagram (produced by `planning_agent`) as a PNG image using PIL, which is then displayed inline in the Chainlit chat.

**How it works:**
- Reads the `{nodes, edges}` dict from the planning agent output
- Lays out nodes by their `layer` value (left-to-right, layer 0 = client side, increasing towards external services)
- Draws boxes/circles/database shapes for nodes and arrows for edges using PIL's `ImageDraw`
- Returns PNG bytes that `chainlit_app.py` sends as a `cl.Image` element

**Why PIL instead of the actual Excalidraw renderer?** Excalidraw is a browser-only React app — it can't be called server-side. The PIL renderer is a server-side approximation that produces a clean, readable architecture diagram without needing a browser.

---

## backend/mcp_excalidraw.py

**Purpose:** Exposes the Excalidraw diagram generation as an MCP (Model Context Protocol) tool. This allows the app to be used with MCP-compatible hosts (e.g., Claude Desktop) where the diagram generation can be invoked as a standalone tool call.

**When it's used:** Only when the app is started with an MCP host. In the normal Chainlit UI flow, the diagram is generated inline by the planning agent and rendered by `excalidraw_utils.py`.

---

## backend/workflow.py

A complete LangGraph `StateGraph` implementation of the full agent pipeline. **This file is kept as a reference implementation — it is not the active code path.** The frontend (`chainlit_app.py`) calls agents directly instead.

### Why it exists but isn't used

LangGraph 1.2.4 introduced breaking changes to the HITL interrupt/resume pattern. When invoked via `asyncio.to_thread` (required by Chainlit's async model), LangGraph's interrupt checkpoints do not persist across thread boundaries — the resume call always starts fresh and loses the prior state. Three approaches were attempted (`interrupt_before` + `update_state`, explicit `as_node` targeting, and the native `interrupt()` + `Command(resume=...)` pattern) and all failed. The direct-call approach was adopted instead.

### What's in the file

- **Agent nodes** — one function per agent (`task_agent_node`, `planning_agent_node`, `feasibility_agent_node`, `estimation_agent_node`, `report_agent_node`). Each node calls the agent function, captures a Langfuse trace, calls `trace.end()`, and returns the output dict to LangGraph state.
- **HITL nodes** — `hitl_1_node`, `hitl_2_node`, `hitl_3_node` use `interrupt()` (LangGraph 1.x pattern) to pause execution and yield control back to the caller with the current state payload. On resume they read the `action_data` dict (containing `hitl_action`, `feedback`, and approved outputs) and route accordingly.
- **Routing functions** — `route_hitl_1`, `route_hitl_2`, `route_hitl_3` read `hitl_action` from state and return the next node name:
  - HITL 1: `approve → planning_agent`, `regenerate → task_agent`
  - HITL 2: `approve → estimation_agent`, `regen_plan → planning_agent`, `regen_feas → feasibility_agent`
  - HITL 3: `approve → report_agent`, `regenerate → estimation_agent`
- **Graph shape** — `START → task_agent → hitl_1 → planning_agent → feasibility_agent → hitl_2 → estimation_agent → hitl_3 → report_agent → END`
- **Checkpointer** — compiled with `MemorySaver()` for in-process state persistence between interrupts. For multi-user production this would be swapped to a Supabase-backed checkpointer.
- **Langfuse tracing** — each node creates its own trace span via `create_trace(name, session_id=project_id)` so agent calls are observable in Langfuse even when run through the graph.

### Active orchestration (how it actually works today)

`chainlit_app.py` calls each agent function directly:
```
run_task_agent(transcript, feedback, trace)
run_planning_agent(requirements, rag_context, feedback, trace)
run_feasibility_agent(requirements, plan, feedback, trace)
run_estimation_pass1(...) → run_estimation_pass2(...)
run_report_agent(requirements, plan, feasibility, estimation, trace)
```
All calls go through `asyncio.to_thread` so they run off the Chainlit async event loop without blocking the UI. HITL pauses happen naturally — each Chainlit action callback (`@cl.action_callback`) simply calls the next agent when the user clicks Approve or Regenerate. Pipeline state lives in the Chainlit session dict `s` and is persisted to Supabase after each step.

---

## backend/api/

An optional FastAPI REST layer that wraps the same agent pipeline. Useful for headless or API-only access — e.g., integrating the pipeline into another system, or scripted batch processing. Not used in the normal Chainlit UI flow.

| File | What it does |
|------|-------------|
| `main.py` | FastAPI app. Exposes endpoints like `POST /run/task`, `POST /run/planning`, `POST /run/estimation`, `GET /project/{id}/state`. Each endpoint calls the same agent functions as `chainlit_app.py`. |
| `client.py` | Python HTTP client helper for calling the FastAPI endpoints programmatically — wraps `requests` with the right base URL and auth headers. |

---

## database/

SQL migration files to run in **Supabase → SQL Editor** in this exact order:

### 1. `supabase_rag_migration.sql`
Creates:
- `document_chunks` table — `(id, project_id, document_name, chunk_text, embedding vector(768), created_at)`
- HNSW index on `embedding` for fast approximate nearest-neighbour search
- `match_document_chunks(query_embedding, match_threshold, match_count, filter_project_id)` RPC — called by `retrival.py` to do server-side vector search

### 2. `pipeline_runs_migration.sql`
Creates:
- `pipeline_runs` table — `(id, project_id, state_data jsonb, updated_at)` — one row per project, upserted after every pipeline step
- Used by `supabase.py` `save_pipeline_state` / `load_pipeline_state`

### 3. `qa_cache_migration.sql`
Creates:
- `qa_cache` table — `(id, project_id, question, answer, embedding vector(768), created_at)`
- `match_qa_cache(query_embedding, match_threshold, match_count, filter_project_id)` RPC — called by `cache.py` for semantic cache lookups

---

## tests/

Manual integration tests — not an automated test suite. Run by hand during development to verify individual agents work against real LLM calls.

| File | What it tests |
|------|--------------|
| `test_feasibility.py` | Runs `run_feasibility_agent` with a hardcoded sample requirements dict + plan dict. Prints the full `FeasibilityAgentOutput` to verify schema validation passes and all fields are populated. |
| `test_plan.py` | Runs `run_planning_agent` with sample requirements. Checks that `tech_stack`, `excalidraw_diagram`, and `reference_docs` are populated. |
| `test_planning.py` | Extended planning agent test with different project types to verify the tech stack doesn't default to a generic stack when the requirements specify a particular cloud or language. |

---

## scripts/

| File | What it does |
|------|-------------|
| `add_decorator.py` | One-off development utility. Was used to programmatically add `@prevent_concurrent` decorators to all `@cl.action_callback` functions in `chainlit_app.py`. No longer needed — the decorators are already in place. |

---

## Configuration files

| File | What it does |
|------|-------------|
| `.chainlit/config.toml` | Chainlit application settings: app name, theme colours, auth type (`"header"`), enabled features (file upload, audio input, multi-modal), max file size. |
| `chainlit.md` | Markdown content shown on the Chainlit login / welcome screen. Displays the app name and a brief description of what the user will do. |
| `.env` | All secret keys. Never committed to git. See README for the full variable list. |
| `.gitignore` | Excludes `.env`, virtual environments (`.venv*`), `__pycache__`, `.pyc` files, log files, and generated report artefacts. |
| `requirements.txt` | All Python dependencies with pinned versions. Install with `pip install -r requirements.txt` into a Python 3.12 virtual environment. |
