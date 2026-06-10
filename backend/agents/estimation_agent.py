import os
import json
from dotenv import load_dotenv
from backend.schemas.estimation_schema import EstimationAgentOutput
from backend.llm_client import generate_with_fallback
from backend.agents.json_utils import extract_json

# Load environment variables
load_dotenv()

# Validate at least one API key is available
if not os.getenv("GEMINI_API_KEY", "").strip() and not os.getenv("OPENROUTER_API_KEY", "").strip():
    raise ValueError("No API key found. Set GEMINI_API_KEY or OPENROUTER_API_KEY in your .env file.")

# -----------------------------------------------------------------
# Prompt Template
# -----------------------------------------------------------------
ESTIMATION_AGENT_PROMPT = """
You are a Senior Technical Architect and Estimation Specialist with deep experience in software project scoping.

Your task is to analyze the provided project requirements, architecture plan, feasibility analysis, and generate a detailed software development effort estimation.

INPUTS:

1. Task Agent Output — Pain points, requirements, constraints, business goals, technology_context
2. Planning Agent Output — Architecture type, technology stack, architecture summary
3. Feasibility Agent Output — Feasibility summary, complexity level, technical risks

OBJECTIVE:

Break the project into logical modules and features. For each feature, estimate development effort in hours using DYNAMIC technology categories derived from the actual tech stack proposed by the Planning Agent.

CRITICAL: DYNAMIC TECHNOLOGY COLUMNS

You MUST define technology categories based on the ACTUAL tech stack from the Planning Agent output. Do NOT use a fixed set of columns.

For example:
- If the plan uses React + Node.js + MongoDB + AWS → categories might be: ["Frontend (React)", "Backend (Node.js)", "Database (MongoDB)", "Cloud (AWS)", "DevOps"]
- If the plan uses Vue + Python/Django + PostgreSQL + Azure + Redis → categories might be: ["Frontend (Vue)", "Backend (Django)", "Database (PostgreSQL)", "Cache (Redis)", "Cloud (Azure)", "DevOps"]
- If the plan uses Angular + .NET + SQL Server + GCP → categories might be: ["Frontend (Angular)", "Backend (.NET)", "Database (SQL Server)", "Cloud (GCP)", "DevOps"]

The tech_categories list defines the column order. Each estimation item's tech_hours dict maps to these categories.

ESTIMATION GUIDELINES:

- Hours must be realistic for an MVP implementation.
- Assign hours ONLY to technologies actually used for each feature.
- If a feature doesn't need a particular technology, omit it from tech_hours or set to 0.
- Include a "Project Setup" row for environment setup, CI/CD, repository configuration.
- Include ALL major modules — do not skip important features.
- tech_remarks: Write technical assumptions and implementation notes.
- ba_remarks: Leave empty (will be filled during BA review).
- Do NOT provide cost estimates, budget calculations, or team-size recommendations.

COMPLEXITY RULES:
- Low: Simple CRUD, basic forms, static pages
- Medium: Authentication, dashboards, API integrations, business logic
- High: Real-time systems, complex backend orchestration, advanced analytics
- Very High: AI/ML systems, multi-agent workflows, streaming, large-scale distributed systems

OUTPUT FORMAT:

Return your response as a valid JSON object with this EXACT structure:
{{
    "tech_categories": ["Frontend", "Backend", "Database", "Cloud", "AI/ML", "DevOps"],
    "estimations": [
        {{
            "functionality_type": "...",
            "module": "...",
            "feature": "...",
            "complexity": "...",
            "interface_type": "...",
            "tech_hours": {{
                "Frontend": 0,
                "Backend": 0,
                "Database": 0,
                "Cloud": 0,
                "AI/ML": 0,
                "DevOps": 0
            }},
            "tech_remarks": "...",
            "ba_remarks": ""
        }}
    ],
    "totals": {{
        "tech_totals": {{
            "Frontend": 0,
            "Backend": 0,
            "Database": 0,
            "Cloud": 0,
            "AI/ML": 0,
            "DevOps": 0
        }},
        "grand_total_hours": 0
    }}
}}

IMPORTANT:
- tech_categories MUST match the keys used in tech_hours and tech_totals.
- grand_total_hours = sum of ALL values in tech_totals.
- Ensure totals are calculated correctly (sum of each column across all rows).
- Return ONLY valid JSON. No markdown. No explanations outside the JSON.

{rag_section}

Here are the requirements (including technology context):
---
{requirements}
---

Here is the proposed plan:
---
{plan}
---

Here is the feasibility analysis:
---
{feasibility}
---

Respond with ONLY the JSON object, nothing else.
"""


# -----------------------------------------------------------------
# Estimation Agent Function
# -----------------------------------------------------------------
def run_estimation_agent(requirements: dict, plan: dict, feasibility: dict, rag_context: str = "") -> EstimationAgentOutput:
    """
    Runs the Estimation Agent on the provided requirements, plan, and feasibility.

    Args:
        requirements (dict): The approved requirements including technology_context.
        plan (dict): The generated architecture plan.
        feasibility (dict): The feasibility analysis.
        rag_context (str): Optional RAG context.

    Returns:
        EstimationAgentOutput: Structured effort estimations with dynamic tech columns.

    Raises:
        ValueError: If LLM returns an invalid or unparseable response.
    """
    if not requirements or not plan or not feasibility:
        raise ValueError("Requirements, Plan, and Feasibility cannot be empty.")

    # Build the prompt
    prompt = ESTIMATION_AGENT_PROMPT.format(
        requirements=json.dumps(requirements, indent=2),
        plan=json.dumps(plan, indent=2),
        feasibility=json.dumps(feasibility, indent=2),
        rag_section=rag_context,
    )

    # Call LLM with fallback (Gemini + Google Search -> OpenRouter)
    raw_text = generate_with_fallback(prompt, use_search=True, agent_name="estimation_agent")

    # Parse the JSON response with robust extraction
    parsed = extract_json(raw_text)

    # Validate against Pydantic schema
    return EstimationAgentOutput(**parsed)
