from __future__ import annotations

from types import SimpleNamespace

from vei.contract import assertions as contract_assertions
from vei.scenario_engine.models import AssertionSpec


def test_contract_assertions_cover_sources_and_success_paths() -> None:
    assert (
        contract_assertions.infer_assertion_source(
            AssertionSpec(kind="result_contains", field="message", contains="ok")
        )
        == "tool_result"
    )
    assert (
        contract_assertions.infer_assertion_source(
            AssertionSpec(kind="observation_contains", contains="visible")
        )
        == "visible_observation"
    )
    assert (
        contract_assertions.infer_assertion_source(
            AssertionSpec(kind="state_equals", field="state.value", equals="ok")
        )
        == "oracle_state"
    )
    assert (
        contract_assertions.infer_assertion_source(
            AssertionSpec(kind="pending_max", max_value=1)
        )
        == "pending"
    )
    assert (
        contract_assertions.infer_assertion_source(
            AssertionSpec(kind="time_max_ms", max_value=1)
        )
        == "time"
    )
    assert (
        contract_assertions.infer_assertion_source(SimpleNamespace(kind="custom_kind"))
        == "oracle_state"
    )

    failures = contract_assertions.evaluate_assertion_specs(
        assertions=[
            AssertionSpec(kind="result_contains", field="message", contains="done"),
            AssertionSpec(kind="result_equals", field="items.0.name", equals="alpha"),
            AssertionSpec(
                kind="observation_contains", focus="summary", contains="ready"
            ),
            AssertionSpec(kind="pending_max", field="total", max_value=2),
            AssertionSpec(kind="state_contains", field="crm.owner", contains="ops"),
            AssertionSpec(kind="state_count_equals", field="items", equals=2),
            AssertionSpec(kind="state_count_max", field="items", max_value=2),
            AssertionSpec(kind="state_exists", field="crm.owner"),
            AssertionSpec(kind="time_max_ms", max_value=200),
        ],
        result={"message": "done", "items": [{"name": "alpha"}]},
        observation={"summary": "system ready"},
        pending={"total": 1},
        oracle_state={"crm": {"owner": "ops@example.com"}, "items": [1, 2]},
        time_ms=100,
    )

    assert failures == []
    assert (
        contract_assertions._resolve_field(
            {"items": [{"name": "alpha"}]}, "items.0.name"
        )
        == "alpha"
    )
    assert contract_assertions._resolve_field({"items": []}, "items.bad") is None
    assert contract_assertions._resolve_field("not-a-container", "field") is None
    assert contract_assertions._resolve_count({"a": 1, "b": 2}) == 2
    assert contract_assertions._resolve_count(None) is None


def test_contract_assertions_cover_failure_messages_and_unknown_kinds() -> None:
    result = {"message": "approved", "items": [{"name": "alpha"}]}
    observation = {"summary": "visible but not hidden"}
    pending = {"total": "many"}
    oracle_state = {"state": {"items": [1, 2, 3], "secret": "hidden"}}

    assert (
        contract_assertions._assertion_failure(
            assertion=AssertionSpec(
                kind="result_not_contains", field="message", contains="approved"
            ),
            result=result,
            observation=observation,
            pending=pending,
            oracle_state=oracle_state,
            time_ms=10,
        )
        == "expected result field 'message' to not contain 'approved'"
    )
    assert (
        contract_assertions._assertion_failure(
            assertion=AssertionSpec(
                kind="result_equals", field="message", equals="denied"
            ),
            result=result,
            observation=observation,
            pending=pending,
            oracle_state=oracle_state,
            time_ms=10,
        )
        == "expected result field 'message' == 'denied', got 'approved'"
    )
    assert (
        contract_assertions._assertion_failure(
            assertion=AssertionSpec(kind="observation_contains", contains="absent"),
            result=result,
            observation=observation,
            pending=pending,
            oracle_state=oracle_state,
            time_ms=10,
        )
        == "expected observation 'summary' to contain 'absent'"
    )
    assert (
        contract_assertions._assertion_failure(
            assertion=AssertionSpec(
                kind="observation_not_contains", contains="visible"
            ),
            result=result,
            observation=observation,
            pending=pending,
            oracle_state=oracle_state,
            time_ms=10,
        )
        == "expected observation 'summary' to not contain 'visible'"
    )
    assert (
        contract_assertions._assertion_failure(
            assertion=AssertionSpec(kind="pending_max", field="total", max_value=1),
            result=result,
            observation=observation,
            pending=pending,
            oracle_state=oracle_state,
            time_ms=10,
        )
        == "pending field 'total' is not numeric: many"
    )
    assert (
        contract_assertions._assertion_failure(
            assertion=AssertionSpec(
                kind="state_not_contains", field="state.secret", contains="hidden"
            ),
            result=result,
            observation=observation,
            pending={"total": 1},
            oracle_state=oracle_state,
            time_ms=10,
        )
        == "expected state field 'state.secret' to not contain 'hidden'"
    )
    assert (
        contract_assertions._assertion_failure(
            assertion=AssertionSpec(
                kind="state_equals", field="state.secret", equals="open"
            ),
            result=result,
            observation=observation,
            pending={"total": 1},
            oracle_state=oracle_state,
            time_ms=10,
        )
        == "expected state field 'state.secret' == 'open', got 'hidden'"
    )
    assert (
        contract_assertions._assertion_failure(
            assertion=AssertionSpec(kind="state_exists", field="state.missing"),
            result=result,
            observation=observation,
            pending={"total": 1},
            oracle_state=oracle_state,
            time_ms=10,
        )
        == "expected state field 'state.missing' to exist"
    )
    assert (
        contract_assertions._assertion_failure(
            assertion=AssertionSpec(
                kind="state_count_equals", field="state.secret", equals=1
            ),
            result=result,
            observation=observation,
            pending={"total": 1},
            oracle_state=oracle_state,
            time_ms=10,
        )
        == "expected state field 'state.secret' count == 1, got 6"
    )
    assert (
        contract_assertions._assertion_failure(
            assertion=AssertionSpec(
                kind="state_count_max", field="state.items", max_value=2
            ),
            result=result,
            observation=observation,
            pending={"total": 1},
            oracle_state=oracle_state,
            time_ms=10,
        )
        == "expected state field 'state.items' count <= 2, got 3"
    )
    assert (
        contract_assertions._assertion_failure(
            assertion=AssertionSpec(kind="time_max_ms", max_value=5),
            result=result,
            observation=observation,
            pending={"total": 1},
            oracle_state=oracle_state,
            time_ms=10,
        )
        == "expected workflow time <= 5 ms, got 10 ms"
    )

    unknown = SimpleNamespace(
        kind="unexpected", field="missing", contains=None, equals=None
    )
    assert (
        contract_assertions._assertion_failure(
            assertion=unknown,
            result=result,
            observation=observation,
            pending={"total": 1},
            oracle_state=oracle_state,
            time_ms=10,
        )
        == "unknown assertion kind: unexpected"
    )
    assert contract_assertions._resolve_count(object()) is None
