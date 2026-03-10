from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


BenchmarkRunner = Literal["scripted", "bc", "llm"]


class BenchmarkCaseSpec(BaseModel):
    runner: BenchmarkRunner
    scenario_name: str
    seed: int = 42042
    artifacts_dir: Path
    branch: Optional[str] = None
    dataset_path: Optional[Path] = None
    replay_mode: Optional[Literal["overlay", "strict"]] = None
    score_mode: Literal["email", "full"] = "full"
    frontier: bool = False
    model: Optional[str] = None
    provider: Optional[str] = None
    bc_model_path: Optional[Path] = None
    task: Optional[str] = None
    max_steps: int = 12
    tool_top_k: int = 0
    step_timeout_s: int = 180
    episode_timeout_s: int = 900
    use_llm_judge: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BenchmarkFamilyManifest(BaseModel):
    name: str
    title: str
    description: str
    scenario_names: List[str] = Field(default_factory=list)
    primary_dimensions: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)


class BenchmarkMetrics(BaseModel):
    elapsed_ms: int = 0
    actions: int = 0
    time_ms: int = 0
    latency_p95_ms: int = 0
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: Optional[float] = None


class BenchmarkDiagnostics(BaseModel):
    branch: str = "main"
    benchmark_family: Optional[str] = None
    snapshot_count: int = 0
    initial_snapshot_id: Optional[int] = None
    final_snapshot_id: Optional[int] = None
    latest_snapshot_label: Optional[str] = None
    replay_mode: Optional[str] = None
    replay_scheduled: int = 0
    pending_events: int = 0
    actor_modes: Dict[str, str] = Field(default_factory=dict)
    actor_status: Dict[str, str] = Field(default_factory=dict)
    receipt_count: int = 0
    connector_receipt_count: int = 0
    state_head: Optional[int] = None
    policy_warning_count: int = 0
    policy_error_count: int = 0
    scenario_metadata: Dict[str, Any] = Field(default_factory=dict)


class BenchmarkCaseResult(BaseModel):
    spec: BenchmarkCaseSpec
    status: Literal["ok", "error"] = "ok"
    success: bool = False
    score: Dict[str, Any] = Field(default_factory=dict)
    raw_score: Dict[str, Any] = Field(default_factory=dict)
    metrics: BenchmarkMetrics = Field(default_factory=BenchmarkMetrics)
    diagnostics: BenchmarkDiagnostics = Field(default_factory=BenchmarkDiagnostics)
    error: Optional[str] = None


class BenchmarkBatchSummary(BaseModel):
    total_runs: int = 0
    success_count: int = 0
    success_rate: float = 0.0
    average_composite_score: float = 0.0
    total_actions: int = 0
    total_time_ms: int = 0
    p95_latency_ms: int = 0
    llm_calls: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: Optional[float] = None


class BenchmarkBatchResult(BaseModel):
    run_id: str
    results: List[BenchmarkCaseResult] = Field(default_factory=list)
    summary: BenchmarkBatchSummary = Field(default_factory=BenchmarkBatchSummary)
