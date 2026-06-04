import os
import json
#import google.generativeai as genai
from dotenv import load_dotenv
from backend.schemas.task_schema import TaskAgentOutput
from google import genai

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
TASK_AGENT_PROMPT = """
You are an expert business analyst AI. You have been given a raw client meeting transcript.
 
Your job is to carefully read the transcript and extract the following business information:
 
1. **Pain Points** - Problems, frustrations, inefficiencies, or challenges the client is currently facing.
2. **Requirements** - Explicit functional and non-functional requirements the client mentioned for the system.
3. **Constraints** - Any limitations such as budget, timeline, team size, technology restrictions, or compliance requirements.
4. **Business Goals** - High-level business objectives the client wants to achieve with this project.
 
Return your response as a valid JSON object with this EXACT structure:
{{
    "pain_points": ["...", "..."],
    "requirements": ["...", "..."],
    "constraints": ["...", "..."],
    "business_goals": ["...", "..."]
}}
 
Rules:
- Each item in each list should be a clear, concise single sentence.
- Do NOT include explanations, markdown, or any text outside the JSON object.
- If a category has no information found in the transcript, return an empty list [].
- Extract only information explicitly stated or clearly implied in the transcript.
 
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
                         pain_points, requirements, constraints, and business_goals.
 
    Raises:
        ValueError: If Gemini returns an invalid or unparseable response.
    """
    if not transcript or not transcript.strip():
        raise ValueError("Transcript cannot be empty.")

    # Build the prompt
    prompt = TASK_AGENT_PROMPT.format(transcript=transcript.strip())
 
    # Initialize Gemini model
    response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=prompt
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
            f"Task Agent returned invalid JSON. Raw response:\n{raw_text}\n\nError: {e}"
        )
 
    # Validate against Pydantic schema
    return TaskAgentOutput(**parsed)