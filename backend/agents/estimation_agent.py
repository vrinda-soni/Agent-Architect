import os
import json
from dotenv import load_dotenv
from backend.schemas.estimation_schema import EstimationAgentOutput
from backend.llm_client import generate_with_fallback
from backend.agents.json_utils import extract_json

load_dotenv()

if not os.getenv("GEMINI_API_KEY", "").strip() and not os.getenv("OPENROUTER_API_KEY", "").strip():
    raise ValueError("No API key found. Set GEMINI_API_KEY or OPENROUTER_API_KEY in your .env file.")


# -----------------------------------------------------------------
# MVP section variants
# -----------------------------------------------------------------
_MVP_SECTION_OFF = """
SCOPE MODE: PRODUCTION (Full System)
Plan for a complete, production-ready system. Do NOT add a "phase" field to any row.
"""

_MVP_SECTION_ON = """
SCOPE MODE: MVP + FULL BUILD
Split every row into one of two phases:
  - "MVP"        — smallest working product; core happy-path features only.
  - "Full Build" — everything else: secondary features, polish, advanced capabilities, full QA.
Add a "phase" field to each row. Also calculate phase1_hours (MVP total) and phase2_hours (Full Build total) in totals.
"""

_PHASE_FIELD_ON  = '"phase": "MVP",'
_PHASE_FIELD_OFF = ""

_PHASE_TOTALS_FIELD_ON  = '"phase1_hours": 0,\n    "phase2_hours": 0,'
_PHASE_TOTALS_FIELD_OFF = ""


# -----------------------------------------------------------------
# Prompt
# -----------------------------------------------------------------
ESTIMATION_AGENT_PROMPT = """
You are a Senior Technical Project Manager, Solution Architect, and Tech Lead with 15+ years of experience.

Your job: read every input, understand the project deeply, then produce a precise effort estimation table that a real team can execute from day one — with the right columns for this specific project.

══════════════════════════════════════════════════
STEP 1 — READ ALL INPUTS
══════════════════════════════════════════════════

1. TRANSCRIPT — raw client conversation: problem, tools mentioned, timeline signals, what they don't want
2. REQUIREMENTS (Task Agent) — pain points, user stories, functional + non-functional requirements, constraints
3. PLAN (Planning Agent) — architecture, tech stack, components, integrations, data flow
4. FEASIBILITY (Feasibility Agent) — complexity ratings, technical risks, unknowns

Do not write a single row until you have read all four.

══════════════════════════════════════════════════
STEP 2 — DECIDE THE COLUMN STRUCTURE
══════════════════════════════════════════════════

This is the most important step. You define ALL columns for this estimation — nothing is fixed except
the two remarks columns at the end. Everything else is project-specific.

You will output two lists:
  structural_columns — the non-tech, non-remarks columns (in display order)
  tech_stack_columns — the technology-based hour columns (in display order)

The final table will always be:
  [structural_columns] → [tech_stack_columns as "(tech) (hrs)"] → Remarks-Tech → Remarks-BA

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
A. STRUCTURAL COLUMNS — decide based on project type
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Always start with "No" (the row ID). Then choose columns that make the most sense for this project.
Column names should match the vocabulary of the domain and project type.

Examples by project type:

  AI/SaaS platform (like a training tool, AI assistant, analytics platform):
    ["No", "Functionality Type", "Module", "Features", "Complexity (Tech Lead)", "Interface Type"]

  Mobile app:
    ["No", "Feature Area", "Screen / Module", "Description", "Complexity", "Platform"]

  E-commerce / marketplace:
    ["No", "Domain", "Module", "Features", "Complexity", "Layer"]

  Internal enterprise tool / dashboard:
    ["No", "Work Area", "Module", "Features", "Complexity", "Interface"]

  Data pipeline / ML platform:
    ["No", "Pipeline Stage", "Component", "Description", "Complexity", "Service Type"]

  API / developer platform:
    ["No", "API Domain", "Endpoint / Service", "Description", "Complexity", "Interface"]

Rules:
  - "No" is always the first structural column
  - Always include a column for the top-level grouping (equivalent to "Functionality Type")
  - Always include a column for the specific module/component
  - Always include a column for the feature/task description (this will contain sub-tasks too)
  - Always include "Complexity" (or renamed equivalent)
  - Include an "Interface Type" / "Layer" / "Platform" column if relevant
  - Add or remove columns based on what genuinely helps describe THIS project's work
  - Do NOT add columns that would be empty or meaningless for this project

B. TECH STACK COLUMNS — derived from the Plan Agent output
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Read the Plan Agent's tech stack. Map to hour columns:
  - HTML/CSS markup work → "HTML"
  - React / Next.js → "ReactJS"
  - Vue.js / Nuxt → "Vue.js"
  - Angular → "Angular"
  - Flutter → "Flutter"
  - React Native → "React Native"
  - Swift / iOS native → "Swift"
  - Kotlin / Android native → "Kotlin"
  - Python (FastAPI/Django/Flask) → "Python"
  - Node.js (Express/NestJS) → "Node.js"
  - Java / Spring → "Java"
  - Go → "Go"
  - Ruby on Rails → "Ruby"
  - Any LLM / RAG / ML / AI / Voice / NLP work → "AI"
  - Pure DevOps/infra (if no other column covers it) → "DevOps"

Order: frontend first → backend → AI/DevOps last
Only include columns that actually have work in this project.

{mvp_section}

══════════════════════════════════════════════════
STEP 3 — SCOPE CHECK
══════════════════════════════════════════════════

- Client asked for specific features only? → scope rows to exactly those.
- Client asked for a complete system? → cover all layers.
- Always include: Project Setup row, Auth module (if users exist), QA module.

══════════════════════════════════════════════════
STEP 4 — BUILD ROWS
══════════════════════════════════════════════════

Use the Functionality Type / Feature Area grouping system:
  - Each group gets a letter prefix: A, B, C, D...
  - First row of each group: A.0, B.0, C.0... (the setup/overview row for that group)
  - Subsequent rows: A.1, A.2... B.1, B.2...
  - Project Setup is always A.0

For each row, the value under the structural columns must be appropriate for that column.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FEATURE / DESCRIPTION COLUMN (the main text column)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

This column must include sub-tasks inline for all Medium+ complexity rows:

Format:
  "[Short description]. Sub-tasks: (1) [specific deliverable], (2) [specific deliverable], (3) [specific deliverable]"

BAD: "Build voice session initialization"
GOOD: "Associate launches roleplay session with microphone permissions, briefing, and objectives. Sub-tasks: (1) Browser mic permission request + fallback handling, (2) Pre-session briefing screen showing scenario + difficulty, (3) Session init API — create record, assign persona, return session token"

Every Medium / High / Very High complexity row MUST have at least 2 sub-tasks.
Low complexity rows: single atomic description is fine.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COMPLEXITY VALUES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Low          — atomic unit, single concern, standard setup
  Medium       — multi-step logic, API integration, stateful UI
  Medium-High  — multiple services interacting, complex data flows
  High         — real-time, AI orchestration, multi-layer coordination
  Very High    — multi-agent systems, streaming pipelines, distributed architecture

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TECH HOURS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Assign 0 for technologies not involved in that row. All integers ≥ 0.

Benchmarks:
  HTML/CSS layout: 4–10 hrs            UI component: 6–16 hrs
  Form + validation + API: 8–14 hrs    Dashboard + charts: 12–22 hrs
  Auth screens: 8–14 hrs               CRUD API: 8–14 hrs
  Auth backend (JWT+roles): 16–24 hrs  Complex service logic: 14–24 hrs
  Third-party API integration: 12–20   File upload + storage: 12–18 hrs
  WebSocket real-time: 16–24 hrs       DB schema + migrations: 6–12 hrs
  LLM inference pipeline: 18–28 hrs    RAG pipeline: 24–36 hrs
  Voice STT: 14–22 hrs                 TTS/voice synthesis: 10–18 hrs
  AI scoring engine: 20–32 hrs         Multi-turn conversation: 16–24 hrs
  CI/CD pipeline: 8–14 hrs             Cloud provisioning: 10–18 hrs
  Docker/containers: 8–12 hrs          Unit tests/module: 8–14 hrs
  Integration tests: 10–16 hrs         E2E test suite: 14–22 hrs
  UAT + bug fixes: 12–20 hrs

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REMARKS — TECH TEAM (tech_remarks)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Write technical notes, assumptions, dependencies, risks. Examples:
  "Depends on streaming pipeline; cannot start until that is live"
  "Assumes Whisper via API; self-hosted adds ~20 hrs"
  "Critical path — all AI features blocked until this ships"

If no special notes: write a brief technical decision summary.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REMARKS — BA TEAM (ba_remarks)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ALWAYS output exactly "". BA fills this manually. Never put anything here.

══════════════════════════════════════════════════
STEP 5 — VERIFY BEFORE OUTPUT
══════════════════════════════════════════════════

  ☐ structural_columns and tech_stack_columns match what is actually used in the rows
  ☐ Every row has ALL structural column keys (using exact same strings as in structural_columns)
  ☐ Every row's tech_hours uses EXACT same keys as tech_stack_columns
  ☐ Every Medium/High/Very High row has sub-tasks in the description column
  ☐ total_hours = exact sum of ALL tech_hours values across ALL rows
  ☐ tech_breakdown[col] = sum of that column across all rows
  ☐ ba_remarks = "" in every single row

══════════════════════════════════════════════════
OUTPUT FORMAT — valid JSON only, nothing else
══════════════════════════════════════════════════

IMPORTANT: Each row in "estimations" is a FLAT JSON object. The structural column names (from structural_columns) are used directly as keys at the top level of each row object — NOT nested inside a sub-object. tech_hours, tech_remarks, ba_remarks are also top-level keys.

Example (for an AI SaaS platform using React + Python + AI):

{{
  "structural_columns": ["No", "Functionality Type", "Module", "Features", "Complexity (Tech Lead)", "Interface Type"],
  "tech_stack_columns": ["HTML", "ReactJS", "Python", "AI"],
  "estimations": [
    {{
      "No": "A.0",
      "Functionality Type": "Project Setup",
      "Module": "-",
      "Features": "Full-stack + AI + cloud project initialization. Sub-tasks: (1) Monorepo setup with frontend/backend split, (2) Docker + docker-compose for local dev, (3) GitHub Actions CI/CD pipeline, (4) Provision dev/staging/prod on cloud with secrets management",
      "Complexity (Tech Lead)": "Medium-High",
      "Interface Type": "Web + Backend + AI + Cloud",
      "tech_hours": {{"HTML": 12, "ReactJS": 12, "Python": 16, "AI": 0}},
      "tech_remarks": "Critical path — all other modules depend on this. CI/CD and environment setup must be done first.",
      "ba_remarks": "",
      {phase_field}
    }},
    {{
      "No": "B.1",
      "Functionality Type": "Voice Roleplay Engine",
      "Module": "Real-Time Speech Capture",
      "Features": "Browser microphone streaming and Whisper STT integration. Sub-tasks: (1) WebRTC mic access + permission handling + fallback UI, (2) Audio chunk streaming to backend via WebSocket, (3) Whisper STT API call + transcript JSON parsing + turn segmentation",
      "Complexity (Tech Lead)": "High",
      "Interface Type": "Web + AI Service",
      "tech_hours": {{"HTML": 8, "ReactJS": 22, "Python": 12, "AI": 18}},
      "tech_remarks": "Real-time streaming; WebSocket architecture must be stable before building this. Whisper latency is a risk.",
      "ba_remarks": "",
      {phase_field}
    }}
  ],
  "totals": {{
    "total_hours": 100,
    {phase_totals_field}
    "tech_breakdown": {{"HTML": 20, "ReactJS": 34, "Python": 28, "AI": 18}}
  }}
}}

STRICT RULES:
- structural_columns list = exact set of keys used in every row (besides tech_hours, tech_remarks, ba_remarks, phase)
- Every row must have every key listed in structural_columns
- tech_stack_columns = exact set of keys inside every tech_hours dict
- total_hours = exact arithmetic sum of all tech_hours values across all rows (verify this)
- tech_breakdown values must sum to total_hours
- ba_remarks is ALWAYS "" — do not fill it
- Return ONLY valid JSON — no markdown fences, no text before or after

{rag_section}

TRANSCRIPT:
---
{transcript}
---

REQUIREMENTS (Task Agent):
---
{requirements}
---

PLAN (Planning Agent):
---
{plan}
---

FEASIBILITY (Feasibility Agent):
---
{feasibility}
---

Respond with ONLY the JSON object. No preamble. No explanation. No markdown.
"""


# -----------------------------------------------------------------
# Estimation Agent Function
# -----------------------------------------------------------------
def run_estimation_agent(
    requirements: dict,
    plan: dict,
    feasibility: dict,
    transcript: str = "",
    include_mvp: bool = False,
    rag_context: str = "",
    feedback: str = "",
) -> EstimationAgentOutput:
    if not requirements or not plan or not feasibility:
        raise ValueError("Requirements, Plan, and Feasibility cannot be empty.")

    mvp_section        = _MVP_SECTION_ON if include_mvp else _MVP_SECTION_OFF
    phase_field        = _PHASE_FIELD_ON if include_mvp else _PHASE_FIELD_OFF
    phase_totals_field = _PHASE_TOTALS_FIELD_ON if include_mvp else _PHASE_TOTALS_FIELD_OFF

    rag_section = rag_context or ""
    if feedback and feedback.strip():
        rag_section = (
            f"USER FEEDBACK TO ADDRESS:\n---\n{feedback.strip()}\n---\n"
            "Incorporate the above feedback into your output before proceeding.\n\n"
            + rag_section
        )

    prompt = ESTIMATION_AGENT_PROMPT.format(
        transcript=transcript or "Not provided.",
        requirements=json.dumps(requirements, indent=2),
        plan=json.dumps(plan, indent=2),
        feasibility=json.dumps(feasibility, indent=2),
        mvp_section=mvp_section,
        phase_field=phase_field,
        phase_totals_field=phase_totals_field,
        rag_section=rag_section,
    )

    raw_text = generate_with_fallback(prompt, use_search=True, agent_name="estimation_agent")
    parsed = extract_json(raw_text)
    return EstimationAgentOutput(**parsed)
