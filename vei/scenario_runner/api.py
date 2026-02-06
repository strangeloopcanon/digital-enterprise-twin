from __future__ import annotations

from typing import Iterable, Protocol

from vei.scenario_engine.compiler import CompiledWorkflow

from .models import ScenarioRunResult, ValidationReport
from .runner import run_compiled_workflow
from .validator import static_validate_workflow


class WorkflowRunnerAPI(Protocol):
    def __call__(
        self,
        workflow: CompiledWorkflow,
        *,
        seed: int = 42042,
        artifacts_dir: str | None = None,
        connector_mode: str = "sim",
    ) -> ScenarioRunResult: ...


def run_workflow(
    workflow: CompiledWorkflow,
    *,
    seed: int = 42042,
    artifacts_dir: str | None = None,
    connector_mode: str = "sim",
) -> ScenarioRunResult:
    return run_compiled_workflow(
        workflow,
        seed=seed,
        artifacts_dir=artifacts_dir,
        connector_mode=connector_mode,
    )


def validate_workflow(
    workflow: CompiledWorkflow, *, available_tools: Iterable[str] | None = None
) -> ValidationReport:
    return static_validate_workflow(workflow, available_tools=available_tools)
