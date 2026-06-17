from pydantic import BaseModel, Field, ConfigDict
from typing import List, Dict, Optional, Any


class EstimationRow(BaseModel):
    model_config = ConfigDict(extra="allow")

    owner_hours: Dict[str, float] = Field(default_factory=dict)
    tech_remarks: str = Field(default="")
    ba_remarks: str = Field(default="")


class EstimationTotals(BaseModel):
    total_hours: float = Field(default=0, ge=0)
    owner_breakdown: Dict[str, float] = Field(default_factory=dict)


class EstimationAgentOutput(BaseModel):
    structural_columns: List[str] = Field(default_factory=list)
    owner_columns: List[str] = Field(default_factory=list)
    estimations: List[EstimationRow] = Field(default_factory=list)
    totals: EstimationTotals = Field(default_factory=EstimationTotals)
