from __future__ import annotations

from typing import Any, Protocol

from .compiler import CompiledWorkflow, compile_workflow_spec, load_workflow_spec
from .models import WorkflowScenarioSpec


class WorkflowCompilerAPI(Protocol):
    def __call__(self, spec: Any, seed: int = 42042) -> CompiledWorkflow: ...


def compile_workflow(spec: Any, seed: int = 42042) -> CompiledWorkflow:
    return compile_workflow_spec(spec, seed=seed)


def load_workflow(payload: Any) -> WorkflowScenarioSpec:
    return load_workflow_spec(payload)
