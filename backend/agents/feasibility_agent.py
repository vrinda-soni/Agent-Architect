import os
import json
from backend.schemas.feasibility_schema import FeasibilityAgentOutput
from backend.llm_client import generate_with_fallback
from backend.agents.json_utils import extract_json

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
# Feasibility Agent Function
# -----------------------------------------------------------------
def run_feasibility_agent(requirements: dict, plan: dict) -> FeasibilityAgentOutput:
    """
    Runs the Feasibility Agent on the provided requirements and plan.

    Args:
        requirements (dict): The approved requirements including technology_context.
        plan (dict): The generated architecture plan.

    Returns:
        FeasibilityAgentOutput: A structured Pydantic model evaluating feasibility.

    Raises:
        ValueError: If LLM returns an invalid or unparseable response.
    """
    if not requirements or not plan:
        raise ValueError("Requirements and Plan cannot be empty.")

    # Build the prompt
    prompt = FEASIBILITY_AGENT_PROMPT.format(
        requirements=json.dumps(requirements, indent=2),
        plan=json.dumps(plan, indent=2)
    )

    # Call LLM with fallback (Gemini + Google Search -> OpenRouter)
    raw_text = generate_with_fallback(prompt, use_search=True, agent_name="feasibility_agent")

    # Parse the JSON response with robust extraction
    parsed = extract_json(raw_text)

    # Validate against Pydantic schema
    return FeasibilityAgentOutput(**parsed)
