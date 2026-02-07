from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .scenario import Scenario
from .scenarios import get_scenario, list_scenarios


class ScenarioManifest(BaseModel):
    """Typed summary of a built-in scenario pack entry."""

    name: str
    scenario_type: str = "core"
    difficulty: str = "standard"
    expected_steps_min: int | None = None
    expected_steps_max: int | None = None
    tool_families: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    docs_count: int = 0
    tickets_count: int = 0
    identity_users_count: int = 0
    servicedesk_incidents_count: int = 0
    servicedesk_requests_count: int = 0


def _expected_steps_range(raw: Any) -> tuple[int | None, int | None]:
    if isinstance(raw, list) and len(raw) == 2:
        lo = raw[0]
        hi = raw[1]
        if isinstance(lo, int) and isinstance(hi, int):
            return lo, hi
    return None, None


def _infer_tool_families(scenario: Scenario) -> list[str]:
    families: set[str] = set()
    if scenario.slack_initial_message:
        families.add("slack")
    if scenario.vendor_reply_variants:
        families.add("mail")
    if scenario.browser_nodes:
        families.add("browser")
    if scenario.documents:
        families.add("docs")
    if scenario.calendar_events:
        families.add("calendar")
    if scenario.tickets:
        families.add("tickets")
    if scenario.database_tables:
        families.add("db")
    if (
        scenario.identity_users
        or scenario.identity_groups
        or scenario.identity_applications
    ):
        families.add("okta")
    if scenario.service_incidents or scenario.service_requests:
        families.add("servicedesk")
    return sorted(families)


def build_scenario_manifest(name: str, scenario: Scenario) -> ScenarioManifest:
    metadata = scenario.metadata or {}
    expected_min, expected_max = _expected_steps_range(metadata.get("expected_steps"))

    raw_tags = metadata.get("tags", [])
    tags: list[str]
    if isinstance(raw_tags, list):
        tags = [str(tag) for tag in raw_tags if isinstance(tag, str)]
    else:
        tags = []

    return ScenarioManifest(
        name=name,
        scenario_type=str(metadata.get("scenario_type", "core")),
        difficulty=str(metadata.get("difficulty", "standard")),
        expected_steps_min=expected_min,
        expected_steps_max=expected_max,
        tool_families=_infer_tool_families(scenario),
        tags=sorted(set(tags)),
        docs_count=len(scenario.documents or {}),
        tickets_count=len(scenario.tickets or {}),
        identity_users_count=len(scenario.identity_users or {}),
        servicedesk_incidents_count=len(scenario.service_incidents or {}),
        servicedesk_requests_count=len(scenario.service_requests or {}),
    )


def get_scenario_manifest(name: str) -> ScenarioManifest:
    scenario = get_scenario(name)
    return build_scenario_manifest(name.strip().lower(), scenario)


def list_scenario_manifest() -> list[ScenarioManifest]:
    manifests = [
        build_scenario_manifest(name, scenario)
        for name, scenario in list_scenarios().items()
    ]
    manifests.sort(key=lambda item: item.name)
    return manifests
