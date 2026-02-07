from __future__ import annotations

from typing import Any, Dict, Optional, Protocol, Sequence

from vei.world.scenario import Scenario


class ObservationLike(Protocol):
    def model_dump(self) -> Dict[str, Any]: ...


class RouterToolSpecLike(Protocol):
    name: str
    description: str


class RouterToolProvider(Protocol):
    def specs(self) -> Sequence[RouterToolSpecLike]: ...

    def handles(self, tool: str) -> bool: ...

    def call(self, tool: str, args: Dict[str, Any]) -> Any: ...


class RouterAPI(Protocol):
    bus: Any
    trace: Any

    def observe(self, focus_hint: Optional[str] = None) -> ObservationLike: ...

    def call_and_step(self, tool: str, args: Dict[str, Any]) -> Dict[str, Any]: ...

    def act_and_observe(self, tool: str, args: Dict[str, Any]) -> Dict[str, Any]: ...

    def pending(self) -> Dict[str, int]: ...

    def register_tool_provider(self, provider: RouterToolProvider) -> None: ...


def create_router(
    *,
    seed: int,
    artifacts_dir: Optional[str] = None,
    scenario: Optional[Scenario] = None,
    connector_mode: Optional[str] = None,
) -> RouterAPI:
    """Factory for the router runtime exposed as a typed module API."""
    from .core import Router

    return Router(
        seed=seed,
        artifacts_dir=artifacts_dir,
        scenario=scenario,
        connector_mode=connector_mode,
    )
