from __future__ import annotations

from vei.behavior.memory import MemoryStore
from vei.behavior.tree import BehaviorContext, WaitFor


class _Obs:
    def __init__(self, summary: str = "Mail: INBOX empty") -> None:
        self._summary = summary

    def model_dump(self) -> dict:
        return {
            "summary": self._summary,
            "pending_events": {"mail": 0, "slack": 0},
        }


class _RouterStub:
    def call_and_step(self, tool: str, args: dict) -> dict:
        return {}

    def observe(self, focus_hint: str | None = None) -> _Obs:
        return _Obs()


def test_waitfor_returns_failure_when_predicate_not_met() -> None:
    ctx = BehaviorContext(router=_RouterStub(), memory=MemoryStore(), transcript=[])
    node = WaitFor(lambda _ctx: False, max_ticks=2, focus="mail")
    assert node.tick(ctx) == "failure"
    wait_entries = [item for item in ctx.transcript if item.get("wait_complete")]
    assert wait_entries and wait_entries[-1]["met"] is False
