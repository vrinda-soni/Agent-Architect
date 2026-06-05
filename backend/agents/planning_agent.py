import os
import json
from dotenv import load_dotenv
from backend.schemas.plan_schema import PlanningAgentOutput
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
PLANNING_AGENT_PROMPT = """
You are an expert Solutions Architect. You have been given the finalized requirements for a project extracted by the Task Agent.
These requirements include pain points, requirements, constraints, and business goals.

Your job is to carefully review these requirements and propose a complete technical plan. 
Use your web searching capabilities to find the most up-to-date and appropriate architectures, reference documentation, and technology stacks.

CRITICAL INSTRUCTION:
Before recommending any architecture or technology stack, you MUST ALWAYS prioritize the following considerations:
1. Constraints
2. Budget
3. Timeline
4. Team Size

The chosen tech stack and architecture must realistically fit these limitations.

Return your response as a valid JSON object with this EXACT structure:
{{
    "architecture_type": "...",
    "tech_stack": {{
        "frontend": "...",
        "backend": "...",
        "database": "...",
        "vector_database": "...",
        "llm": "...",
        "orchestration": "...",
        "deployment": "..."
    }},
    "recommendation_reason": {{
        "frontend": "...",
        "backend": "...",
        "database": "...",
        "vector_database": "...",
        "llm": "...",
        "orchestration": "...",
        "deployment": "..."
    }},
    "architecture_summary": {{
        "overview": "...",
        "workflow": "...",
        "data_flow": "..."
    }},
    "reference_docs": [
        {{
            "title": "...",
            "url": "..."
        }}
    ],
    "mermaid_diagram": "graph TD; A-->B;"
}}

Rules:
- The tech_stack and recommendation_reason keys must match.
- reference_docs must be a list of objects with title and url.
- mermaid_diagram MUST be a valid Mermaid string mapping out the system architecture. Make sure to escape newlines correctly in JSON!
- Do NOT include markdown blocks outside the JSON.
- Respond with ONLY the JSON object, nothing else.

Here are the requirements:
---
{requirements}
---

Respond with ONLY the JSON object, nothing else.
"""

# -----------------------------------------------------------------
# Planning Agent Function
# -----------------------------------------------------------------
def run_planning_agent(requirements: dict) -> PlanningAgentOutput:
    """
    Runs the Planning Agent on the provided requirements.

    Args:
        requirements (dict): The approved requirements from the task agent.

    Returns:
        PlanningAgentOutput: A structured Pydantic model containing the technical plan.

    Raises:
        ValueError: If Gemini returns an invalid or unparseable response.
    """
    if not requirements:
        raise ValueError("Requirements cannot be empty.")

    # Build the prompt
    prompt = PLANNING_AGENT_PROMPT.format(requirements=json.dumps(requirements, indent=2))

    # Initialize Gemini model with Google Search grounding
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
            f"Planning Agent returned invalid JSON. Raw response:\n{raw_text}\n\nError: {e}"
        )

    # Validate against Pydantic schema
    return PlanningAgentOutput(**parsed)