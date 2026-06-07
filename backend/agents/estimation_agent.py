import os
import json
from dotenv import load_dotenv
from backend.schemas.estimation_schema import EstimationAgentOutput
from backend.llm_client import generate_with_fallback

# Load environment variables
load_dotenv()

# Validate at least one API key is available
if not os.getenv("GEMINI_API_KEY", "").strip() and not os.getenv("OPENROUTER_API_KEY", "").strip():
    raise ValueError("No API key found. Set GEMINI_API_KEY or OPENROUTER_API_KEY in your .env file.")

# -----------------------------------------------------------------
# Prompt Template
# -----------------------------------------------------------------
ESTIMATION_AGENT_PROMPT = """
You are a Senior Technical Architect and Estimation Specialist.

Your task is to analyze the provided project requirements, architecture plan, and feasibility analysis, then generate a detailed software development effort estimation.

INPUTS:

1. Task Agent Output
   - Pain Points
   - Requirements
   - Constraints
   - Business Goals

2. Planning Agent Output
   - Architecture Type
   - Technology Stack
   - Architecture Summary
   - Mermaid Diagram

3. Feasibility Agent Output
   - Feasibility Summary
   - Complexity Level
   - Technical Risks

OBJECTIVE:

Break the project into logical modules and features.

For each feature, estimate development effort in hours for:
- HTML
- ReactJS
- Python
- AI

Use realistic software engineering judgement.

The estimations should be suitable for an MVP implementation and should reflect the complexity of the feature.

Do NOT generate vague estimates.
Do NOT provide cost estimates.
Do NOT provide budget calculations.
Do NOT provide team-size recommendations.

Focus only on development effort estimation.

For every feature provide:
- functionality_type: High-level functionality category (e.g., "Project Setup", "Authentication", "Dashboard", "AI Engine")
- module: The logical module name
- feature: Detailed description of the feature
- complexity: One of "Low", "Medium", "High", "Very High"
- interface_type: Interface classification like "Web", "Backend", "AI", "Web + Backend", "Web + Backend + AI + Cloud + DevOps"
- html_hours: integer hours for HTML/CSS
- react_hours: integer hours for ReactJS
- python_hours: integer hours for Python backend
- ai_hours: integer hours for AI/ML integration
- tech_remarks: Technical implementation notes
- ba_remarks: Business analyst notes

COMPLEXITY RULES:

Low:
- Simple CRUD
- Basic forms
- Static pages

Medium:
- Authentication
- Dashboards
- API Integrations
- Business Logic

High:
- Real-time systems
- Multi-agent workflows
- Complex backend orchestration
- Advanced analytics

Very High:
- Voice AI
- Multi-agent AI orchestration
- RAG systems
- Streaming systems
- Large-scale distributed architectures

ESTIMATION GUIDELINES:

- Hours must be realistic.
- AI-heavy features should allocate more effort to AI hours.
- Backend-heavy features should allocate more effort to Python hours.
- Frontend-heavy features should allocate more effort to HTML and ReactJS hours.
- Do not assign hours where they are not required.
- If a feature does not require AI, AI hours should be 0.
- If a feature does not require HTML, HTML hours should be 0.
- Include a "Project Setup" row at the beginning for environment setup, CI/CD, repository configuration, etc.
- Include all major modules required for the project.
- Do not skip important features.
- Ensure totals are calculated correctly.

OUTPUT FORMAT:

Return your response as a valid JSON object with this EXACT structure:
{{
    "estimations": [
        {{
            "functionality_type": "...",
            "module": "...",
            "feature": "...",
            "complexity": "...",
            "interface_type": "...",
            "html_hours": 0,
            "react_hours": 0,
            "python_hours": 0,
            "ai_hours": 0,
            "tech_remarks": "...",
            "ba_remarks": "..."
        }}
    ],
    "totals": {{
        "html_hours": 0,
        "react_hours": 0,
        "python_hours": 0,
        "ai_hours": 0,
        "grand_total_hours": 0
    }}
}}

IMPORTANT:
- Generate all major modules required for the project.
- Do not skip important features.
- Ensure totals are calculated correctly (sum of all respective columns).
- Return ONLY valid JSON.
- Do not include markdown.
- Do not include explanations outside the JSON.

{rag_section}

Here are the requirements:
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
        requirements (dict): The approved requirements.
        plan (dict): The generated architecture plan.
        feasibility (dict): The feasibility analysis.

    Returns:
        EstimationAgentOutput: A structured Pydantic model containing effort estimations.

    Raises:
        ValueError: If Gemini returns an invalid or unparseable response.
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
            f"Estimation Agent returned invalid JSON. Raw response:\n{raw_text}\n\nError: {e}"
        )

    # Validate against Pydantic schema
    return EstimationAgentOutput(**parsed)
