from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Protocol

from vei.data.models import BaseEvent


class EventBusLike(Protocol):
    clock_ms: int

    def schedule(
        self,
        *,
        dt_ms: int,
        target: str,
        payload: Dict[str, Any],
        actor_id: str | None = None,
        source: str = "system",
        kind: str = "scheduled",
    ) -> str: ...


def materialize_overlay_event(
    raw: BaseEvent | Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    payload = raw.model_dump() if hasattr(raw, "model_dump") else dict(raw)
    channel = str(payload.get("channel", "")).strip()
    if not channel:
        return None

    raw_payload = payload.get("payload", {})
    event_payload = raw_payload if isinstance(raw_payload, dict) else {}
    event_type = str(payload.get("type", "")).strip()

    if channel == "tool":
        args = event_payload.get("args", {})
        if not isinstance(args, dict):
            args = {}
        tool_name = event_type or str(event_payload.get("tool", "")).strip()
        if not tool_name:
            return None
        return {
            "time_ms": int(payload.get("time_ms", 0)),
            "target": "tool",
            "payload": {"tool": tool_name, "args": args},
            "actor_id": payload.get("actor_id"),
            "source": "dataset_replay",
        }

    delivered = event_payload.get("payload", event_payload)
    if not isinstance(delivered, dict):
        delivered = {}
    return {
        "time_ms": int(payload.get("time_ms", 0)),
        "target": channel,
        "payload": delivered,
        "actor_id": payload.get("actor_id"),
        "source": "dataset_replay",
    }


class ReplayAdapter:
    def __init__(self, bus: EventBusLike, events: Iterable[BaseEvent]) -> None:
        self.bus = bus
        self.events = sorted(events, key=lambda e: e.time_ms)
        self._index = 0

    def prime(self) -> None:
        for event in self.events:
            scheduled = materialize_overlay_event(event)
            if scheduled is None:
                continue
            dt = max(0, int(scheduled.get("time_ms", 0)) - self.bus.clock_ms)
            self.bus.schedule(
                dt_ms=dt,
                target=str(scheduled["target"]),
                payload=dict(scheduled.get("payload", {})),
                actor_id=scheduled.get("actor_id"),
                source=str(scheduled.get("source", "dataset_replay")),
                kind="scheduled",
            )
