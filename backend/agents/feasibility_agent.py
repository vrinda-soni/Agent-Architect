import os
import json
from backend.schemas.feasibility_schema import FeasibilityAgentOutput
from backend.llm_client import generate_with_fallback
from backend.agents.json_utils import extract_json
from backend.langfuse_client import create_span

# Validate at least one API key is available
if not os.getenv("GEMINI_API_KEY", "").strip() and not os.getenv("OPENROUTER_API_KEY", "").strip():
    raise ValueError("No API key found. Set GEMINI_API_KEY or OPENROUTER_API_KEY in your .env file.")

# -----------------------------------------------------------------
# Prompt Template
# -----------------------------------------------------------------
FEASIBILITY_AGENT_PROMPT = """
You are an expert Technical Lead and Risk Analyst with deep experience evaluating software project proposals.
You have been given the approved project requirements (including technology context), and the proposed technical plan/architecture.

Your job is to rigorously evaluate the feasibility of this plan against the stated requirements, constraints, and technology context.

CRITICAL EVALUATION CRITERIA:

1. TECHNOLOGY FIT:
   - Does the proposed architecture align with the client's existing infrastructure and technology_context?
   - Are there mismatches between what the client has/wants and what was proposed?
   - If the client specified Azure, does the plan actually use Azure services?

2. CONSTRAINTS REALITY CHECK:
   - Can this architecture realistically be built within the stated budget, timeline, and team size?
   - Are the technology choices appropriate for the team's likely skill level?
   - Is the complexity proportional to the team capacity?

3. TECHNICAL RISK ASSESSMENT:
   - Identify real, specific technical risks — not generic ones.
   - Consider integration risks, data migration risks, scalability bottlenecks, and vendor lock-in.
   - Each risk must have a concrete, actionable mitigation.

4. ARCHITECTURE CONFIDENCE:
   - Rate how well the architecture fits ALL stated requirements including technology_context.
   - Flag any requirements that the architecture does NOT adequately address.

5. FEASIBILITY CONFIDENCE:
   - Rate the overall deliverability considering constraints, risks, and team capacity.
   - Be honest — if it looks overambitious, say so.

Return your response as a valid JSON object with this EXACT structure:
{{
    "feasibility_summary": "...",
    "complexity_level": "...",
    "architecture_confidence": "...",
    "feasibility_confidence": "...",
    "technical_risks": [
        {{
            "risk": "...",
            "impact": "...",
            "mitigation": "..."
        }}
    ]
}}

Rules:
- complexity_level must be exactly one of: 'Low', 'Medium', 'High', 'Very High'.
- architecture_confidence must be exactly one of: 'Low', 'Medium', 'High'.
  Rate how well the proposed architecture fits the stated requirements AND technology_context.
- feasibility_confidence must be exactly one of: 'Low', 'Medium', 'High'.
  Rate how deliverable the plan is within budget, timeline, and team constraints.
- technical_risks must be specific and actionable, not generic. Include at least 2-3 risks.
- feasibility_summary should be 3-5 sentences covering overall assessment.
- Do NOT include markdown blocks outside the JSON.
- Respond with ONLY the JSON object, nothing else.

{feedback_section}
Here are the requirements (including technology context):
---
{requirements}
---

Here is the proposed plan:
---
{plan}
---

Respond with ONLY the JSON object, nothing else.
"""

# -----------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------

def _coerce_risks(risks: list) -> list:
    """Normalize technical_risks entries that are plain strings into the
    {risk, impact, mitigation} dict shape that TechnicalRisk expects.
    Some fallback LLMs ignore the schema and return strings like
    'Budget overrun: description...' — this recovers them gracefully."""
    coerced = []
    for item in risks:
        if isinstance(item, dict):
            coerced.append({
                "risk":       item.get("risk", str(item)),
                "impact":     item.get("impact", "Not specified"),
                "mitigation": item.get("mitigation", "Not specified"),
            })
        elif isinstance(item, str):
            if ": " in item:
                name, rest = item.split(": ", 1)
                coerced.append({
                    "risk":       name.strip(),
                    "impact":     rest.strip(),
                    "mitigation": "Review and address during project planning.",
                })
            else:
                coerced.append({
                    "risk":       item.strip(),
                    "impact":     "See risk description.",
                    "mitigation": "Review and address during project planning.",
                })
        else:
            coerced.append({
                "risk":       str(item),
                "impact":     "Not specified",
                "mitigation": "Not specified",
            })
    return coerced


# -----------------------------------------------------------------
# Feasibility Agent Function
# -----------------------------------------------------------------
def run_feasibility_agent(requirements: dict, plan: dict, feedback: str = "", trace=None) -> FeasibilityAgentOutput:
    if not requirements or not plan:
        raise ValueError("Requirements and Plan cannot be empty.")

    feedback_section = (
        f"USER FEEDBACK TO ADDRESS:\n---\n{feedback.strip()}\n---\n"
        "Incorporate the above feedback into your output before proceeding.\n"
        if feedback and feedback.strip() else ""
    )

    prompt = FEASIBILITY_AGENT_PROMPT.format(
        requirements=json.dumps(requirements, indent=2),
        plan=json.dumps(plan, indent=2),
        feedback_section=feedback_section,
    )

    span = create_span(trace, "feasibility_agent", input={"feedback": feedback})
    # Call LLM with fallback (Gemini + Google Search -> OpenRouter)
    raw_text = generate_with_fallback(prompt, use_search=True, trace=span or trace, agent_name="feasibility_agent")

    # Parse the JSON response with robust extraction
    parsed = extract_json(raw_text)

    # Fallback LLMs sometimes return technical_risks as plain strings instead of
    # {"risk", "impact", "mitigation"} dicts. Coerce them so Pydantic doesn't raise.
    if "technical_risks" in parsed and isinstance(parsed["technical_risks"], list):
        parsed["technical_risks"] = _coerce_risks(parsed["technical_risks"])

    # Validate against Pydantic schema
    result = FeasibilityAgentOutput(**parsed)
    if span:
        span.end(output=parsed)
    return result
