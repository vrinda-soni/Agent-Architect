import os
import json
from google import genai
from google.genai import types
from backend.agents.planning_agent import PLANNING_AGENT_PROMPT, PlanningAgentOutput

with open('.env') as f:
    for line in f:
        if line.startswith('GEMINI_API_KEY='):
            os.environ['GEMINI_API_KEY'] = line.strip().split('=', 1)[1]

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

reqs = {
    "pain_points": ["Manual data entry is slow", "Hard to track user activity"],
    "requirements": ["Web portal for admins", "REST API for mobile apps"],
    "constraints": ["Must use Python", "Limited budget"],
    "business_goals": ["Automate reporting", "Increase user retention"]
}

prompt = PLANNING_AGENT_PROMPT.format(requirements=json.dumps(reqs, indent=2))

print("Generating plan with Google Search grounding...")
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=prompt,
    config=types.GenerateContentConfig(
        tools=[{"google_search": {}}]
    )
)

print("\n--- RAW TEXT ---")
print(response.text)
