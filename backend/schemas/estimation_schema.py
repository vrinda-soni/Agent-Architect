from pydantic import BaseModel, Field, field_validator
from typing import List, Dict, Any


class EstimationItem(BaseModel):
    no: str = Field(default="")
    functionality: str = Field(default="")
    module: str = Field(default="")
    features: str = Field(default="")
    interface_type: str = Field(default="")
    stack_involvement: Dict[str, Any] = Field(default_factory=dict)
    tech_remarks: str = Field(default="")
    ba_remarks: str = Field(default="")

    @field_validator("no", mode="before")
    @classmethod
    def coerce_no_to_str(cls, v):
        return str(v) if v is not None else ""

    @field_validator("stack_involvement", mode="before")
    @classmethod
    def coerce_involvement_values(cls, v):
        if not isinstance(v, dict):
            return {}
        # coerce any truthy/falsy value to bool
        return {k: bool(val) for k, val in v.items()}


class FunctionalityGroup(BaseModel):
    letter: str = Field(default="")
    name: str = Field(default="")


class EstimationAgentOutput(BaseModel):
    functionalities: List[FunctionalityGroup] = Field(default_factory=list)
    stack_columns: List[str] = Field(default_factory=list)
    items: List[EstimationItem] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
