from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class WorkflowQualityScore(BaseModel):
    scenario_id: str
    fingerprint: str
    realism_score: float
    novelty_score: float
    runnability_score: float
    accepted: bool
    reasons: List[str] = Field(default_factory=list)


class QualityFilterReport(BaseModel):
    accepted: List[WorkflowQualityScore] = Field(default_factory=list)
    rejected: List[WorkflowQualityScore] = Field(default_factory=list)
