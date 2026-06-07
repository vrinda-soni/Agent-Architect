import os
import json
from dotenv import load_dotenv
from backend.schemas.plan_schema import PlanningAgentOutput
from backend.llm_client import generate_with_fallback

# Load environment variables
load_dotenv()

# Validate at least one API key is available
if not os.getenv("GEMINI_API_KEY", "").strip() and not os.getenv("OPENROUTER_API_KEY", "").strip():
    raise ValueError("No API key found. Set GEMINI_API_KEY or OPENROUTER_API_KEY in your .env file.")

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
    "mermaid_diagram": "flowchart TD\\n    Users[End Users] --> Portal[Client Portal]\\n    Portal --> Platform[Core Platform]\\n    Platform --> AI[AI Services]\\n    Platform --> Data[(Data Store)]"
}}

Rules:
- The tech_stack and recommendation_reason keys must match.
- reference_docs must be a list of objects with title and url.
- mermaid_diagram MUST be a valid, SIMPLE Mermaid flowchart using flowchart TD syntax.
- The diagram must use BUSINESS-LEVEL component names only (5-8 nodes max).
  Examples: "End Users", "Admin Portal", "Core Platform", "AI Engine", "Data Store", "External APIs".
- Do NOT put framework or library names in the diagram (no React, FastAPI, PostgreSQL, etc.).
- Keep node labels short (max 3 words). Use clear left-to-right or top-down flow.
- CRITICAL: Each mermaid statement must be on its OWN LINE separated by \\n (newlines).
- Do NOT use semicolons (;) to separate statements. Use newlines only.
- Do NOT wrap the diagram in markdown code blocks inside the JSON string.
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

    # Call LLM with fallback (Gemini + Google Search -> OpenRouter)
    raw_text = generate_with_fallback(prompt, use_search=True)

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