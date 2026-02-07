from __future__ import annotations

from typing import Any, Dict, Protocol


class EventBusAPI(Protocol):
    """Typed interface for schedulers used by world replay/drift modules."""

    clock_ms: int

    def schedule(self, dt_ms: int, target: str, payload: Dict[str, Any]) -> None: ...


def get_catalog_scenario(name: str) -> Any:
    """Load a named built-in scenario from the catalog."""
    from vei.world.scenarios import get_scenario

    return get_scenario(name)
