from __future__ import annotations

from vei.corpus.generator import generate_corpus
from vei.corpus.models import GeneratedWorkflowSpec
from vei.quality.filter import filter_workflow_corpus
from vei.scenario_engine.api import compile_workflow
from vei.scenario_runner.api import run_workflow


def test_generate_corpus_is_seed_deterministic() -> None:
    first = generate_corpus(seed=42, environment_count=2, scenarios_per_environment=3)
    second = generate_corpus(seed=42, environment_count=2, scenarios_per_environment=3)
    assert first.model_dump() == second.model_dump()
    assert len(first.environments) == 2
    assert len(first.workflows) == 6


def test_quality_filter_detects_duplicate_fingerprint() -> None:
    bundle = generate_corpus(seed=123, environment_count=1, scenarios_per_environment=2)
    duplicate = GeneratedWorkflowSpec(
        scenario_id="DUP-1",
        env_id=bundle.workflows[0].env_id,
        seed=999,
        spec=dict(bundle.workflows[0].spec),
    )
    report = filter_workflow_corpus([bundle.workflows[0], duplicate])
    assert len(report.accepted) == 1
    assert len(report.rejected) == 1
    assert "duplicate_fingerprint" in report.rejected[0].reasons


def test_generate_corpus_covers_enterprise_tooling(monkeypatch) -> None:
    monkeypatch.setenv("VEI_CRM_ALIAS_PACKS", "salesforce")
    bundle = generate_corpus(seed=77, environment_count=1, scenarios_per_environment=10)
    tools = {
        step.get("tool")
        for workflow in bundle.workflows
        for step in workflow.spec.get("steps", [])
        if isinstance(step, dict)
    }
    assert "slack.send_message" in tools
    assert "mail.compose" in tools
    assert "docs.search" in tools or "docs.create" in tools
    assert "calendar.create_event" in tools
    assert "tickets.create" in tools
    assert "db.query" in tools
    assert "db.upsert" in tools
    assert "salesforce.opportunity.create" in tools
    assert "servicedesk.list_requests" in tools
    assert "okta.assign_group" in tools
    assert "erp.create_po" in tools


def test_generated_workflows_are_runnable_without_random_faults() -> None:
    bundle = generate_corpus(seed=123, environment_count=1, scenarios_per_environment=7)
    for workflow in bundle.workflows:
        compiled = compile_workflow(workflow.spec, seed=workflow.seed)
        result = run_workflow(compiled, seed=workflow.seed, connector_mode="sim")
        assert result.ok, workflow.scenario_id
