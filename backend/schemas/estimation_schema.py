from pydantic import BaseModel, Field, ConfigDict
from typing import List, Dict, Optional, Any


class EstimationItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    tech_hours: Dict[str, int] = Field(default_factory=dict)
    tech_remarks: str = Field(default="")
    ba_remarks: str = Field(default="")
    phase: Optional[str] = Field(default=None)


class EstimationTotals(BaseModel):
    total_hours: int = Field(default=0, ge=0)
    tech_breakdown: Dict[str, int] = Field(default_factory=dict)
    phase1_hours: Optional[int] = Field(default=None)
    phase2_hours: Optional[int] = Field(default=None)


class EstimationAgentOutput(BaseModel):
    structural_columns: List[str] = Field(default_factory=list)
    tech_stack_columns: List[str] = Field(default_factory=list)
    estimations: List[EstimationItem] = Field(default_factory=list)
    totals: EstimationTotals = Field(default_factory=EstimationTotals)
