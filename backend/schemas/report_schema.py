"""
report_schema.py
----------------
Pydantic models defining the structured output of the Report Agent.
"""

from pydantic import BaseModel, Field
from typing import List, Dict, Any


class ReportSection(BaseModel):
    title: str = Field(..., description="Section title.")
    content: str = Field(..., description="Section body content in markdown/plain text.")


class ReportAgentOutput(BaseModel):
    """
    Structured output from the Report Agent.
    Contains a comprehensive project report compiled from all previous agent outputs.
    """

    executive_summary: str = Field(
        ...,
        description="High-level executive summary of the project, objectives, and recommendations."
    )

    requirements_summary: str = Field(
        ...,
        description="Summary of extracted pain points, requirements, constraints, and business goals."
    )

    architecture_overview: str = Field(
        ...,
        description="Overview of the proposed architecture, tech stack, and design rationale."
    )

    feasibility_assessment: str = Field(
        ...,
        description="Summary of feasibility findings, risks, and mitigation strategies."
    )

    effort_estimation_summary: str = Field(
        ...,
        description="Summary of development effort estimation with totals and key highlights."
    )

    recommendations: List[str] = Field(
        default_factory=list,
        description="Actionable recommendations for next steps, team structure, and timeline."
    )

    sections: List[ReportSection] = Field(
        default_factory=list,
        description="Additional detailed report sections."
    )

    raw_data: Dict[str, Any] = Field(
        default_factory=dict,
        description="Raw aggregated data from all agents for export purposes."
    )
