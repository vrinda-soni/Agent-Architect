"""
estimation_schema.py
--------------------
Pydantic models defining the structured output of the Estimation Agent.
"""

from pydantic import BaseModel, Field
from typing import List


class EstimationItem(BaseModel):
    """
    A single feature estimation item.
    """
    functionality_type: str = Field(
        default="",
        description="High-level functionality category (e.g., 'Project Setup', 'Voice Roleplay Engine')."
    )

    module: str = Field(
        ...,
        description="The logical module or component this feature belongs to."
    )

    feature: str = Field(
        ...,
        description="Detailed description of the feature to be implemented."
    )

    complexity: str = Field(
        ...,
        description="Complexity level: 'Low', 'Medium', 'High', or 'Very High'."
    )

    interface_type: str = Field(
        ...,
        description="Type of interface: 'Web', 'Backend', 'AI', 'Web + Backend', 'Web + Backend + AI + Cloud + DevOps', etc."
    )

    html_hours: int = Field(
        default=0,
        ge=0,
        description="Estimated hours for HTML/CSS development."
    )

    react_hours: int = Field(
        default=0,
        ge=0,
        description="Estimated hours for ReactJS frontend development."
    )

    python_hours: int = Field(
        default=0,
        ge=0,
        description="Estimated hours for Python backend development."
    )

    ai_hours: int = Field(
        default=0,
        ge=0,
        description="Estimated hours for AI/ML integration and prompt engineering."
    )

    tech_remarks: str = Field(
        default="",
        description="Technical remarks, implementation notes, or concerns from a tech lead perspective."
    )

    ba_remarks: str = Field(
        default="",
        description="Business analyst remarks, clarifications, or acceptance criteria notes."
    )


class EstimationTotals(BaseModel):
    """
    Aggregated totals across all estimation items.
    """
    html_hours: int = Field(default=0, ge=0)
    react_hours: int = Field(default=0, ge=0)
    python_hours: int = Field(default=0, ge=0)
    ai_hours: int = Field(default=0, ge=0)
    grand_total_hours: int = Field(default=0, ge=0)


class EstimationAgentOutput(BaseModel):
    """
    Structured output from the Estimation Agent.
    Contains detailed effort estimations broken down by module, feature, and technology.
    """

    estimations: List[EstimationItem] = Field(
        default_factory=list,
        description="List of individual feature estimations."
    )

    totals: EstimationTotals = Field(
        default_factory=EstimationTotals,
        description="Aggregated hour totals across all features."
    )
