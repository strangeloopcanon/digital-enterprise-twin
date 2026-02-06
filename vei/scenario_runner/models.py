from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ValidationIssue(BaseModel):
    code: str
    message: str
    step_id: Optional[str] = None
    severity: str = "error"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ValidationReport(BaseModel):
    ok: bool
    issues: List[ValidationIssue] = Field(default_factory=list)


class StepExecution(BaseModel):
    step_id: str
    tool: str
    ok: bool
    result: Any = None
    observation: Dict[str, Any] = Field(default_factory=dict)
    assertion_failures: List[str] = Field(default_factory=list)
    time_ms: int = 0


class ScenarioRunResult(BaseModel):
    ok: bool
    workflow_name: str
    static_validation: ValidationReport
    dynamic_validation: ValidationReport
    steps: List[StepExecution] = Field(default_factory=list)
    artifacts_dir: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
