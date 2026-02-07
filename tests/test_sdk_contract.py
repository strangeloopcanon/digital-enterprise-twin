from __future__ import annotations

from typing import Any, Dict, Sequence

from vei.router.tool_providers import PrefixToolProvider
from vei.router.tool_registry import ToolSpec
from vei.sdk import (
    create_session,
    filter_enterprise_corpus,
    generate_enterprise_corpus,
    run_workflow_spec,
    validate_workflow_spec,
)


class _EchoProvider(PrefixToolProvider):
    def __init__(self) -> None:
        super().__init__(name="echo_provider", prefixes=("ext.",))

    def specs(self) -> Sequence[ToolSpec]:
        return (
            ToolSpec(
                name="ext.echo",
                description="Echo payload for SDK contract tests.",
                returns="object",
            ),
        )

    def call(self, tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if tool == "ext.echo":
            return {"ok": True, "payload": dict(args)}
        raise RuntimeError(f"unsupported tool for _EchoProvider: {tool}")


def _workflow_spec() -> Dict[str, Any]:
    return {
        "name": "sdk-contract-workflow",
        "objective": {
            "statement": "Read browser context and post approval note.",
            "success": ["context read", "approval posted"],
        },
        "world": {"catalog": "multi_channel"},
        "steps": [
            {
                "step_id": "read",
                "description": "Read browser state",
                "tool": "browser.read",
                "args": {},
            },
            {
                "step_id": "approve",
                "description": "Post approval in procurement channel",
                "tool": "slack.send_message",
                "args": {
                    "channel": "#procurement",
                    "text": "Approval request for budget $2400 with quote attached.",
                },
                "expect": [
                    {"kind": "result_contains", "field": "ts", "contains": ""},
                ],
            },
        ],
        "success_assertions": [
            {"kind": "pending_max", "field": "total", "max_value": 20}
        ],
    }


def test_sdk_session_supports_observe_and_tool_calls() -> None:
    session = create_session(seed=42042, scenario_name="multi_channel")
    observation = session.observe()
    assert isinstance(observation.get("action_menu"), list)

    browser = session.call_tool("browser.read", {})
    assert "url" in browser
    assert "title" in browser


def test_sdk_session_supports_custom_tool_provider_registration() -> None:
    session = create_session(seed=42042, scenario_name="multi_channel")
    session.register_tool_provider(_EchoProvider())

    result = session.call_tool("ext.echo", {"message": "hello"})
    assert result["ok"] is True
    assert result["payload"]["message"] == "hello"


def test_sdk_workflow_helpers_compile_validate_and_run() -> None:
    spec = _workflow_spec()
    validation = validate_workflow_spec(spec, seed=7)
    assert validation.ok

    result = run_workflow_spec(spec, seed=7, connector_mode="sim")
    assert result.ok
    assert result.static_validation.ok
    assert result.dynamic_validation.ok
    assert len(result.steps) == 2


def test_sdk_validate_reports_unknown_tool() -> None:
    spec = _workflow_spec()
    spec["steps"][1]["tool"] = "unknown.tool"
    report = validate_workflow_spec(
        spec,
        seed=7,
        available_tools=["browser.read", "slack.send_message"],
    )
    assert not report.ok
    assert any(issue.code == "tool.unavailable" for issue in report.issues)


def test_sdk_corpus_helpers_generate_and_filter() -> None:
    bundle = generate_enterprise_corpus(
        seed=42042,
        environment_count=2,
        scenarios_per_environment=3,
    )
    report = filter_enterprise_corpus(bundle, realism_threshold=0.0)

    assert len(bundle.workflows) == 6
    assert len(report.accepted) + len(report.rejected) == len(bundle.workflows)
