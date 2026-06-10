import os
import json
from dotenv import load_dotenv
from backend.schemas.task_schema import TaskAgentOutput
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
TASK_AGENT_PROMPT = """
You are an elite Senior Business Analyst and Solutions Consultant with 15+ years of experience in client-facing project discovery. You have been given a raw client meeting transcript.

Your mission is to perform an exhaustive, line-by-line analysis of the transcript and extract EVERY piece of business-relevant information. No detail is too small — every word matters.

You must extract the following five categories with maximum accuracy and completeness:

1. **Pain Points** — Problems, frustrations, inefficiencies, bottlenecks, or challenges the client is currently facing or anticipates. Include both explicit complaints AND implied frustrations.

2. **Requirements** — All functional requirements (what the system must DO) and non-functional requirements (performance, security, scalability, availability, maintainability). Include both explicitly stated AND clearly implied requirements. Capture partial mentions and incomplete thoughts as well.

3. **Constraints** — Any limitations: budget caps, hard deadlines, timeline pressure, team size limits, existing technology lock-in, compliance requirements (GDPR, HIPAA, SOC2, etc.), geographic restrictions, or organizational policies.

4. **Business Goals** — High-level strategic objectives: revenue targets, user acquisition goals, market expansion, cost reduction, automation targets, competitive positioning, or transformation objectives.

5. **Technology Context** — CRITICAL: Any technology the client currently uses, mentions wanting to use, or has existing investments in. This includes:
   - Cloud providers (AWS, Azure, GCP, etc.)
   - Existing infrastructure or servers
   - Programming languages or frameworks in use
   - Third-party services or APIs already in use
   - Databases currently deployed
   - CI/CD tools, DevOps practices
   - Security tools or compliance platforms
   - Any technology the client explicitly says they want or do NOT want

For technology_context, organize as key-value pairs where the key describes the category and the value describes what was mentioned. Use these categories when applicable: existing_infrastructure, preferred_cloud, required_technologies, existing_integrations, compliance_tools, devops_tools, data_platforms. Add any other relevant categories you find.

CRITICAL RULES:
- Read EVERY sentence carefully. Do not skip or summarize away details.
- If the client says "we have Azure" → capture it in technology_context as preferred_cloud.
- If the client says "we need it to handle 1000 users" → capture as a non-functional requirement.
- If the client mentions a competitor or alternative they evaluated → capture as context.
- Preserve the original intent and specificity — do not generalize or dilute.
- If a statement is ambiguous, capture it as-is and note the ambiguity.
- Empty lists are acceptable ONLY if the transcript genuinely contains zero mentions of that category.

Return your response as a valid JSON object with this EXACT structure:
{{
    "pain_points": ["...", "..."],
    "requirements": ["...", "..."],
    "constraints": ["...", "..."],
    "business_goals": ["...", "..."],
    "technology_context": {{
        "existing_infrastructure": "...",
        "preferred_cloud": "...",
        "required_technologies": "...",
        "existing_integrations": "...",
        "compliance_tools": "..."
    }}
}}

Rules:
- Each item in lists should be a clear, concise single sentence preserving original context.
- technology_context values should be descriptive sentences explaining what was mentioned.
- Do NOT include explanations, markdown, or any text outside the JSON object.
- Do NOT invent information not present in the transcript.
- Extract ONLY information explicitly stated or clearly implied in the transcript.

Here is the client meeting transcript:
---
{transcript}
---
 
Respond with ONLY the JSON object, nothing else.
"""
 

# -----------------------------------------------------------------
# Task Agent Function
# -----------------------------------------------------------------
def run_task_agent(transcript: str) -> TaskAgentOutput:
    """
    Runs the Task Identification Agent on the provided transcript.

    Args:
        transcript (str): The raw client meeting transcript text.

    Returns:
        TaskAgentOutput: A structured Pydantic model containing extracted
                         pain_points, requirements, constraints, business_goals,
                         and technology_context.

    Raises:
        ValueError: If Gemini returns an invalid or unparseable response.
    """
    if not transcript or not transcript.strip():
        raise ValueError("Transcript cannot be empty.")

    # Build the prompt
    prompt = TASK_AGENT_PROMPT.format(transcript=transcript.strip())
 
    # Call LLM with fallback (Gemini -> OpenRouter)
    raw_text = generate_with_fallback(prompt, use_search=False, agent_name="task_agent")
    
    # Parse the JSON response with robust extraction
    parsed = extract_json(raw_text)
 
    # Validate against Pydantic schema
    return TaskAgentOutput(**parsed)
