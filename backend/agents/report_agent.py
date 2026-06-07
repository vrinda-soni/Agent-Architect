import os
import json
from dotenv import load_dotenv
from backend.schemas.report_schema import ReportAgentOutput
from backend.llm_client import generate_with_fallback

load_dotenv()

if not os.getenv("GEMINI_API_KEY", "").strip() and not os.getenv("OPENROUTER_API_KEY", "").strip():
    raise ValueError("No API key found. Set GEMINI_API_KEY or OPENROUTER_API_KEY in your .env file.")


REPORT_AGENT_PROMPT = """
You are an expert Technical Project Manager and Report Writer.

Your task is to compile a comprehensive, client-ready project report using the outputs from all previous agents:
- Task Agent (requirements, pain points, constraints, business goals)
- Planning Agent (architecture, tech stack, mermaid diagram)
- Feasibility Agent (feasibility summary, complexity, risks)
- Estimation Agent (effort estimates by module/feature)

Write the report in a professional, structured manner suitable for stakeholder presentation.

Return your response as a valid JSON object with this EXACT structure:
{{
    "executive_summary": "...",
    "requirements_summary": "...",
    "architecture_overview": "...",
    "feasibility_assessment": "...",
    "effort_estimation_summary": "...",
    "recommendations": ["...", "..."],
    "sections": [
        {{
            "title": "...",
            "content": "..."
        }}
    ],
    "raw_data": {{}}
}}

Rules:
- executive_summary: 2-3 paragraphs highlighting the project purpose, scope, and key recommendations.
- requirements_summary: Summarize pain points, requirements, constraints, and business goals.
- architecture_overview: Describe the proposed architecture, tech stack choices, and why they fit.
- feasibility_assessment: Summarize complexity, confidence levels, and top risks with mitigations.
- effort_estimation_summary: Provide a narrative summary of total hours and key module breakdowns.
- recommendations: A list of 5-8 actionable next-step recommendations.
- sections: Add any extra sections you think are valuable (e.g., Timeline, Risk Register, Team Structure).
- raw_data: Leave as empty object {{}} — the frontend will populate this.
- Do NOT include markdown outside the JSON.
- Respond with ONLY the JSON object, nothing else.

Here are the approved requirements:
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

Here is the effort estimation:
---
{estimation}
---

Respond with ONLY the JSON object, nothing else.
"""


def run_report_agent(requirements: dict, plan: dict, feasibility: dict, estimation: dict) -> ReportAgentOutput:
    """
    Runs the Report Agent to compile a comprehensive project report.

    Args:
        requirements: Approved requirements dict.
        plan: Planning agent output dict.
        feasibility: Feasibility agent output dict.
        estimation: Estimation agent output dict.

    Returns:
        ReportAgentOutput: Structured report data.
    """
    if not all([requirements, plan, feasibility, estimation]):
        raise ValueError("Requirements, Plan, Feasibility, and Estimation are all required for the Report Agent.")

    prompt = REPORT_AGENT_PROMPT.format(
        requirements=json.dumps(requirements, indent=2),
        plan=json.dumps(plan, indent=2),
        feasibility=json.dumps(feasibility, indent=2),
        estimation=json.dumps(estimation, indent=2),
    )

    raw_text = generate_with_fallback(prompt, use_search=False, agent_name="report_agent")

    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`").strip()
        if raw_text.startswith("json"):
            raw_text = raw_text[4:].strip()

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Report Agent returned invalid JSON. Raw response:\n{raw_text}\n\nError: {e}"
        )

    # Populate raw_data with all inputs for export
    parsed["raw_data"] = {
        "requirements": requirements,
        "plan": plan,
        "feasibility": feasibility,
        "estimation": estimation,
    }

    return ReportAgentOutput(**parsed)
