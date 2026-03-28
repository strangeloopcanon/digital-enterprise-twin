from __future__ import annotations

import pytest

from vei.corpus.generator import generate_corpus
from vei.corpus.models import GeneratedWorkflowSpec
from vei.quality import filter as quality_filter
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


def test_quality_filter_helpers_cover_thresholds_and_alias_services(
    monkeypatch,
) -> None:
    realistic_spec = {
        "objective": {"statement": "Recover the environment."},
        "steps": [
            {"tool": "browser.open"},
            {"tool": "mail.compose"},
            {"tool": "slack.send_message"},
            {"tool": "tickets.create"},
            {"tool": "db.query"},
            {"tool": "salesforce.opportunity.create"},
            {"tool": "xero.create_purchase_order"},
            {"tool": "okta.assign_group"},
            {"tool": "servicedesk.list_requests"},
        ],
        "approvals": [{"stage": "manager"}],
        "constraints": [{"name": "audit"}],
        "metadata": {"scenario_seed": 42, "keep": "yes"},
    }
    lean_spec = {
        "objective": {"statement": "Check the basics."},
        "steps": [
            {"tool": "browser.open"},
            {"tool": "mail.compose"},
            {"tool": "slack.send_message"},
        ],
    }

    assert quality_filter.realism_score(realistic_spec) == 1.0
    assert quality_filter.realism_score(lean_spec) == pytest.approx(0.75)
    assert quality_filter._tool_service({"tool": "salesforce.account.list"}) == "crm"
    assert quality_filter._tool_service({"tool": "xero.create_invoice"}) == "erp"
    assert quality_filter._tool_service({"tool": "not-a-tool"}) == ""
    assert quality_filter._structure_key({"steps": "not-a-list"}) == "none"
    assert quality_filter._normalized_spec(realistic_spec)["metadata"] == {
        "keep": "yes"
    }

    monkeypatch.setattr(
        quality_filter,
        "compile_workflow_spec",
        lambda spec: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert quality_filter.runnability_score(realistic_spec) == 0.0


def test_quality_filter_rejects_low_realism_failed_runs_and_repeated_structures(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        quality_filter,
        "runnability_score",
        lambda spec: 0.0 if spec.get("mode") == "broken" else 1.0,
    )

    workflows = [
        GeneratedWorkflowSpec(
            scenario_id=f"scenario-{index}",
            env_id="env-1",
            seed=index,
            spec={
                "mode": "broken" if index == 0 else "ok",
                "objective": (
                    {}
                    if index == 0
                    else {"statement": f"Handle request {index} safely."}
                ),
                "steps": [
                    {"tool": "browser.open"},
                    {"tool": "mail.compose"},
                    {"tool": "slack.send_message"},
                ],
                "metadata": {"scenario_seed": index, "nonce": index},
            },
        )
        for index in range(6)
    ]

    report = filter_workflow_corpus(workflows, realism_threshold=0.56)

    assert "realism_below_threshold:0.550" in report.rejected[0].reasons
    assert "static_runnability_failed" in report.rejected[0].reasons
    assert any(
        "low_structural_novelty:0.167" in item.reasons for item in report.rejected
    )
    assert report.accepted
