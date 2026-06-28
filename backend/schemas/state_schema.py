"""
state_schema.py
---------------
Shared LangGraph state container.  Every agent node reads from and writes
to this TypedDict.  total=False makes every key optional so partial state
updates work correctly with the MemorySaver checkpointer.
"""

from typing import TypedDict, Optional, Dict, Any


class AgentState(TypedDict, total=False):

    # ── Pipeline inputs ───────────────────────────────────────────────────────
    transcript:  str        # raw client meeting transcript
    project_id:  str        # Supabase project UUID; used for Langfuse tracing
    include_mvp: bool       # whether estimation should flag MVP tasks
    rag_context: str        # pre-formatted RAG chunks injected into agent prompts

    # ── Agent outputs (raw, before HITL approval) ─────────────────────────────
    requirements: Optional[Dict[str, Any]]   # task_agent output
    plan:         Optional[Dict[str, Any]]   # planning_agent output
    feasibility:  Optional[Dict[str, Any]]   # feasibility_agent output
    estimation:   Optional[Dict[str, Any]]   # estimation_agent output
    report:       Optional[Dict[str, Any]]   # report_agent output

    # ── HITL-approved copies ──────────────────────────────────────────────────
    approved_requirements: Optional[Dict[str, Any]]
    approved_plan:         Optional[Dict[str, Any]]
    approved_feasibility:  Optional[Dict[str, Any]]
    approved_estimation:   Optional[Dict[str, Any]]

    # ── HITL control ──────────────────────────────────────────────────────────
    # hitl_action values:
    #   "approve"     — accept output and advance
    #   "regenerate"  — re-run the preceding agent (with feedback)
    #   "regen_plan"  — re-run planning only (HITL #2)
    #   "regen_feas"  — re-run feasibility only (HITL #2)
    hitl_action:      str
    feedback:         str   # free-text user guidance passed into the re-run
    cancel_requested: bool  # set by Stop button during long estimation runs
