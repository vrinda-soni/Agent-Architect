
"""
task_schema.py
--------------
Pydantic models defining the structured output of the Task Identification Agent.
The agent extracts business information from a client meeting transcript.
"""
 
from pydantic import BaseModel, Field
from typing import List, Dict
 
 
class TaskAgentOutput(BaseModel):
    """
    Structured output from the Task Identification Agent.
    Contains all business-relevant information extracted from the transcript.
    """

    pain_points: List[str] = Field(
        default_factory=list,
        description="Client problems, frustrations, or inefficiencies mentioned in the transcript."
    )

    requirements: List[str] = Field(
        default_factory=list,
        description="Explicit functional and non-functional requirements extracted from the transcript."
    )

    constraints: List[str] = Field(
        default_factory=list,
        description="Limitations or restrictions such as budget, timeline, technology, or team size."
    )

    business_goals: List[str] = Field(
        default_factory=list,
        description="High-level business objectives the client wants to achieve with this project."
    )

    technology_context: Dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Technology-related context extracted from the transcript. "
            "Keys are categories (e.g., 'existing_infrastructure', 'preferred_cloud', "
            "'required_technologies', 'integrations', 'compliance_tools') and values are "
            "descriptions of what the client mentioned or currently uses."
        )
    )
