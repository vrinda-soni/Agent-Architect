"""
report_schema.py
----------------
Pydantic models for the 12-section consulting report produced by the Report Agent.
"""

from pydantic import BaseModel, Field
from typing import List, Dict, Any


class ProblemNeedRow(BaseModel):
    problem_need: str = ""
    business_impact: str = ""


class FunctionalRequirementRow(BaseModel):
    id: str = ""
    requirement: str = ""


class NonFunctionalRequirementRow(BaseModel):
    category: str = ""
    requirement: str = ""


class FeatureModuleRow(BaseModel):
    module: str = ""
    feature_functionality: str = ""
    technologies_used: str = ""


class FeasibilityRow(BaseModel):
    metric: str = ""
    value: str = ""
    reason: str = ""


class RiskRow(BaseModel):
    risk: str = ""
    impact: str = ""
    mitigation_strategy: str = ""


class ReportAgentOutput(BaseModel):
    """
    12-section consulting report compiled from all approved agent outputs.
    """

    # Section 1
    executive_summary: str = Field(..., description="2-3 paragraph executive summary for C-level stakeholders.")

    # Section 2
    background_summary: str = Field(..., description="Client's current situation, business context, and existing process.")

    # Section 3
    problem_need_analysis: List[ProblemNeedRow] = Field(
        default_factory=list, description="Business problems and their impact."
    )

    # Section 4 — Requirements Analysis
    functional_requirements: List[FunctionalRequirementRow] = Field(
        default_factory=list, description="Functional requirements with sequential IDs."
    )
    non_functional_requirements: List[NonFunctionalRequirementRow] = Field(
        default_factory=list, description="Non-functional requirements by category."
    )
    constraints: List[str] = Field(default_factory=list)
    business_goals: List[str] = Field(default_factory=list)
    technology_context: List[str] = Field(
        default_factory=list, description='Each entry formatted as "Category: Value".'
    )

    # Section 5
    assumptions: List[str] = Field(default_factory=list)

    # Section 6
    feature_module_breakdown: List[FeatureModuleRow] = Field(
        default_factory=list, description="Module and feature breakdown with technologies used."
    )

    # Section 8
    feasibility_table: List[FeasibilityRow] = Field(
        default_factory=list, description="Feasibility metrics: Complexity, Architecture Confidence, Feasibility Confidence."
    )

    # Section 9
    risk_assessment: List[RiskRow] = Field(
        default_factory=list, description="Project-specific risks with impact and mitigation."
    )

    # Section 10
    recommendations_next_steps: str = Field(
        ..., description="Immediate next steps, MVP recommendations, and future enhancements."
    )

    # Section 11
    architecture_summary: str = Field(
        ..., description="Business-friendly paragraph explaining why the architecture was selected."
    )

    # Sections 7 & 12 (architecture diagram) come from raw_data["plan"]["mermaid_diagram"]
    raw_data: Dict[str, Any] = Field(default_factory=dict)
