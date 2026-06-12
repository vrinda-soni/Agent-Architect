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
You are a Senior Business Analyst and Solution Architect preparing a professional consulting report.

Your task is to compile a client-ready report using ONLY the APPROVED outputs from all previous agents.

CRITICAL RULES — PRESERVE APPROVED OUTPUTS:
- Do NOT alter, contradict, or override any architectural decisions, feasibility assessments, or estimation numbers.
- Use EXACT technology names, architecture choices, confidence levels, and risk descriptions from the approved outputs.
- Your role is to ORGANIZE, CONSOLIDATE, and PRESENT — not to re-evaluate or second-guess.

Return ONLY a valid JSON object with this EXACT structure (no markdown, no extra text):

{{
    "executive_summary": "2-3 paragraphs. Project purpose, scope, proposed solution, key decisions, and high-level recommendation. Written for C-level stakeholders — focus on business value, no jargon.",

    "background_summary": "1-2 paragraphs. Client current situation, business context, and existing process being improved or automated.",

    "problem_need_analysis": [
        {{"problem_need": "...", "business_impact": "..."}}
    ],

    "functional_requirements": [
        {{"id": "FR-001", "requirement": "..."}}
    ],

    "non_functional_requirements": [
        {{"category": "Performance", "requirement": "..."}},
        {{"category": "Security", "requirement": "..."}},
        {{"category": "Scalability", "requirement": "..."}}
    ],

    "constraints": ["...", "..."],

    "business_goals": ["...", "..."],

    "technology_context": ["Preferred Cloud: Azure", "Existing CRM: Salesforce"],

    "assumptions": [
        "Azure subscription is available and provisioned.",
        "Client will provide API credentials for third-party integrations.",
        "Existing infrastructure remains unchanged during the POC phase."
    ],

    "feature_module_breakdown": [
        {{"module": "...", "feature_functionality": "...", "technologies_used": "..."}}
    ],

    "feasibility_table": [
        {{"metric": "Complexity", "value": "High", "reason": "..."}},
        {{"metric": "Architecture Confidence", "value": "High", "reason": "..."}},
        {{"metric": "Feasibility Confidence", "value": "Medium", "reason": "..."}}
    ],

    "risk_assessment": [
        {{"risk": "...", "impact": "...", "mitigation_strategy": "..."}}
    ],

    "recommendations_next_steps": "Paragraph covering: immediate next steps, team structure recommendations, MVP delivery approach, timeline milestones, and future enhancement roadmap.",

    "architecture_summary": "Business-friendly paragraph explaining: why this architecture was selected, how it satisfies the requirements, and how it aligns with business goals and constraints.",

    "raw_data": {{}}
}}

Derivation instructions — follow these exactly:

- problem_need_analysis: Map each pain point from the approved requirements to its business impact. Be specific.
- functional_requirements: Take each item from the approved requirements list. Assign sequential IDs (FR-001, FR-002, ...). These are the functional requirements.
- non_functional_requirements: Identify NFRs from context: performance, scalability, security, availability, maintainability. Extract or infer from constraints and requirements.
- constraints: Copy EXACTLY from the approved requirements constraints list — do not paraphrase.
- business_goals: Copy EXACTLY from the approved requirements business_goals list — do not paraphrase.
- technology_context: Format each entry in the approved technology_context as "Key: Value" string. E.g. "Preferred Cloud: Azure".
- assumptions: Infer project-specific assumptions from the architecture, feasibility, and estimation context. Be concrete and project-relevant — avoid generic boilerplate.
- feature_module_breakdown: Derive each module from the approved tech_stack and architecture plan. Each row = one module (e.g., Frontend, Backend API, Authentication, Database, Integration Layer, CI/CD).
- feasibility_table: MUST include rows for Complexity, Architecture Confidence, and Feasibility Confidence. Use EXACT values from the approved feasibility data. Add other relevant metrics if present.
- risk_assessment: Map EXACTLY from technical_risks in the approved feasibility data. Preserve the exact risk descriptions.
- raw_data: Leave as empty object {{}} — the system will populate this automatically.

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

Respond with ONLY the JSON object. No markdown. No explanation. No trailing text.
"""


def run_report_agent(requirements: dict, plan: dict, feasibility: dict, estimation: dict) -> ReportAgentOutput:
    """
    Compiles a 12-section consulting report from all approved agent outputs.
    Preserves all architectural decisions, feasibility values, and estimation numbers exactly.
    """
    if not all([requirements, plan, feasibility, estimation]):
        raise ValueError("Requirements, Plan, Feasibility, and Estimation are all required for the Report Agent.")

    def _truncate(obj, max_chars=3000):
        s = json.dumps(obj, indent=2)
        return s[:max_chars] + "\n... [truncated for brevity]" if len(s) > max_chars else s

    prompt = REPORT_AGENT_PROMPT.format(
        requirements=_truncate(requirements),
        plan=_truncate(plan),
        feasibility=_truncate(feasibility),
        estimation=_truncate(estimation),
    )

    raw_text = generate_with_fallback(prompt, use_search=False, agent_name="report_agent")
    parsed = extract_json(raw_text)

    parsed["raw_data"] = {
        "requirements": requirements,
        "plan": plan,
        "feasibility": feasibility,
        "estimation": estimation,
    }

    return ReportAgentOutput(**parsed)
