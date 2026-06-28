"""
backend/workflow.py
-------------------
LangGraph multi-agent pipeline for the POC Generator.

Graph shape:
  START → task_agent → [HITL #1 interrupt] → hitl_1
    hitl_1 → planning_agent  (approve)
           → task_agent      (regenerate)
    planning_agent → feasibility_agent → [HITL #2 interrupt] → hitl_2
    hitl_2 → estimation_agent  (approve)
           → planning_agent    (regen_plan)
           → feasibility_agent (regen_feas)
    estimation_agent → [HITL #3 interrupt] → hitl_3
    hitl_3 → report_agent    (approve)
           → estimation_agent (regenerate)
    report_agent → END

HITL pattern:
  - MemorySaver checkpointer persists state between interrupts.
  - Graph interrupts BEFORE each hitl_* node.
  - Chainlit reads current state, shows output to user, writes
    hitl_action (+ optional feedback) into state, then resumes:
      graph.invoke(Command(resume=updated_state), config=thread_config)
  - Trace objects are intentionally NOT stored in state — MemorySaver
    cannot serialise them. Each node creates its own Langfuse span.
"""

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt

from backend.schemas.state_schema import AgentState
from backend.agents.task_agent import run_task_agent
from backend.agents.planning_agent import run_planning_agent
from backend.agents.feasibility_agent import run_feasibility_agent
from backend.agents.estimation_agent import run_estimation_pass1, run_estimation_pass2
from backend.agents.report_agent import run_report_agent
from backend.langfuse_client import create_trace


def _trace(state: AgentState, name: str):
    try:
        return create_trace(name=name, session_id=str(state.get("project_id") or "workflow"))
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Agent nodes
# ─────────────────────────────────────────────────────────────────────────────

def task_agent_node(state: AgentState) -> dict:
    transcript = state.get("transcript", "")
    feedback   = state.get("feedback", "")
    if not transcript:
        raise ValueError("transcript is required")
    t = _trace(state, "task_agent")
    output = run_task_agent(transcript, feedback=feedback, trace=t)
    if t:
        try: t.end()
        except Exception: pass
    return {"requirements": output.model_dump(), "feedback": ""}


def planning_agent_node(state: AgentState) -> dict:
    reqs        = state.get("approved_requirements", {})
    rag_context = state.get("rag_context", "")
    feedback    = state.get("feedback", "")
    if not reqs:
        raise ValueError("approved_requirements is required")
    t = _trace(state, "planning_agent")
    output = run_planning_agent(reqs, rag_context=rag_context, feedback=feedback, trace=t)
    if t:
        try: t.end()
        except Exception: pass
    return {"plan": output.model_dump(), "feedback": ""}


def feasibility_agent_node(state: AgentState) -> dict:
    reqs     = state.get("approved_requirements", {})
    plan     = state.get("plan", {})
    feedback = state.get("feedback", "")
    if not reqs or not plan:
        raise ValueError("approved_requirements and plan are required")
    t = _trace(state, "feasibility_agent")
    output = run_feasibility_agent(reqs, plan, feedback=feedback, trace=t)
    if t:
        try: t.end()
        except Exception: pass
    return {"feasibility": output.model_dump(), "feedback": ""}


def estimation_agent_node(state: AgentState) -> dict:
    reqs        = state.get("approved_requirements", {})
    plan        = state.get("approved_plan") or state.get("plan", {})
    feasibility = state.get("approved_feasibility") or state.get("feasibility", {})
    include_mvp = state.get("include_mvp", False)
    rag_context = state.get("rag_context", "")
    feedback    = state.get("feedback", "")
    if not all([reqs, plan, feasibility]):
        raise ValueError("approved_requirements, plan, and feasibility are required")
    t         = _trace(state, "estimation_agent")
    p1_result = run_estimation_pass1(reqs, plan, feasibility, feedback, rag_context, t)
    output    = run_estimation_pass2(p1_result, include_mvp, t)
    if t:
        try: t.end()
        except Exception: pass
    return {"estimation": output.model_dump(), "feedback": ""}


def report_agent_node(state: AgentState) -> dict:
    reqs        = state.get("approved_requirements", {})
    plan        = state.get("approved_plan") or state.get("plan", {})
    feasibility = state.get("approved_feasibility") or state.get("feasibility", {})
    estimation  = state.get("approved_estimation") or state.get("estimation", {})
    if not all([reqs, plan, feasibility, estimation]):
        raise ValueError("All prior stages must be complete before generating a report")
    t      = _trace(state, "report_agent")
    output = run_report_agent(reqs, plan, feasibility, estimation, trace=t)
    if t:
        try: t.end()
        except Exception: pass
    return {"report": output.model_dump()}


# ─────────────────────────────────────────────────────────────────────────────
# HITL nodes — use interrupt() (LangGraph 1.x pattern).
# The frontend resumes via invoke(Command(resume={...}), thread_cfg).
# ─────────────────────────────────────────────────────────────────────────────

def hitl_1_node(state: AgentState) -> dict:
    """Pause for user review of task agent requirements."""
    action_data = interrupt(state.get("requirements"))
    action = action_data.get("hitl_action", "approve")
    if action != "regenerate":
        return {
            "hitl_action":          action,
            "feedback":             action_data.get("feedback", ""),
            "rag_context":          action_data.get("rag_context", state.get("rag_context", "")),
            "approved_requirements": action_data.get("approved_requirements") or state.get("requirements", {}),
        }
    return {
        "hitl_action": action,
        "feedback":    action_data.get("feedback", ""),
    }


def hitl_2_node(state: AgentState) -> dict:
    """Pause for user review of planning + feasibility output."""
    action_data = interrupt({"plan": state.get("plan"), "feasibility": state.get("feasibility")})
    action = action_data.get("hitl_action", "approve")
    if action == "approve":
        return {
            "hitl_action":          action,
            "feedback":             action_data.get("feedback", ""),
            "include_mvp":          action_data.get("include_mvp", state.get("include_mvp", False)),
            "rag_context":          action_data.get("rag_context", state.get("rag_context", "")),
            "approved_plan":        action_data.get("approved_plan") or state.get("plan", {}),
            "approved_feasibility": action_data.get("approved_feasibility") or state.get("feasibility", {}),
        }
    return {
        "hitl_action": action,
        "feedback":    action_data.get("feedback", ""),
        "rag_context": action_data.get("rag_context", state.get("rag_context", "")),
    }


def hitl_3_node(state: AgentState) -> dict:
    """Pause for user review of estimation output."""
    action_data = interrupt(state.get("estimation"))
    action = action_data.get("hitl_action", "approve")
    if action != "regenerate":
        return {
            "hitl_action":       action,
            "feedback":          action_data.get("feedback", ""),
            "approved_estimation": action_data.get("approved_estimation") or state.get("estimation", {}),
        }
    return {
        "hitl_action": action,
        "feedback":    action_data.get("feedback", ""),
        "include_mvp": action_data.get("include_mvp", state.get("include_mvp", False)),
        "rag_context": action_data.get("rag_context", state.get("rag_context", "")),
    }


# ─────────────────────────────────────────────────────────────────────────────
# HITL routing
# ─────────────────────────────────────────────────────────────────────────────

def route_hitl_1(state: AgentState) -> str:
    return "task_agent" if state.get("hitl_action") == "regenerate" else "planning_agent"


def route_hitl_2(state: AgentState) -> str:
    action = state.get("hitl_action", "approve")
    if action == "regen_plan":
        return "planning_agent"
    if action == "regen_feas":
        return "feasibility_agent"
    return "estimation_agent"


def route_hitl_3(state: AgentState) -> str:
    return "estimation_agent" if state.get("hitl_action") == "regenerate" else "report_agent"


# ─────────────────────────────────────────────────────────────────────────────
# Build and compile the graph
# ─────────────────────────────────────────────────────────────────────────────

_graph = StateGraph(AgentState)

_graph.add_node("task_agent",        task_agent_node)
_graph.add_node("hitl_1",            hitl_1_node)
_graph.add_node("planning_agent",    planning_agent_node)
_graph.add_node("feasibility_agent", feasibility_agent_node)
_graph.add_node("hitl_2",            hitl_2_node)
_graph.add_node("estimation_agent",  estimation_agent_node)
_graph.add_node("hitl_3",            hitl_3_node)
_graph.add_node("report_agent",      report_agent_node)

_graph.add_edge(START, "task_agent")
_graph.add_edge("task_agent", "hitl_1")
_graph.add_conditional_edges("hitl_1", route_hitl_1, {
    "task_agent":     "task_agent",
    "planning_agent": "planning_agent",
})
_graph.add_edge("planning_agent", "feasibility_agent")
_graph.add_edge("feasibility_agent", "hitl_2")
_graph.add_conditional_edges("hitl_2", route_hitl_2, {
    "planning_agent":    "planning_agent",
    "feasibility_agent": "feasibility_agent",
    "estimation_agent":  "estimation_agent",
})
_graph.add_edge("estimation_agent", "hitl_3")
_graph.add_conditional_edges("hitl_3", route_hitl_3, {
    "estimation_agent": "estimation_agent",
    "report_agent":     "report_agent",
})
_graph.add_edge("report_agent", END)

# MemorySaver keeps state in-process between HITL interrupts.
# For multi-user production, swap to a Supabase-backed checkpointer.
# interrupt() inside each hitl_*_node handles pausing (LangGraph 1.x pattern).
app = _graph.compile(checkpointer=MemorySaver())
