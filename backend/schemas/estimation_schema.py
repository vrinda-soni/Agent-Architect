"""
estimation_schema.py
--------------------
Pydantic models for the Estimation Agent WBS output.
One effort_hours column per task (not per-tech breakdown).
"""

from pydantic import BaseModel, Field
from typing import List


class EstimationItem(BaseModel):
    id: int = Field(default=0)
    phase: str = Field(default="Phase 1 (MVP)")
    module: str = Field(...)
    feature: str = Field(...)
    role: str = Field(default="")
    effort_hours: int = Field(default=0, ge=0)
    duration_days: float = Field(default=0.0, ge=0)
    dependencies: str = Field(default="—")
    complexity: str = Field(...)
    confidence: str = Field(default="High")
    risk_notes: str = Field(default="")
    tech_remarks: str = Field(default="")
    ba_remarks: str = Field(default="")


class EstimationTotals(BaseModel):
    total_hours: int = Field(default=0, ge=0)
    phase1_hours: int = Field(default=0, ge=0)
    phase2_hours: int = Field(default=0, ge=0)


class EstimationAgentOutput(BaseModel):
    estimations: List[EstimationItem] = Field(default_factory=list)
    totals: EstimationTotals = Field(default_factory=EstimationTotals)
