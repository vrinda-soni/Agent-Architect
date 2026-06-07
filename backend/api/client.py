import os
import requests
from typing import Optional

from backend.schemas.task_schema import TaskAgentOutput
from backend.schemas.plan_schema import PlanningAgentOutput
from backend.schemas.feasibility_schema import FeasibilityAgentOutput
from backend.schemas.estimation_schema import EstimationAgentOutput
from backend.schemas.report_schema import ReportAgentOutput

API_URL = os.getenv("API_URL", "http://localhost:8000")
TIMEOUT = 300  # 5 min — LLM calls can be slow


def _post(path: str, payload: dict) -> dict:
    resp = requests.post(f"{API_URL}{path}", json=payload, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def call_task_agent(transcript: str) -> TaskAgentOutput:
    data = _post("/api/task-agent", {"transcript": transcript})
    return TaskAgentOutput(**data)


def call_planning_agent(
    requirements: dict,
    project_id: Optional[str] = None,
) -> PlanningAgentOutput:
    data = _post("/api/planning-agent", {"requirements": requirements, "project_id": project_id})
    return PlanningAgentOutput(**data)


def call_feasibility_agent(requirements: dict, plan: dict) -> FeasibilityAgentOutput:
    data = _post("/api/feasibility-agent", {"requirements": requirements, "plan": plan})
    return FeasibilityAgentOutput(**data)


def call_estimation_agent(
    requirements: dict,
    plan: dict,
    feasibility: dict,
    project_id: Optional[str] = None,
) -> EstimationAgentOutput:
    data = _post(
        "/api/estimation-agent",
        {
            "requirements": requirements,
            "plan": plan,
            "feasibility": feasibility,
            "project_id": project_id,
        },
    )
    return EstimationAgentOutput(**data)


def call_report_agent(
    requirements: dict,
    plan: dict,
    feasibility: dict,
    estimation: dict,
) -> ReportAgentOutput:
    data = _post(
        "/api/report-agent",
        {
            "requirements": requirements,
            "plan": plan,
            "feasibility": feasibility,
            "estimation": estimation,
        },
    )
    return ReportAgentOutput(**data)
