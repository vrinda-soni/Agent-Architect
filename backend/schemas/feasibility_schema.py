"""
feasibility_schema.py
---------------------
Pydantic models defining the structured output of the Feasibility Agent.
"""

from pydantic import BaseModel, Field
from typing import List

class TechnicalRisk(BaseModel):
    risk: str = Field(..., description="The identified technical risk.")
    impact: str = Field(..., description="The potential impact of the risk.")
    mitigation: str = Field(..., description="Proposed mitigation strategy for the risk.")

class FeasibilityAgentOutput(BaseModel):
    """
    Structured output from the Feasibility Agent.
    Evaluates the technical feasibility of the proposed plan based on requirements.
    """
    
    feasibility_summary: str = Field(
        ...,
        description="A high-level summary of whether the proposed architecture is feasible."
    )
    
    complexity_level: str = Field(
        ...,
        description="The estimated complexity of the project: 'Low', 'Medium', 'High', or 'Very High'."
    )

    architecture_confidence: str = Field(
        ...,
        description="Confidence in the proposed architecture fitting requirements: 'Low', 'Medium', or 'High'."
    )

    feasibility_confidence: str = Field(
        ...,
        description="Confidence that the plan can be delivered within constraints: 'Low', 'Medium', or 'High'."
    )
    
    technical_risks: List[TechnicalRisk] = Field(
        default_factory=list,
        description="A list of technical risks along with their impact and mitigation strategies."
    )
