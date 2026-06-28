import json
import os
from dotenv import load_dotenv

# Ensure we use the API key
load_dotenv()
if "GEMINI_API_KEY" not in os.environ:
    print("Error: GEMINI_API_KEY not found in environment.")
    exit(1)

from backend.agents.planning_agent import run_planning_agent

# Mock requirements extracted from the previous Task Agent
mock_requirements = {
    "pain_points": ["Current system is slow and crashes often.", "Hard to scale with user load."],
    "requirements": ["Need a fast asynchronous backend.", "Need a dynamic UI.", "Need an AI integration."],
    "constraints": ["Budget is $50,000.", "Needs to be completed in 3 months."],
    "business_goals": ["Reduce server costs by 30%.", "Increase user engagement with AI features."]
}

print("Running Planning Agent (without API/Integrations or Web Search)...\n")
try:
    plan = run_planning_agent(mock_requirements)
    print("----- PLANNING AGENT OUTPUT -----")
    print(json.dumps(plan.model_dump(), indent=2))
except Exception as e:
    print(f"Error running agent: {e}")
