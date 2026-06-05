from langgraph.graph import StateGraph, START, END
from backend.schemas.state_schema import AgentState
from backend.agents.task_agent import run_task_agent
from backend.agents.planning_agent import run_planning_agent
from backend.agents.feasibility_agent import run_feasibility_agent
 
 
# -----------------------------------------------------------------
# Node functions
# -----------------------------------------------------------------
 
def task_agent_node(state: AgentState) -> AgentState:
    """Reads transcript, calls run_task_agent, writes requirements."""
    transcript = state.get("transcript", "")
    if not transcript:
        raise ValueError("transcript is required")
    output = run_task_agent(transcript)
    return {"requirements": output.model_dump()}
 
 
def hitl_1_node(state: AgentState) -> AgentState:
    """
    HITL #1 pass-through node.
    The frontend sets hitl_action (and optionally feedback) in state before
    resuming the graph. This node copies requirements -> approved_requirements.
    """
    requirements = state.get("requirements", {})
    return {
        "approved_requirements": requirements,
        "hitl_action": state.get("hitl_action", "approve"),
    }
 
 
def planning_agent_node(state: AgentState) -> AgentState:
    """
    Planning Agent node.
    Reads approved_requirements, writes plan.
    """
    approved_requirements = state.get("approved_requirements", {})
    if not approved_requirements:
        raise ValueError("approved_requirements is required for the Planning Agent")
        
    output = run_planning_agent(approved_requirements)
    return {"plan": output.model_dump()}
 
 
def feasibility_agent_node(state: AgentState) -> AgentState:
    """
    Feasibility Agent node.
    Reads approved_requirements and plan, writes feasibility.
    """
    approved_requirements = state.get("approved_requirements", {})
    plan = state.get("plan", {})
    
    if not approved_requirements or not plan:
        raise ValueError("approved_requirements and plan are required for the Feasibility Agent")
        
    output = run_feasibility_agent(approved_requirements, plan)
    return {"feasibility": output.model_dump()}
 
 
def hitl_2_node(state: AgentState) -> AgentState:
    """
    HITL #2 pass-through node.
    The frontend sets hitl_action (and optionally feedback) in state before
    resuming the graph. This node copies plan + feasibility -> approved_plan.
    """
    plan = state.get("plan", {})
    feasibility = state.get("feasibility", {})
    return {
        "approved_plan": {"plan": plan, "feasibility": feasibility},
        "hitl_action": state.get("hitl_action", "approve"),
    }
 
 
def report_agent_node(state: AgentState) -> AgentState:
    """
    Report Agent node — stub until report_agent.py is implemented.
    Reads approved_requirements, approved_plan, feasibility, writes report.
    """
    # TODO: replace with real report agent call once implemented
    return {
        "report": {
            "_stub": True,
            "approved_requirements": state.get("approved_requirements", {}),
            "approved_plan": state.get("approved_plan", {}),
            "feasibility": state.get("feasibility", {}),
        }
    }
 
 
# -----------------------------------------------------------------
# HITL routing functions
# -----------------------------------------------------------------
 
def route_hitl_1(state: AgentState) -> str:
    """
    Routes after HITL #1.
    - approve / edit  -> planning_agent
    - regenerate      -> task_agent
    - unknown         -> planning_agent (treat as approve)
    """
    action = state.get("hitl_action", "approve")
    if action == "regenerate":
        return "task_agent"
    return "planning_agent"
 
 
def route_hitl_2(state: AgentState) -> str:
    """
    Routes after HITL #2.
    - approve / edit  -> report_agent
    - regenerate      -> planning_agent
    - unknown         -> report_agent (treat as approve)
    """
    action = state.get("hitl_action", "approve")
    if action == "regenerate":
        return "planning_agent"
    return "report_agent"
 
 
# -----------------------------------------------------------------
# Build and compile the StateGraph
# -----------------------------------------------------------------
 
_graph = StateGraph(AgentState)
 
# Register nodes
_graph.add_node("task_agent", task_agent_node)
_graph.add_node("hitl_1", hitl_1_node)
_graph.add_node("planning_agent", planning_agent_node)
_graph.add_node("feasibility_agent", feasibility_agent_node)
_graph.add_node("hitl_2", hitl_2_node)
_graph.add_node("report_agent", report_agent_node)
 
# Sequential edges
_graph.add_edge(START, "task_agent")
_graph.add_edge("task_agent", "hitl_1")
_graph.add_edge("planning_agent", "feasibility_agent")
_graph.add_edge("feasibility_agent", "hitl_2")
_graph.add_edge("report_agent", END)
 
# Conditional edges for HITL checkpoints
_graph.add_conditional_edges(
    "hitl_1",
    route_hitl_1,
    {"task_agent": "task_agent", "planning_agent": "planning_agent"},
)
_graph.add_conditional_edges(
    "hitl_2",
    route_hitl_2,
    {"planning_agent": "planning_agent", "report_agent": "report_agent"},
)
 
# Compiled graph — exported for frontend / callers
app = _graph.compile()
 
 
def run_workflow(transcript: str) -> AgentState:
    """
    Convenience helper for invoking the workflow.
 
    Args:
        transcript: Raw client meeting transcript text.
 
    Returns:
        Final AgentState containing all populated fields after the workflow completes.
    """
    initial_state: AgentState = {"transcript": transcript}
    return app.invoke(initial_state)