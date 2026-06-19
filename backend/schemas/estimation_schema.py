from pydantic import BaseModel, Field, ConfigDict
from typing import List


class WBSRow(BaseModel):
    model_config = ConfigDict(extra="allow")

    owners: List[str] = Field(default_factory=list)
    tech_remarks: str = Field(default="")
    ba_remarks: str = Field(default="")


class EstimationAgentOutput(BaseModel):
    structural_columns: List[str] = Field(default_factory=list)
    owner_columns: List[str] = Field(default_factory=list)
    work_breakdown: List[WBSRow] = Field(default_factory=list)
