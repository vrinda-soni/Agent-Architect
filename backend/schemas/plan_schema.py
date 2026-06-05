"""
plan_schema.py
--------------
Pydantic models defining the structured output of the Planning Agent.
"""

from pydantic import BaseModel, Field
from typing import List, Dict

class ReferenceDoc(BaseModel):
    title: str
    url: str

class ArchitectureSummary(BaseModel):
    overview: str
    workflow: str
    data_flow: str

class PlanningAgentOutput(BaseModel):
    """
    Structured output from the Planning Agent.
    Contains the technical architecture, stack, and integrations based on requirements.
    """
    
    architecture_type: str = Field(
        ...,
        description="The overall type of architecture (e.g., 'Multi-Agent Architecture', 'Microservices', 'Monolithic')."
    )

    tech_stack: Dict[str, str] = Field(
        default_factory=dict,
        description="A mapping of technology categories (e.g., 'frontend', 'backend', 'database') to the chosen technology."
    )
    
    recommendation_reason: Dict[str, str] = Field(
        default_factory=dict,
        description="A mapping of technology categories to the specific reason why they were chosen."
    )
    
    architecture_summary: ArchitectureSummary = Field(
        ...,
        description="A detailed summary of the architecture including overview, workflow, and data flow."
    )
    
    reference_docs: List[ReferenceDoc] = Field(
        default_factory=list,
        description="A list of relevant documentation links."
    )
    
    mermaid_diagram: str = Field(
        ...,
        description="A Mermaid.js compatible diagram string representing the architecture."
    )
