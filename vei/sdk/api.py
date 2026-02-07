from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Protocol

from vei.corpus.api import CorpusBundle, GeneratedWorkflowSpec, generate_corpus
from vei.quality.api import QualityFilterReport, filter_workflow_corpus
from vei.router.api import RouterAPI, RouterToolProvider, create_router
from vei.scenario_engine.api import compile_workflow
from vei.scenario_engine.compiler import CompiledWorkflow
from vei.scenario_runner.api import run_workflow, validate_workflow
from vei.scenario_runner.models import ScenarioRunResult, ValidationReport
from vei.world.api import (
    get_catalog_scenario,
    get_catalog_scenario_manifest,
    list_catalog_scenario_manifest,
)
from vei.world.manifest import ScenarioManifest


@dataclass(frozen=True)
class SessionConfig:
    seed: int = 42042
    artifacts_dir: str | None = None
    connector_mode: str = "sim"
    scenario_name: str = "multi_channel"
    scenario: Any | None = None


class SessionHook(Protocol):
    """Optional callback hooks for SDK embedding telemetry and control."""

    def before_call(self, tool: str, args: Dict[str, Any]) -> None: ...

    def after_call(
        self, tool: str, args: Dict[str, Any], result: Dict[str, Any]
    ) -> None: ...


class EnterpriseSession:
    """Stable high-level embedding API for VEI office simulations."""

    def __init__(self, config: SessionConfig):
        self.config = config
        scenario_obj = config.scenario
        if scenario_obj is None and config.scenario_name:
            scenario_obj = get_catalog_scenario(config.scenario_name)
        self._router: RouterAPI = create_router(
            seed=config.seed,
            artifacts_dir=config.artifacts_dir,
            scenario=scenario_obj,
            connector_mode=config.connector_mode,
        )
        self._hooks: list[SessionHook] = []

    @property
    def router(self) -> RouterAPI:
        return self._router

    def observe(self, focus_hint: str | None = None) -> Dict[str, Any]:
        return self._router.observe(focus_hint=focus_hint).model_dump()

    def call_tool(
        self, tool: str, args: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        payload = dict(args or {})
        self._run_before_hooks(tool, payload)
        result = self._router.call_and_step(tool, payload)
        self._run_after_hooks(tool, payload, result)
        return result

    def act_and_observe(
        self, tool: str, args: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        payload = dict(args or {})
        self._run_before_hooks(tool, payload)
        result = self._router.act_and_observe(tool, payload)
        self._run_after_hooks(tool, payload, result)
        return result

    def pending(self) -> Dict[str, int]:
        return self._router.pending()

    def register_tool_provider(self, provider: RouterToolProvider) -> None:
        self._router.register_tool_provider(provider)

    def register_hook(self, hook: SessionHook) -> None:
        self._hooks.append(hook)

    def _run_before_hooks(self, tool: str, args: Dict[str, Any]) -> None:
        for hook in self._hooks:
            hook.before_call(tool, dict(args))

    def _run_after_hooks(
        self, tool: str, args: Dict[str, Any], result: Dict[str, Any]
    ) -> None:
        for hook in self._hooks:
            hook.after_call(tool, dict(args), dict(result))


def create_session(
    *,
    seed: int = 42042,
    artifacts_dir: str | None = None,
    connector_mode: str = "sim",
    scenario_name: str = "multi_channel",
    scenario: Any | None = None,
) -> EnterpriseSession:
    return EnterpriseSession(
        SessionConfig(
            seed=seed,
            artifacts_dir=artifacts_dir,
            connector_mode=connector_mode,
            scenario_name=scenario_name,
            scenario=scenario,
        )
    )


def compile_workflow_spec(spec: Any, *, seed: int = 42042) -> CompiledWorkflow:
    return compile_workflow(spec, seed=seed)


def validate_workflow_spec(
    spec: Any,
    *,
    seed: int = 42042,
    available_tools: Iterable[str] | None = None,
) -> ValidationReport:
    workflow = compile_workflow(spec, seed=seed)
    return validate_workflow(workflow, available_tools=available_tools)


def run_workflow_spec(
    spec: Any,
    *,
    seed: int = 42042,
    artifacts_dir: str | None = None,
    connector_mode: str = "sim",
) -> ScenarioRunResult:
    workflow = compile_workflow(spec, seed=seed)
    return run_workflow(
        workflow,
        seed=seed,
        artifacts_dir=artifacts_dir,
        connector_mode=connector_mode,
    )


def generate_enterprise_corpus(
    *,
    seed: int = 42042,
    environment_count: int = 10,
    scenarios_per_environment: int = 10,
) -> CorpusBundle:
    return generate_corpus(
        seed=seed,
        environment_count=environment_count,
        scenarios_per_environment=scenarios_per_environment,
    )


def filter_enterprise_corpus(
    bundle: CorpusBundle,
    *,
    realism_threshold: float = 0.55,
) -> QualityFilterReport:
    workflows: list[GeneratedWorkflowSpec] = [
        GeneratedWorkflowSpec.model_validate(workflow.model_dump())
        for workflow in bundle.workflows
    ]
    return filter_workflow_corpus(workflows, realism_threshold=realism_threshold)


def get_scenario_manifest(name: str) -> ScenarioManifest:
    return get_catalog_scenario_manifest(name)


def list_scenario_manifest() -> list[ScenarioManifest]:
    return list_catalog_scenario_manifest()
