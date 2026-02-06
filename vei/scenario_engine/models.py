from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class ActorSpec(BaseModel):
    actor_id: str
    role: str
    email: Optional[str] = None
    slack: Optional[str] = None


class ConstraintSpec(BaseModel):
    name: str
    description: str
    required: bool = True


class ApprovalSpec(BaseModel):
    stage: str
    approver: str
    required: bool = True
    evidence: Optional[str] = None


class AssertionSpec(BaseModel):
    kind: Literal[
        "result_contains",
        "result_equals",
        "observation_contains",
        "pending_max",
    ]
    field: Optional[str] = None
    contains: Optional[str] = None
    equals: Optional[str] = None
    focus: Optional[str] = None
    max_value: Optional[int] = None
    description: Optional[str] = None


class WorkflowStepSpec(BaseModel):
    step_id: str
    description: str
    tool: str
    args: Dict[str, Any] = Field(default_factory=dict)
    expect: List[AssertionSpec] = Field(default_factory=list)
    on_failure: str = "fail"


class FailurePathSpec(BaseModel):
    name: str
    trigger_step: str
    recovery_steps: List[str] = Field(default_factory=list)
    notes: Optional[str] = None


class ObjectiveSpec(BaseModel):
    statement: str
    success: List[str] = Field(default_factory=list)


class WorkflowScenarioSpec(BaseModel):
    name: str
    objective: ObjectiveSpec
    world: Dict[str, Any] = Field(default_factory=dict)
    actors: List[ActorSpec] = Field(default_factory=list)
    constraints: List[ConstraintSpec] = Field(default_factory=list)
    approvals: List[ApprovalSpec] = Field(default_factory=list)
    steps: List[WorkflowStepSpec] = Field(default_factory=list)
    success_assertions: List[AssertionSpec] = Field(default_factory=list)
    failure_paths: List[FailurePathSpec] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_unique_steps(self) -> "WorkflowScenarioSpec":
        seen: set[str] = set()
        for step in self.steps:
            if step.step_id in seen:
                raise ValueError(f"duplicate step_id: {step.step_id}")
            seen.add(step.step_id)
        return self
