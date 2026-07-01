from pydantic import BaseModel, Field, field_validator
from typing import List, Dict, Any


class EstimationTask(BaseModel):
    no: str = Field(default="")
    task: str = Field(default="")
    sub_tasks: List[str] = Field(default_factory=list)
    features: str = Field(default="")
    interface_type: str = Field(default="")
    stack_involvement: Dict[str, Any] = Field(default_factory=dict)
    estimated_hours: int = Field(default=0)
    complexity: str = Field(default="Medium")
    is_mvp: bool = Field(default=True)
    tech_remarks: str = Field(default="")
    ba_remarks: str = Field(default="")

    @field_validator("no", mode="before")
    @classmethod
    def coerce_no_to_str(cls, v):
        return str(v) if v is not None else ""

    @field_validator("sub_tasks", mode="before")
    @classmethod
    def coerce_sub_tasks(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [v] if v.strip() else []
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        return []

    @field_validator("stack_involvement", mode="before")
    @classmethod
    def coerce_involvement_values(cls, v):
        if not isinstance(v, dict):
            return {}
        # coerce any truthy/falsy value to bool
        return {k: bool(val) for k, val in v.items()}


class EstimationModule(BaseModel):
    no: str = Field(default="")
    module: str = Field(default="")
    scope: str = Field(default="")
    tasks: List[EstimationTask] = Field(default_factory=list)


class EstimationFunctionality(BaseModel):
    letter: str = Field(default="")
    name: str = Field(default="")
    modules: List[EstimationModule] = Field(default_factory=list)


class EstimationAgentOutput(BaseModel):
    stack_columns: List[str] = Field(default_factory=list)
    functionalities: List[EstimationFunctionality] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
