from __future__ import annotations

from vei.scenario_engine.api import compile_workflow
from vei.scenario_runner.api import run_workflow, validate_workflow


def _workflow_spec() -> dict:
    return {
        "name": "workflow-runner-test",
        "objective": {
            "statement": "Request quote and post approval",
            "success": ["mail sent", "approval posted"],
        },
        "world": {"catalog": "multi_channel"},
        "actors": [
            {"actor_id": "agent", "role": "procurement_operator"},
            {"actor_id": "approver", "role": "finance_manager"},
        ],
        "constraints": [
            {
                "name": "budget",
                "description": "budget must be included",
                "required": True,
            }
        ],
        "approvals": [{"stage": "finance", "approver": "approver", "required": True}],
        "steps": [
            {
                "step_id": "read",
                "description": "Read browser",
                "tool": "browser.read",
                "args": {},
            },
            {
                "step_id": "mail",
                "description": "Send quote email",
                "tool": "mail.compose",
                "args": {
                    "to": "sales@macrocompute.example",
                    "subj": "Quote request",
                    "body_text": "Please share quote and ETA.",
                },
                "expect": [{"kind": "result_contains", "field": "id", "contains": "m"}],
            },
            {
                "step_id": "approve",
                "description": "Post approval message",
                "tool": "slack.send_message",
                "args": {
                    "channel": "#procurement",
                    "text": "Please approve budget $2400 with quote evidence.",
                },
                "expect": [{"kind": "result_contains", "field": "ts", "contains": ""}],
            },
        ],
        "success_assertions": [
            {"kind": "pending_max", "field": "total", "max_value": 20}
        ],
        "tags": ["unit-test"],
    }


def test_compile_and_run_workflow_success() -> None:
    compiled = compile_workflow(_workflow_spec(), seed=99)
    result = run_workflow(compiled, seed=99, connector_mode="sim")

    assert result.static_validation.ok
    assert result.dynamic_validation.ok
    assert result.ok
    assert len(result.steps) == 3
    assert all(step.ok for step in result.steps)


def test_validate_workflow_flags_unknown_tool() -> None:
    spec = _workflow_spec()
    spec["steps"][1]["tool"] = "mail.unknown_operation"
    compiled = compile_workflow(spec, seed=1)
    report = validate_workflow(
        compiled, available_tools=["browser.read", "mail.compose"]
    )
    assert not report.ok
    assert any(issue.code == "tool.unavailable" for issue in report.issues)


def test_run_workflow_enforces_success_assertions() -> None:
    spec = _workflow_spec()
    spec["success_assertions"] = [
        {"kind": "pending_max", "field": "total", "max_value": -1}
    ]
    compiled = compile_workflow(spec, seed=88)
    result = run_workflow(compiled, seed=88, connector_mode="sim")

    assert not result.ok
    assert any(
        issue.code == "success_assertion.failed"
        for issue in result.dynamic_validation.issues
    )


def test_run_workflow_supports_salesforce_alias_and_db_steps(
    monkeypatch,
) -> None:
    monkeypatch.setenv("VEI_CRM_ALIAS_PACKS", "salesforce")
    spec = {
        "name": "workflow-salesforce-db",
        "objective": {
            "statement": "Create opportunity and verify db audit records.",
            "success": ["opportunity created", "db queried"],
        },
        "world": {"catalog": "multi_channel"},
        "actors": [{"actor_id": "agent", "role": "procurement_operator"}],
        "steps": [
            {
                "step_id": "create_opp",
                "description": "Create Salesforce opportunity",
                "tool": "salesforce.opportunity.create",
                "args": {"name": "Renewal FY27", "amount": 100000},
                "expect": [
                    {"kind": "result_contains", "field": "id", "contains": "D-"}
                ],
            },
            {
                "step_id": "query_db",
                "description": "Query approval audit table",
                "tool": "db.query",
                "args": {"table": "approval_audit", "limit": 5},
                "expect": [
                    {
                        "kind": "result_contains",
                        "field": "table",
                        "contains": "approval_audit",
                    }
                ],
            },
        ],
        "success_assertions": [
            {"kind": "pending_max", "field": "total", "max_value": 20}
        ],
    }
    compiled = compile_workflow(spec, seed=99)
    result = run_workflow(compiled, seed=99, connector_mode="sim")
    assert result.ok
    assert all(step.ok for step in result.steps)
