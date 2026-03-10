from __future__ import annotations

from typing import Any, Iterable, List

from vei.scenario_engine.compiler import CompiledWorkflow
from vei.scenario_engine.models import WorkflowScenarioSpec

from .assertions import evaluate_assertion_specs, infer_assertion_source
from .models import (
    ContractEvaluationResult,
    ContractPredicateSpec,
    ContractSpec,
    ContractValidationIssue,
    ContractValidationReport,
    InterventionRuleSpec,
    ObservationBoundarySpec,
    PolicyInvariantSpec,
    RewardTermSpec,
)

_FORBIDDEN_ASSERTION_KINDS = {
    "result_not_contains",
    "observation_not_contains",
    "state_not_contains",
    "state_count_max",
    "pending_max",
    "time_max_ms",
}


def build_contract_from_workflow(
    workflow: CompiledWorkflow | WorkflowScenarioSpec,
) -> ContractSpec:
    spec = workflow.spec if isinstance(workflow, CompiledWorkflow) else workflow
    scenario_name = None
    if isinstance(spec.world, dict) and spec.world.get("catalog") is not None:
        scenario_name = str(spec.world.get("catalog"))

    success_predicates: List[ContractPredicateSpec] = []
    forbidden_predicates: List[ContractPredicateSpec] = []
    for index, assertion in enumerate(spec.success_assertions, start=1):
        predicate = ContractPredicateSpec(
            name=f"predicate_{index}",
            source=infer_assertion_source(assertion),
            assertion=assertion,
            description=assertion.description,
        )
        if assertion.kind in _FORBIDDEN_ASSERTION_KINDS:
            forbidden_predicates.append(predicate)
        else:
            success_predicates.append(predicate)

    focus_hints = sorted(
        {
            assertion.focus or "summary"
            for assertion in spec.success_assertions
            if assertion.kind.startswith("observation_")
        }
    )
    allowed_tools = sorted({step.tool for step in spec.steps})
    hidden_state_fields = sorted(
        {
            assertion.field or ""
            for assertion in spec.success_assertions
            if infer_assertion_source(assertion) == "oracle_state" and assertion.field
        }
    )
    observation_boundary = ObservationBoundarySpec(
        allowed_tools=allowed_tools,
        focus_hints=focus_hints or ["summary"],
        hidden_state_fields=hidden_state_fields,
        description="Agent-visible observations remain bounded to declared focuses.",
    )

    policy_invariants = [
        PolicyInvariantSpec(
            name=constraint.name,
            description=constraint.description,
            required=constraint.required,
        )
        for constraint in spec.constraints
    ]
    policy_invariants.extend(
        PolicyInvariantSpec(
            name=f"approval:{approval.stage}",
            description=f"Approval required from {approval.approver} at {approval.stage}",
            required=approval.required,
            evidence=approval.evidence,
        )
        for approval in spec.approvals
    )

    intervention_rules: List[InterventionRuleSpec] = [
        InterventionRuleSpec(
            name=f"approval:{approval.stage}",
            trigger=f"approval:{approval.stage}",
            action="request_approval",
            actor=approval.approver,
            required=approval.required,
            evidence=approval.evidence,
        )
        for approval in spec.approvals
    ]
    intervention_rules.extend(
        InterventionRuleSpec(
            name=path.name,
            trigger=path.trigger_step,
            action=" -> ".join(path.recovery_steps) if path.recovery_steps else "fail",
            actor=None,
            required=True,
            evidence=path.notes,
        )
        for path in spec.failure_paths
    )

    reward_terms: List[RewardTermSpec] = []
    if success_predicates:
        weight = round(1.0 / len(success_predicates), 3)
        reward_terms.extend(
            RewardTermSpec(
                name=predicate.name,
                weight=weight,
                term_type="success",
                description=predicate.description,
            )
            for predicate in success_predicates
        )
    if forbidden_predicates:
        penalty = round(1.0 / len(forbidden_predicates), 3)
        reward_terms.extend(
            RewardTermSpec(
                name=predicate.name,
                weight=penalty,
                term_type="penalty",
                description=predicate.description,
            )
            for predicate in forbidden_predicates
        )

    metadata = dict(spec.metadata or {})
    metadata.update(
        {
            "workflow_tags": list(spec.tags),
            "objective": spec.objective.statement,
            "success_outcomes": list(spec.objective.success),
        }
    )

    return ContractSpec(
        name=f"{spec.name}.contract",
        workflow_name=spec.name,
        scenario_name=scenario_name,
        success_predicates=success_predicates,
        forbidden_predicates=forbidden_predicates,
        observation_boundary=observation_boundary,
        policy_invariants=policy_invariants,
        reward_terms=reward_terms,
        intervention_rules=intervention_rules,
        metadata=metadata,
    )


def evaluate_contract(
    contract: ContractSpec,
    *,
    oracle_state: dict[str, Any],
    visible_observation: dict[str, Any] | None = None,
    result: object | None = None,
    pending: dict[str, int] | None = None,
    time_ms: int = 0,
    available_tools: Iterable[str] | None = None,
    validation_mode: str = "state",
) -> ContractEvaluationResult:
    visible_observation = visible_observation or {}
    pending = pending or {}
    tool_set = set(available_tools or [])
    static_issues: List[ContractValidationIssue] = []
    for tool in contract.observation_boundary.allowed_tools:
        if tool_set and tool not in tool_set:
            static_issues.append(
                ContractValidationIssue(
                    code="tool.unavailable",
                    message=f"Contract requires unavailable tool: {tool}",
                    source="visible_observation",
                    metadata={"tool": tool},
                )
            )

    dynamic_issues: List[ContractValidationIssue] = []
    success_failures = _evaluate_predicates(
        predicates=contract.success_predicates,
        oracle_state=oracle_state,
        visible_observation=visible_observation,
        result=result,
        pending=pending,
        time_ms=time_ms,
        code="success_predicate.failed",
    )
    forbidden_failures = _evaluate_predicates(
        predicates=contract.forbidden_predicates,
        oracle_state=oracle_state,
        visible_observation=visible_observation,
        result=result,
        pending=pending,
        time_ms=time_ms,
        code="forbidden_predicate.violated",
    )
    dynamic_issues.extend(success_failures)
    dynamic_issues.extend(forbidden_failures)

    static_report = ContractValidationReport(
        ok=not any(issue.severity == "error" for issue in static_issues),
        issues=static_issues,
    )
    dynamic_report = ContractValidationReport(
        ok=not any(issue.severity == "error" for issue in dynamic_issues),
        issues=dynamic_issues,
    )
    return ContractEvaluationResult(
        ok=static_report.ok and dynamic_report.ok,
        contract_name=contract.name,
        workflow_name=contract.workflow_name,
        static_validation=static_report,
        dynamic_validation=dynamic_report,
        success_predicate_count=len(contract.success_predicates),
        success_predicates_passed=max(
            0, len(contract.success_predicates) - len(success_failures)
        ),
        success_predicates_failed=len(success_failures),
        forbidden_predicate_count=len(contract.forbidden_predicates),
        forbidden_predicates_failed=len(forbidden_failures),
        policy_invariant_count=len(contract.policy_invariants),
        policy_invariants_failed=0,
        metadata={
            "validation_mode": validation_mode,
            "scenario_name": contract.scenario_name,
            "observation_boundary": contract.observation_boundary.model_dump(
                mode="json"
            ),
            "reward_terms": [
                item.model_dump(mode="json") for item in contract.reward_terms
            ],
        },
    )


def _evaluate_predicates(
    *,
    predicates: List[ContractPredicateSpec],
    oracle_state: dict[str, Any],
    visible_observation: dict[str, Any],
    result: object | None,
    pending: dict[str, int],
    time_ms: int,
    code: str,
) -> List[ContractValidationIssue]:
    issues: List[ContractValidationIssue] = []
    for predicate in predicates:
        failures = evaluate_assertion_specs(
            assertions=[predicate.assertion],
            result=result or {},
            observation=visible_observation,
            pending=pending,
            oracle_state=oracle_state,
            time_ms=time_ms,
        )
        for message in failures:
            issues.append(
                ContractValidationIssue(
                    code=code,
                    message=message,
                    predicate_name=predicate.name,
                    source=predicate.source,
                )
            )
    return issues
