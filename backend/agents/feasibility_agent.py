import os
import json
from dotenv import load_dotenv
from backend.schemas.feasibility_schema import FeasibilityAgentOutput
from backend.llm_client import generate_with_fallback

# Load environment variables
load_dotenv()

# Validate at least one API key is available
if not os.getenv("GEMINI_API_KEY", "").strip() and not os.getenv("OPENROUTER_API_KEY", "").strip():
    raise ValueError("No API key found. Set GEMINI_API_KEY or OPENROUTER_API_KEY in your .env file.")

# -----------------------------------------------------------------
# Prompt Template
# -----------------------------------------------------------------
FEASIBILITY_AGENT_PROMPT = """
You are an expert Technical Lead and Risk Analyst. 
You have been given the approved project requirements and the proposed technical plan/architecture.

Your job is to evaluate the feasibility of this plan against the given requirements and constraints.
Identify technical risks, complexity, necessary assumptions, and actionable recommendations.

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
  Rate how well the proposed architecture fits the stated requirements and constraints.
- feasibility_confidence must be exactly one of: 'Low', 'Medium', 'High'.
  Rate how deliverable the plan is within budget, timeline, and team constraints.
- Do NOT include markdown blocks outside the JSON.
- Respond with ONLY the JSON object, nothing else.

Here are the requirements:
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
        requirements (dict): The approved requirements.
        plan (dict): The generated architecture plan.

    Returns:
        FeasibilityAgentOutput: A structured Pydantic model evaluating feasibility.

    Raises:
        ValueError: If Gemini returns an invalid or unparseable response.
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

    # Clean up in case Gemini wraps output in markdown code blocks
    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`").strip()
        if raw_text.startswith("json"):
            raw_text = raw_text[4:].strip()

    # Parse the JSON response
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Feasibility Agent returned invalid JSON. Raw response:\n{raw_text}\n\nError: {e}"
        )

    # Validate against Pydantic schema
    return FeasibilityAgentOutput(**parsed)
