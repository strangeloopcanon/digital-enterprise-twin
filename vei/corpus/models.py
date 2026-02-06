from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field


class EnterpriseProfile(BaseModel):
    org_id: str
    org_name: str
    primary_domain: str
    departments: List[str] = Field(default_factory=list)
    budget_cap_usd: int = 3000


class GeneratedEnvironment(BaseModel):
    env_id: str
    seed: int
    profile: EnterpriseProfile
    world_template: Dict[str, Any] = Field(default_factory=dict)


class GeneratedWorkflowSpec(BaseModel):
    scenario_id: str
    env_id: str
    seed: int
    spec: Dict[str, Any] = Field(default_factory=dict)


class CorpusBundle(BaseModel):
    seed: int
    environments: List[GeneratedEnvironment] = Field(default_factory=list)
    workflows: List[GeneratedWorkflowSpec] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
