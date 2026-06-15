import os
import json
from dotenv import load_dotenv
from backend.schemas.estimation_schema import EstimationAgentOutput
from backend.llm_client import generate_with_fallback
from backend.agents.json_utils import extract_json

load_dotenv()

if not os.getenv("GEMINI_API_KEY", "").strip() and not os.getenv("OPENROUTER_API_KEY", "").strip():
    raise ValueError("No API key found. Set GEMINI_API_KEY or OPENROUTER_API_KEY in your .env file.")


ESTIMATION_AGENT_PROMPT = """
You are an Expert Technical Project Manager, Solution Architect, and Delivery Planner.

Read all inputs carefully: Requirements, Architecture Plan, Feasibility Analysis, and Transcript.
Understand the project deeply before generating any output.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 1 — DECIDE STRUCTURAL COLUMNS (dynamic)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Choose the structural columns that best describe THIS project's work breakdown.
Always start with "No". Always include a grouping column, module column, feature/task column, complexity, and dependencies.

Example for an AI SaaS platform:
["No", "Functionality Type", "Module", "Feature", "Task", "Sub Task", "Complexity", "Dependencies"]

Example for a mobile app:
["No", "Feature Area", "Screen", "Task", "Sub Task", "Complexity", "Dependencies"]

Example for a data pipeline:
["No", "Pipeline Stage", "Component", "Task", "Sub Task", "Complexity", "Dependencies"]

Rules:
- "No" is always first
- Always include complexity and dependencies
- Add or remove columns based on what genuinely helps describe THIS project
- Do NOT add columns that would be empty for this project

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 2 — DECIDE OWNER COLUMNS (dynamic)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Generate owner team columns based on the approved architecture and tech stack.
These represent ENGINEERING TEAMS, not programming languages.

Map the architecture to owner types:
- UI/web/mobile work → "Frontend"
- API/server/database work → "Backend"
- LLM/RAG/ML/AI/NLP work → "AI/ML"
- Cloud/infra/containers → "Cloud Infrastructure"
- CI/CD/pipelines/deployment → "DevOps"
- Security/auth/compliance → "Security"
- Testing/QA → "QA"
- Data pipelines/ETL/BI → "Data Engineering"
- Third-party API integrations → "Integration"

Only include owner types that have actual work in this project.
Order: Frontend → Backend → AI/ML → Integration → Cloud Infrastructure → DevOps → Security → QA

DO NOT use language names as columns (no "React", "Python", "HTML", "Node.js" etc.)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 3 — BUILD ROWS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

For each row:
- Fill every structural column with the appropriate value
- Fill owner_hours with hours for each owner column (0 if that team has no work for this row)
- Each row = one concrete, assignable unit of work (sub-task level)
- tech_remarks: always filled — write the tech assumption, dependency note, or risk for this row
- ba_remarks: always empty string ""

Complexity values: Low, Medium, Medium-High, High, Very High

Hour benchmarks per owner:
  Frontend: UI layout 4-10hrs, component 6-16hrs, form+validation 8-14hrs, dashboard 12-22hrs
  Backend: CRUD API 8-14hrs, auth backend 16-24hrs, complex service 14-24hrs, file upload 12-18hrs
  AI/ML: LLM pipeline 18-28hrs, RAG pipeline 24-36hrs, AI scoring 20-32hrs, multi-agent 30-40hrs
  Integration: third-party API 12-20hrs, webhook 8-14hrs, OAuth 10-16hrs
  DevOps: CI/CD 8-14hrs, cloud provisioning 10-18hrs, Docker 8-12hrs
  QA: unit tests 8-14hrs, integration tests 10-16hrs, E2E suite 14-22hrs

MINIMUM ROWS: small project (≤5 reqs) → 15 rows; medium (6-12 reqs) → 25 rows; large (13+ reqs) → 35 rows

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT — valid JSON only
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{{
  "structural_columns": ["No", "Functionality Type", "Module", "Feature", "Task", "Sub Task", "Complexity", "Dependencies"],
  "owner_columns": ["Frontend", "Backend", "AI/ML", "DevOps", "QA"],
  "estimations": [
    {{
      "No": "A.0",
      "Functionality Type": "Project Setup",
      "Module": "-",
      "Feature": "Monorepo & CI/CD initialization",
      "Task": "Environment Setup",
      "Sub Task": "Docker, GitHub Actions, cloud secrets, dev/staging/prod environments",
      "Complexity": "Medium-High",
      "Dependencies": "",
      "owner_hours": {{"Frontend": 0, "Backend": 8, "AI/ML": 0, "DevOps": 14, "QA": 0}},
      "tech_remarks": "Critical path — all modules blocked until this ships. Secrets managed via environment variables.",
      "ba_remarks": ""
    }},
    {{
      "No": "B.1",
      "Functionality Type": "Authentication",
      "Module": "User Login",
      "Feature": "Email/Password Auth",
      "Task": "Login UI",
      "Sub Task": "Login form, validation, error states, forgot password link",
      "Complexity": "Medium",
      "Dependencies": "Backend Auth API",
      "owner_hours": {{"Frontend": 12, "Backend": 0, "AI/ML": 0, "DevOps": 0, "QA": 4}},
      "tech_remarks": "Assumes Supabase Auth handles token issuance. Stateless JWT — no session store needed.",
      "ba_remarks": ""
    }}
  ],
  "totals": {{
    "total_hours": 38,
    "owner_breakdown": {{"Frontend": 12, "Backend": 8, "AI/ML": 0, "DevOps": 14, "QA": 4}}
  }}
}}

STRICT RULES:
1. structural_columns = exact list of keys used in every row (besides owner_hours, tech_remarks, ba_remarks)
2. owner_columns = exact list of keys inside every owner_hours dict
3. Every row must have ALL structural column keys
4. Every row's owner_hours must have ALL owner_columns keys (use 0 for no work)
5. tech_remarks must NEVER be empty
6. ba_remarks is ALWAYS ""
7. totals.total_hours = sum of ALL owner_hours values across ALL rows
8. totals.owner_breakdown[col] = sum of that column across all rows
9. No MVP/phase fields — do NOT add mvp_future or phase columns
10. Return ONLY valid JSON — no markdown, no text before or after

{rag_section}

TRANSCRIPT:
---
{transcript}
---

REQUIREMENTS:
---
{requirements}
---

PLAN:
---
{plan}
---

FEASIBILITY:
---
{feasibility}
---

Respond with ONLY the JSON object.
"""


def run_estimation_agent(
    requirements: dict,
    plan: dict,
    feasibility: dict,
    transcript: str = "",
    include_mvp: bool = False,  # kept for API compatibility
    rag_context: str = "",
    feedback: str = "",
) -> EstimationAgentOutput:
    if not requirements or not plan or not feasibility:
        raise ValueError("Requirements, Plan, and Feasibility cannot be empty.")

    rag_section = rag_context or ""
    if feedback and feedback.strip():
        rag_section = (
            f"USER FEEDBACK TO ADDRESS:\n---\n{feedback.strip()}\n---\n"
            "Incorporate the above feedback before proceeding.\n\n"
            + rag_section
        )

    prompt = ESTIMATION_AGENT_PROMPT.format(
        transcript=transcript or "Not provided.",
        requirements=json.dumps(requirements, indent=2),
        plan=json.dumps(plan, indent=2),
        feasibility=json.dumps(feasibility, indent=2),
        rag_section=rag_section,
    )

    raw_text = generate_with_fallback(prompt, use_search=False, agent_name="estimation_agent")
    parsed = extract_json(raw_text)
    return EstimationAgentOutput(**parsed)
