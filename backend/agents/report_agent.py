import os
import json
from dotenv import load_dotenv
from backend.schemas.report_schema import ReportAgentOutput
from backend.llm_client import generate_with_fallback
from backend.agents.json_utils import extract_json

load_dotenv()

if not os.getenv("GEMINI_API_KEY", "").strip() and not os.getenv("OPENROUTER_API_KEY", "").strip():
    raise ValueError("No API key found. Set GEMINI_API_KEY or OPENROUTER_API_KEY in your .env file.")


REPORT_AGENT_PROMPT = """
You are a Senior Technical Project Manager and Consulting Report Writer.

Your task is to compile a professional, client-ready consulting report using the APPROVED outputs from all previous agents. 

CRITICAL RULE — PRESERVE APPROVED OUTPUTS:
- You MUST NOT alter, contradict, or override any architectural decisions, feasibility assessments, or estimation numbers from the approved outputs.
- Your role is to CONSOLIDATE, ORGANIZE, SUMMARIZE, and PRESENT — not to re-evaluate or second-guess.
- If the approved plan says "Azure", your report must say "Azure" — not "AWS would be better".
- If the approved estimation says 120 hours, your report must reflect 120 hours — not your own estimate.
- Use the exact technology names, architecture choices, and numbers from the approved outputs.

Report Structure — Professional Consulting Style:

1. EXECUTIVE SUMMARY:
   - 2-3 paragraphs: project purpose, scope, key decisions made, and high-level recommendation.
   - Written for C-level stakeholders — no jargon, focus on business value.

2. REQUIREMENTS SUMMARY:
   - Organized presentation of pain points, requirements, constraints, business goals, and technology context.
   - Group related items logically. Preserve the original intent.

3. ARCHITECTURE OVERVIEW:
   - Describe the chosen architecture type and WHY it was selected.
   - Present the tech stack with justification for each choice.
   - Summarize the architecture workflow and data flow.

4. FEASIBILITY ASSESSMENT:
   - Present complexity level, confidence ratings, and feasibility summary.
   - List technical risks with their impact and mitigation — PRESERVE the exact risk descriptions.

5. EFFORT ESTIMATION SUMMARY:
   - Present module breakdown with technology-specific hours — PRESERVE exact numbers.
   - Highlight the grand total and key observations about effort distribution.

6. RECOMMENDATIONS:
   - 5-8 actionable next steps: team structure, timeline milestones, risk mitigation priorities.

7. ADDITIONAL SECTIONS:
   - Add 2-3 value-add sections like: "Proposed Timeline", "Risk Register", "Technology Stack Detail", "Next Steps & Milestones".
   - These should be practical and specific to this project.

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
- Do NOT include markdown outside the JSON.
- Respond with ONLY the JSON object, nothing else.
- raw_data: Leave as empty object {{}} — the system will populate this.

Here are the APPROVED requirements:
---
{requirements}
---

Here is the APPROVED plan:
---
{plan}
---

Here is the APPROVED feasibility analysis:
---
{feasibility}
---

Here is the APPROVED effort estimation:
---
{estimation}
---

Respond with ONLY the JSON object, nothing else.
"""


def run_report_agent(requirements: dict, plan: dict, feasibility: dict, estimation: dict) -> ReportAgentOutput:
    """
    Runs the Report Agent to compile a comprehensive project report.

    The report preserves all approved outputs exactly and presents them
    in a professional consulting-style format.

    Args:
        requirements: Approved requirements dict.
        plan: Approved planning agent output dict.
        feasibility: Approved feasibility agent output dict.
        estimation: Approved estimation agent output dict.

    Returns:
        ReportAgentOutput: Structured report data.
    """
    if not all([requirements, plan, feasibility, estimation]):
        raise ValueError("Requirements, Plan, Feasibility, and Estimation are all required for the Report Agent.")

    # Truncate each input to prevent timeout (max ~3000 chars each)
    def _truncate(obj, max_chars=3000):
        s = json.dumps(obj, indent=2)
        if len(s) > max_chars:
            return s[:max_chars] + "\n... [truncated for brevity]"
        return s

    prompt = REPORT_AGENT_PROMPT.format(
        requirements=_truncate(requirements),
        plan=_truncate(plan),
        feasibility=_truncate(feasibility),
        estimation=_truncate(estimation),
    )

    raw_text = generate_with_fallback(prompt, use_search=False, agent_name="report_agent")

    # Parse the JSON response with robust extraction
    parsed = extract_json(raw_text)

    # Populate raw_data with all approved inputs for export
    parsed["raw_data"] = {
        "requirements": requirements,
        "plan": plan,
        "feasibility": feasibility,
        "estimation": estimation,
    }

    return ReportAgentOutput(**parsed)
