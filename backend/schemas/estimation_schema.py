"""
estimation_schema.py
--------------------
Pydantic models defining the structured output of the Estimation Agent.
Tech-hour columns are DYNAMIC — determined by the project's actual tech stack.
"""

from pydantic import BaseModel, Field
from typing import List, Dict


class EstimationItem(BaseModel):
    """
    A single feature estimation item with dynamic technology hours.
    """
    functionality_type: str = Field(
        default="",
        description="High-level functionality category (e.g., 'Project Setup', 'Authentication', 'AI Engine')."
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

    tech_hours: Dict[str, int] = Field(
        default_factory=dict,
        description=(
            "Dynamic technology hours mapping. Keys are technology/category names "
            "(e.g., 'Frontend', 'Backend', 'Database', 'Cloud', 'AI/ML', 'DevOps') "
            "and values are estimated hours. Only include technologies relevant to THIS feature."
        )
    )

    tech_remarks: str = Field(
        default="",
        description="Technical assumptions, implementation notes, or concerns from a tech lead perspective."
    )

    ba_remarks: str = Field(
        default="",
        description="Business analyst remarks — typically left empty for initial estimation."
    )


class EstimationTotals(BaseModel):
    """
    Aggregated totals across all estimation items, keyed by technology category.
    """
    tech_totals: Dict[str, int] = Field(
        default_factory=dict,
        description="Aggregated hours per technology category across all features."
    )

    grand_total_hours: int = Field(
        default=0,
        ge=0,
        description="Total hours across all technologies and features."
    )


class EstimationAgentOutput(BaseModel):
    """
    Structured output from the Estimation Agent.
    Contains detailed effort estimations broken down by module, feature, and dynamic technology columns.
    """

    tech_categories: List[str] = Field(
        default_factory=list,
        description=(
            "Ordered list of technology category names used as columns "
            "(e.g., ['Frontend', 'Backend', 'Database', 'Cloud', 'AI/ML', 'DevOps']). "
            "These define the column order in the estimation table."
        )
    )

    estimations: List[EstimationItem] = Field(
        default_factory=list,
        description="List of individual feature estimations."
    )

    totals: EstimationTotals = Field(
        default_factory=EstimationTotals,
        description="Aggregated hour totals across all features."
    )
