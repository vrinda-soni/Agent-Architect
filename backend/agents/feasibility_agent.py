import os
import json
from dotenv import load_dotenv
from backend.schemas.feasibility_schema import FeasibilityAgentOutput
from google import genai
from google.genai import types

# Load environment variables
load_dotenv()

# Configure Gemini API
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY is not set. Please add it to your .env file.")

client = genai.Client(
    api_key=GEMINI_API_KEY
)

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
    "technical_risks": [
        {{
            "risk": "...",
            "impact": "...",
            "mitigation": "..."
        }}
    ]
}}

Rules:
- complexity_level should be a brief string like 'Low', 'Medium', 'High', or 'Very High'.
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

    # Initialize Gemini model (Using Google Search grounding if needed for deep risk analysis)
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[{"google_search": {}}]
        )
    )

    raw_text = response.text

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
