import json
import os

# Read .env file manually
env_file = ".env"
if os.path.exists(env_file):
    with open(env_file, 'r') as f:
        for line in f:
            if '=' in line and not line.startswith('#'):
                key, val = line.strip().split('=', 1)
                os.environ[key] = val

if "GEMINI_API_KEY" not in os.environ:
    print("Error: GEMINI_API_KEY not found in environment.")
    exit(1)

from backend.agents.feasibility_agent import run_feasibility_agent

# Mock requirements (same as before)
mock_requirements = {
    "pain_points": ["Current system is slow and crashes often.", "Hard to scale with user load."],
    "requirements": ["Need a fast asynchronous backend.", "Need a dynamic UI.", "Need an AI integration."],
    "constraints": ["Budget is $50,000.", "Needs to be completed in 3 months."],
    "business_goals": ["Reduce server costs by 30%.", "Increase user engagement with AI features."]
}

# Mock plan (simulating output from the planning agent)
mock_plan = {
    "architecture_type": "Multi-Agent Serverless Architecture",
    "tech_stack": {
        "frontend": "React",
        "backend": "FastAPI",
        "database": "PostgreSQL via Supabase",
        "llm": "Gemini 2.5 Flash"
    },
    "recommendation_reason": {
        "frontend": "React allows for a highly dynamic UI within budget constraints.",
        "backend": "FastAPI meets the async backend requirement efficiently.",
        "database": "Supabase manages the DB, heavily reducing server maintenance costs.",
        "llm": "Gemini provides cost-effective AI integration."
    },
    "architecture_summary": {
        "overview": "A scalable serverless backend talking to a React SPA.",
        "workflow": "User -> React -> FastAPI -> Gemini API -> DB",
        "data_flow": "JSON over REST"
    },
    "reference_docs": [],
    "mermaid_diagram": "graph TD; A-->B;"
}

print("Running Feasibility Agent...\n")
try:
    feasibility = run_feasibility_agent(mock_requirements, mock_plan)
    print("----- FEASIBILITY AGENT OUTPUT -----")
    print(json.dumps(feasibility.model_dump(), indent=2))
except Exception as e:
    print(f"Error running agent: {e}")
