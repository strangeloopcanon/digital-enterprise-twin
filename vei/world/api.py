from __future__ import annotations

from typing import Any, Dict, Protocol

from .manifest import ScenarioManifest, get_scenario_manifest, list_scenario_manifest


class EventBusAPI(Protocol):
    """Typed interface for schedulers used by world replay/drift modules."""

    clock_ms: int

    def schedule(self, dt_ms: int, target: str, payload: Dict[str, Any]) -> None: ...


def get_catalog_scenario(name: str) -> Any:
    """Load a named built-in scenario from the catalog."""
    from vei.world.scenarios import get_scenario

    return get_scenario(name)


def get_catalog_scenario_manifest(name: str) -> ScenarioManifest:
    """Load metadata manifest for a named built-in scenario."""
    return get_scenario_manifest(name)


def list_catalog_scenario_manifest() -> list[ScenarioManifest]:
    """List metadata manifests for all built-in scenarios."""
    return list_scenario_manifest()
