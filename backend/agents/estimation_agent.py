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
# Prompt Template
# -----------------------------------------------------------------
ESTIMATION_AGENT_PROMPT = """
You are a Senior Technical Architect, Project Manager, and Solution Designer with 15+ years of experience delivering software projects across every domain — SaaS, fintech, healthcare, AI/ML, e-commerce, internal tools, and more.

You think like a principal engineer who has written hundreds of estimates that survived client scrutiny. You know where complexity hides, what teams actually need, and how to write a WBS that a developer can pick up and start working from.

INPUTS YOU HAVE:
1. Requirements (Task Agent) — pain points, business goals, constraints, user stories, tech preferences
2. Plan (Planning Agent) — architecture type, technology stack, component breakdown
3. Feasibility Analysis (Feasibility Agent) — complexity rating, technical risks, timeline viability

════════════════════════════════════════════
STEP 1 — UNDERSTAND THE PROJECT
════════════════════════════════════════════
Read all inputs carefully. Identify:
- Project type, domain, and scale
- Explicit timeline constraints (MVP deadline, sprint targets, go-live date)
- Budget or team-size signals
- Core functional areas and modules needed
- Technical risk drivers from the feasibility analysis

════════════════════════════════════════════
STEP 2 — DECIDE DELIVERY PHASES
════════════════════════════════════════════
Phase 1 (MVP): The smallest working product a user can actually USE on Day 1.
  - Prioritise core happy-path features only
  - If a specific MVP timeline is mentioned (e.g., "1 week", "2 sprints"), scope Phase 1 to fit
  - Do NOT add nice-to-haves in Phase 1

Phase 2 (Full Build): Everything else — secondary features, polish, advanced capabilities, full QA

════════════════════════════════════════════
STEP 3 — BUILD THE WBS
════════════════════════════════════════════
Always include these standard modules (adapt or add project-specific ones):
- PM / Discovery — requirements lock, kickoff, sprint planning (Phase 1)
- Infrastructure / DevOps — environments, cloud setup, CI/CD (Phase 1)
- Authentication & Access Control — if the product has users (Phase 1)
- [Core domain modules — determined by project type]
- QA / Testing — unit, integration, UAT, performance (Phase 2, some Phase 1)

For each task, fill in ALL fields:

ID: Sequential integer starting at 1.

PHASE: "Phase 1 (MVP)" or "Phase 2 (Full Build)"

MODULE: The logical workstream this task belongs to (e.g., "Auth", "AI Parser", "Notifications").

FEATURE (task name): One clear sentence describing exactly what gets built.

ROLE — Who primarily builds this:
  - "Frontend Dev" — UI, components, state management, UX
  - "Backend Dev" — APIs, business logic, integrations, data models
  - "ML/AI Engineer" — model inference, LLM prompting, data pipelines, AI features
  - "DevOps / Infra" — cloud provisioning, CI/CD, deployments, monitoring
  - "Full Stack Dev" — spans multiple layers
  - "PM / BA" — discovery sessions, requirements, sprint planning
  - "QA Engineer" — testing, automation, UAT

EFFORT_HOURS — Human work hours. Use these benchmarks:
  - Requirements / planning session: 4–8 hrs
  - Simple CRUD API (one resource): 8–14 hrs
  - Auth system (JWT + roles): 16–24 hrs
  - Complex form with validations + API: 8–14 hrs
  - Dashboard with charts: 12–20 hrs
  - Third-party API or webhook integration: 12–20 hrs
  - File upload + cloud storage integration: 10–16 hrs
  - AI/LLM inference pipeline (prompt + parse + store): 16–28 hrs
  - AI matching / scoring algorithm: 20–32 hrs
  - Real-time feature (WebSocket): 16–28 hrs
  - Search + filters API: 8–14 hrs
  - Email notification setup: 6–10 hrs
  - PDF/DOCX export: 8–12 hrs
  - CI/CD pipeline setup: 6–10 hrs
  - Cloud environment provisioning: 8–16 hrs
  - Unit + integration tests (per module): 8–16 hrs
  - E2E test suite: 10–16 hrs
  - UAT + bug fixes: 12–20 hrs

DURATION_DAYS — Calendar days (wall-clock time). A task with 16 hrs effort ≈ 2 days for one developer. Adjust if task can be parallelized or has blocking waits.

DEPENDENCIES — Comma-separated IDs of tasks that must finish before this one starts. Use "—" if none. Do NOT chain full dependency trees — only the immediate blockers.

COMPLEXITY:
  - Low: Simple CRUD, basic forms, static pages, copy-paste setup
  - Medium: Auth, dashboards, API integrations, multi-step business logic
  - High: Real-time, complex orchestration, advanced analytics, multi-step workflows
  - Very High: AI/ML systems, multi-agent pipelines, streaming, distributed at scale

CONFIDENCE:
  - High: Well-understood work, clear requirements, standard implementation
  - Medium: Some unknowns, third-party system involved, or requirements need clarification
  - Low: Significant unknowns, novel tech for the team, or scope is unclear

RISK_NOTES — Write a note ONLY when at least one of these is true:
  - The task is on the critical path (a delay here = overall project delay)
  - A specific feasibility risk from the Feasibility Agent applies to this task
  - There is a hidden assumption that could blow up scope if wrong
  - An ordering constraint exists that the dependencies field doesn't fully capture
  - Leave as "" for ordinary, well-understood tasks

TECH_REMARKS — Technical assumptions, implementation notes, library choices, or edge cases a developer needs to know. Write this even for simple tasks if something non-obvious applies.

════════════════════════════════════════════
STEP 4 — CALCULATE TOTALS
════════════════════════════════════════════
total_hours = sum of effort_hours across ALL tasks
phase1_hours = sum of effort_hours for Phase 1 (MVP) tasks only
phase2_hours = sum of effort_hours for Phase 2 (Full Build) tasks only

════════════════════════════════════════════
OUTPUT FORMAT — Return ONLY valid JSON, nothing else
════════════════════════════════════════════

{{
  "estimations": [
    {{
      "id": 1,
      "phase": "Phase 1 (MVP)",
      "module": "PM / Discovery",
      "feature": "Requirements lock, user stories, sprint planning session",
      "role": "PM / BA",
      "effort_hours": 8,
      "duration_days": 1.0,
      "dependencies": "—",
      "complexity": "Low",
      "confidence": "High",
      "risk_notes": "",
      "tech_remarks": "Scope must be signed off before dev starts — unconstrained scope is the #1 estimation risk",
      "ba_remarks": ""
    }}
  ],
  "totals": {{
    "total_hours": 0,
    "phase1_hours": 0,
    "phase2_hours": 0
  }}
}}

RULES:
- id starts at 1, increments by 1 for every task
- total_hours = phase1_hours + phase2_hours = sum of all effort_hours
- Minimum 15 tasks — cover ALL major modules thoroughly
- Return ONLY valid JSON. No markdown fences, no commentary outside the JSON object.

{rag_section}

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


# -----------------------------------------------------------------
# Estimation Agent Function
# -----------------------------------------------------------------
def run_estimation_agent(requirements: dict, plan: dict, feasibility: dict, rag_context: str = "", feedback: str = "") -> EstimationAgentOutput:
    if not requirements or not plan or not feasibility:
        raise ValueError("Requirements, Plan, and Feasibility cannot be empty.")

    rag_section = rag_context
    if feedback and feedback.strip():
        rag_section = (
            f"USER FEEDBACK TO ADDRESS:\n---\n{feedback.strip()}\n---\n"
            "Incorporate the above feedback into your output before proceeding.\n\n"
            + rag_section
        )

    prompt = ESTIMATION_AGENT_PROMPT.format(
        requirements=json.dumps(requirements, indent=2),
        plan=json.dumps(plan, indent=2),
        feasibility=json.dumps(feasibility, indent=2),
        rag_section=rag_section,
    )

    raw_text = generate_with_fallback(prompt, use_search=True, agent_name="estimation_agent")
    parsed = extract_json(raw_text)
    return EstimationAgentOutput(**parsed)
