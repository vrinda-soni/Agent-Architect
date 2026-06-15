import os
import json
from dotenv import load_dotenv
from backend.schemas.plan_schema import PlanningAgentOutput
from backend.llm_client import generate_with_fallback
from backend.agents.json_utils import extract_json

# Load environment variables
load_dotenv()

# Validate at least one API key is available
if not os.getenv("GEMINI_API_KEY", "").strip() and not os.getenv("OPENROUTER_API_KEY", "").strip():
    raise ValueError("No API key found. Set GEMINI_API_KEY or OPENROUTER_API_KEY in your .env file.")

# -----------------------------------------------------------------
# Prompt Template
# -----------------------------------------------------------------
PLANNING_AGENT_PROMPT = """
You are an expert Solutions Architect with deep expertise across multiple technology ecosystems.
You have been given the finalized project requirements including technology context extracted from a client meeting.

Your job is to propose a complete, realistic technical architecture based STRICTLY on the provided requirements and technology context.

CRITICAL INSTRUCTIONS:

1. TECHNOLOGY CONTEXT IS PARAMOUNT:
   - If the client mentions existing infrastructure (Azure, AWS, GCP, etc.), you MUST build on that ecosystem.
   - If the client mentions preferred technologies, you MUST incorporate them.
   - If the client mentions existing integrations or tools, your architecture MUST be compatible with them.
   - Do NOT assume a default stack (e.g., always React + FastAPI + AWS). Choose what fits THIS project.

2. CONSTRAINTS FIRST:
   Before recommending any technology, verify the recommendation fits within:
   - Budget constraints
   - Timeline constraints
   - Team size and skill constraints
   - Technology lock-in or compliance requirements

3. BE REALISTIC AND SPECIFIC:
   - Recommend specific versions or services where relevant (e.g., "Azure App Service" not just "Azure").
   - Justify EVERY technology choice with a concrete reason tied to the requirements.
   - Reference real documentation links where possible.

4. ARCHITECTURE MUST BE FEASIBLE:
   - Consider operational complexity, not just features.
   - Prefer proven, well-documented technologies unless requirements demand cutting-edge.

Return your response as a valid JSON object with this EXACT structure:
{{
    "architecture_type": "...",
    "tech_stack": {{
        "category_name": "specific technology",
        ...
    }},
    "recommendation_reason": {{
        "category_name": "reason tied to requirements/technology_context",
        ...
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
    "mermaid_diagram": "",
    "excalidraw_diagram": {{
        "nodes": [
            {{"id": "ui",       "label": "User Interface",  "type": "box",      "layer": 0}},
            {{"id": "api",      "label": "Backend API",     "type": "box",      "layer": 1}},
            {{"id": "ai",       "label": "AI Services",     "type": "box",      "layer": 2}},
            {{"id": "db",       "label": "Database",        "type": "database", "layer": 2}},
            {{"id": "ext",      "label": "External APIs",   "type": "box",      "layer": 3}}
        ],
        "edges": [
            {{"from": "ui",  "to": "api", "label": "HTTP/REST"}},
            {{"from": "api", "to": "ai",  "label": "invoke"}},
            {{"from": "api", "to": "db",  "label": "query"}},
            {{"from": "ai",  "to": "ext", "label": "call"}}
        ]
    }}
}}

Rules:
- tech_stack categories are DYNAMIC — use whatever categories make sense for this project.
- recommendation_reason keys MUST match tech_stack keys exactly.
- reference_docs: Include real, valid documentation URLs relevant to the chosen stack.
- mermaid_diagram: Leave as empty string "".
- excalidraw_diagram: Generate a proper node/edge architecture diagram for THIS project.
  - nodes: 5-10 BUSINESS-LEVEL components (not framework names). Each node needs: id (short slug), label (2-4 words), type (box/database/decision/circle), layer (0=leftmost/client, increasing towards right/external).
  - edges: Connect nodes with directional relationships. Each edge needs: from, to, label (short action like "HTTP", "query", "invoke", "stream").
  - Layer 0 = User/Client facing. Layer 1 = Gateway/API. Layer 2 = Core services. Layer 3 = Data/AI. Layer 4 = External.
  - Keep it clean — 5-10 nodes max, meaningful connections only.
- Do NOT include markdown blocks outside the JSON.
- Respond with ONLY the JSON object, nothing else.

{rag_section}

Here are the requirements (including technology context):
---
{requirements}
---

Respond with ONLY the JSON object, nothing else.
"""

# -----------------------------------------------------------------
# Planning Agent Function
# -----------------------------------------------------------------
def run_planning_agent(requirements: dict, rag_context: str = "", feedback: str = "") -> PlanningAgentOutput:
    if not requirements:
        raise ValueError("Requirements cannot be empty.")

    rag_section = rag_context
    if feedback and feedback.strip():
        rag_section = (
            f"USER FEEDBACK TO ADDRESS:\n---\n{feedback.strip()}\n---\n"
            "Incorporate the above feedback into your output before proceeding.\n\n"
            + rag_section
        )

    prompt = PLANNING_AGENT_PROMPT.format(
        requirements=json.dumps(requirements, indent=2),
        rag_section=rag_section,
    )

    # Call LLM with fallback (Gemini + Google Search -> OpenRouter)
    raw_text = generate_with_fallback(prompt, use_search=True, agent_name="planning_agent")

    # Parse the JSON response with robust extraction
    parsed = extract_json(raw_text)

    # Validate against Pydantic schema
    return PlanningAgentOutput(**parsed)
