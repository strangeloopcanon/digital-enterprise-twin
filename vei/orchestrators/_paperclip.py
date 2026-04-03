from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .models import (
    OrchestratorActivityItem,
    OrchestratorAgent,
    OrchestratorBudgetSummary,
    OrchestratorCommandResult,
    OrchestratorConfig,
    OrchestratorSnapshot,
    OrchestratorSummary,
    OrchestratorSyncCapabilities,
    OrchestratorTask,
)

_SURFACE_ALIASES = {
    "chat": "slack",
    "email": "graph",
    "graph": "graph",
    "inbox": "graph",
    "issues": "jira",
    "jira": "jira",
    "mail": "graph",
    "outlook": "graph",
    "salesforce": "salesforce",
    "slack": "slack",
    "tickets": "jira",
    "crm": "salesforce",
}


class PaperclipOrchestratorClient:
    def __init__(
        self,
        config: OrchestratorConfig,
        *,
        timeout_s: float = 4.0,
    ) -> None:
        self.config = config
        self.timeout_s = timeout_s

    def fetch_snapshot(self) -> OrchestratorSnapshot:
        company_payload = self._safe_get(f"/api/companies/{self.config.company_id}")
        dashboard_payload = self._safe_get(
            f"/api/companies/{self.config.company_id}/dashboard"
        )
        agents_payload = self._safe_get(
            f"/api/companies/{self.config.company_id}/agents"
        )
        issues_payload = self._safe_get(
            f"/api/companies/{self.config.company_id}/issues"
        )
        activity_payload = self._safe_get(
            f"/api/companies/{self.config.company_id}/activity"
        )
        costs_summary_payload = self._safe_get(
            f"/api/companies/{self.config.company_id}/costs/summary"
        )
        costs_by_agent_payload = self._safe_get(
            f"/api/companies/{self.config.company_id}/costs/by-agent"
        )

        if all(
            payload is None
            for payload in (
                company_payload,
                dashboard_payload,
                agents_payload,
                issues_payload,
                activity_payload,
                costs_summary_payload,
                costs_by_agent_payload,
            )
        ):
            raise RuntimeError("paperclip API is not reachable right now")

        costs_by_agent = _coerce_records(
            costs_by_agent_payload,
            keys=("items", "agents", "costs"),
        )
        cost_index = {
            str(
                item.get("agentId") or item.get("agent_id") or item.get("id") or ""
            ): item
            for item in costs_by_agent
            if isinstance(item, Mapping)
        }

        agents = [
            _normalize_agent(
                item,
                cost_payload=cost_index.get(
                    str(item.get("id") or item.get("agentId") or "")
                ),
            )
            for item in _coerce_records(agents_payload, keys=("agents", "items"))
        ]
        agent_ids_by_external = _build_agent_ids_by_external(agents)

        tasks = [
            _normalize_task(item, agent_ids_by_external=agent_ids_by_external)
            for item in _coerce_records(issues_payload, keys=("issues", "items"))
        ]
        tasks = [item for item in tasks if item is not None]
        task_ids_by_agent: dict[str, list[str]] = {}
        for task in tasks:
            if task.assignee_agent_id is None:
                continue
            task_ids_by_agent.setdefault(task.assignee_agent_id, []).append(
                task.task_id
            )
        agents = [
            agent.model_copy(
                update={"task_ids": task_ids_by_agent.get(agent.agent_id, [])},
                deep=True,
            )
            for agent in agents
        ]

        recent_activity = [
            _normalize_activity(item, agent_ids_by_external=agent_ids_by_external)
            for item in _coerce_records(activity_payload, keys=("activity", "items"))
        ]
        recent_activity = [item for item in recent_activity if item is not None][:12]

        capabilities = self.sync_capabilities()
        budget = _normalize_budget(costs_summary_payload, company_payload)
        summary = _normalize_summary(
            company_payload=company_payload,
            dashboard_payload=dashboard_payload,
            budget=budget,
            agents=agents,
            task_count_payload=tasks,
        )
        return OrchestratorSnapshot(
            provider="paperclip",
            company_id=self.config.company_id,
            fetched_at=_iso_now(),
            summary=summary,
            budget=budget,
            capabilities=capabilities,
            agents=agents,
            tasks=tasks,
            recent_activity=recent_activity,
        )

    def pause_agent(self, agent_id: str) -> OrchestratorCommandResult:
        external_agent_id = external_agent_id_for(agent_id)
        self._request_json(f"/api/agents/{external_agent_id}/pause", method="POST")
        return OrchestratorCommandResult(
            provider="paperclip",
            agent_id=normalize_agent_id("paperclip", external_agent_id),
            external_agent_id=external_agent_id,
            action="pause",
            message="Paperclip agent paused.",
        )

    def resume_agent(self, agent_id: str) -> OrchestratorCommandResult:
        external_agent_id = external_agent_id_for(agent_id)
        self._request_json(f"/api/agents/{external_agent_id}/resume", method="POST")
        return OrchestratorCommandResult(
            provider="paperclip",
            agent_id=normalize_agent_id("paperclip", external_agent_id),
            external_agent_id=external_agent_id,
            action="resume",
            message="Paperclip agent resumed.",
        )

    def sync_capabilities(self) -> OrchestratorSyncCapabilities:
        return OrchestratorSyncCapabilities(
            can_pause_agents=True,
            can_resume_agents=True,
            routeable_surfaces=["slack", "jira", "graph", "salesforce"],
        )

    def _safe_get(self, path: str) -> dict[str, Any] | list[Any] | None:
        try:
            return self._request_json(path)
        except RuntimeError:
            return None

    def _request_json(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[Any]:
        base = self.config.base_url.rstrip("/")
        body = None
        headers = dict(self._headers())
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(f"{base}{path}", data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout_s) as response:  # nosec B310
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(
                f"paperclip request failed: {exc.code} {detail or exc.reason}"
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"paperclip request failed: {exc}") from exc
        if not raw.strip():
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("paperclip returned invalid JSON") from exc

    def _headers(self) -> dict[str, str]:
        api_key = os.environ.get(self.config.api_key_env, "").strip()
        if not api_key:
            return {}
        return {"Authorization": f"Bearer {api_key}"}


def normalize_agent_id(provider: str, external_agent_id: str) -> str:
    external = str(external_agent_id).strip()
    prefix = f"{provider}:"
    if external.startswith(prefix):
        return external
    return f"{prefix}{external}"


def normalize_task_id(provider: str, external_task_id: str) -> str:
    external = str(external_task_id).strip()
    prefix = f"{provider}:"
    if external.startswith(prefix):
        return external
    return f"{prefix}{external}"


def external_agent_id_for(agent_id: str) -> str:
    text = str(agent_id).strip()
    if ":" not in text:
        return text
    return text.split(":", 1)[1]


def _normalize_summary(
    *,
    company_payload: dict[str, Any] | list[Any] | None,
    dashboard_payload: dict[str, Any] | list[Any] | None,
    budget: OrchestratorBudgetSummary,
    agents: list[OrchestratorAgent],
    task_count_payload: list[Any],
) -> OrchestratorSummary:
    company = company_payload if isinstance(company_payload, Mapping) else {}
    dashboard = dashboard_payload if isinstance(dashboard_payload, Mapping) else {}
    agent_counts = _coerce_counts(
        dashboard,
        keys=(
            "agentCounts",
            "agent_counts",
            "agentsByStatus",
            "agent_counts_by_status",
        ),
    ) or _count_records([agent.status or "unknown" for agent in agents])
    task_counts = _coerce_counts(
        dashboard,
        keys=("taskCounts", "task_counts", "issuesByStatus", "issueCounts"),
    ) or _count_records(
        [
            str(item.status or "unknown")
            for item in task_count_payload
            if item is not None
        ]
    )
    stale_task_count = _first_int(
        dashboard.get("staleTaskCount"),
        dashboard.get("stale_task_count"),
        dashboard.get("staleTasks"),
        len(_coerce_records(dashboard.get("staleTasks"), keys=("items",))),
        default=0,
    )
    company_name = (
        _string(company.get("name"))
        or _string(dashboard.get("companyName"))
        or f"Paperclip company {company.get('id') or ''}".strip()
    )
    return OrchestratorSummary(
        provider="paperclip",
        company_id=_string(company.get("id")) or "",
        company_name=company_name or "Paperclip company",
        company_status=_string(company.get("status")),
        description=_string(company.get("description")),
        agent_counts=agent_counts,
        task_counts=task_counts,
        stale_task_count=stale_task_count,
    )


def _normalize_budget(
    costs_summary_payload: dict[str, Any] | list[Any] | None,
    company_payload: dict[str, Any] | list[Any] | None,
) -> OrchestratorBudgetSummary:
    payload = (
        costs_summary_payload if isinstance(costs_summary_payload, Mapping) else {}
    )
    company = company_payload if isinstance(company_payload, Mapping) else {}
    budget_cents = _first_int(
        payload.get("budgetMonthlyCents"),
        payload.get("monthlyBudgetCents"),
        company.get("budgetMonthlyCents"),
    )
    spend_cents = _first_int(
        payload.get("spentMonthlyCents"),
        payload.get("currentMonthSpendCents"),
        payload.get("monthlySpendCents"),
    )
    utilization_ratio = _first_float(
        payload.get("utilizationRatio"),
        payload.get("utilization"),
        payload.get("budgetUtilization"),
    )
    if utilization_ratio is None and budget_cents and spend_cents is not None:
        utilization_ratio = max(0.0, min(1.0, spend_cents / max(budget_cents, 1)))
    return OrchestratorBudgetSummary(
        monthly_budget_cents=budget_cents,
        monthly_spend_cents=spend_cents,
        utilization_ratio=utilization_ratio,
    )


def _normalize_agent(
    payload: Mapping[str, Any],
    *,
    cost_payload: Mapping[str, Any] | None,
) -> OrchestratorAgent:
    provider = _string(payload.get("provider")) or "paperclip"
    external_agent_id = _string(payload.get("id") or payload.get("agentId")) or ""
    hint_sources = [
        payload,
        _mapping(payload.get("metadata")),
        _mapping(payload.get("adapterConfig")),
        _mapping(_mapping(payload.get("metadata")).get("vei")),
        _mapping(_mapping(payload.get("adapterConfig")).get("vei")),
    ]
    integration_mode = _resolve_integration_mode(hint_sources)
    explicit_surfaces = _resolve_surfaces(hint_sources)
    capabilities = _normalize_surfaces(payload.get("capabilities"))
    allowed_surfaces = explicit_surfaces or capabilities
    policy_profile_id = _resolve_policy_profile(payload, hint_sources)
    spent_cents = _first_int(
        payload.get("spentMonthlyCents"),
        payload.get("spent_monthly_cents"),
        (cost_payload or {}).get("spentMonthlyCents"),
        (cost_payload or {}).get("costCents"),
    )
    budget_cents = _first_int(
        payload.get("budgetMonthlyCents"),
        payload.get("budget_monthly_cents"),
        (cost_payload or {}).get("budgetMonthlyCents"),
    )
    metadata = {
        "adapter_type": _string(payload.get("adapterType")),
        "capabilities": _string(payload.get("capabilities")),
    }
    metadata.update(
        {
            key: value
            for key, value in _mapping(payload.get("metadata")).items()
            if key not in {"vei"}
        }
    )
    return OrchestratorAgent(
        provider=provider,
        agent_id=normalize_agent_id(provider, external_agent_id),
        external_agent_id=external_agent_id,
        name=_string(payload.get("name")) or external_agent_id or "unknown-agent",
        role=_string(payload.get("role")),
        title=_string(payload.get("title")),
        team=_string(payload.get("team")),
        status=_string(payload.get("status")),
        reports_to=_string(payload.get("reportsTo")),
        integration_mode=integration_mode,
        allowed_surfaces=allowed_surfaces,
        policy_profile_id=policy_profile_id,
        monthly_budget_cents=budget_cents,
        monthly_spend_cents=spent_cents,
        metadata={
            key: value for key, value in metadata.items() if value not in {None, ""}
        },
    )


def _normalize_task(
    payload: Mapping[str, Any],
    *,
    agent_ids_by_external: Mapping[str, str],
) -> Any:
    provider = _string(payload.get("provider")) or "paperclip"
    external_task_id = _string(payload.get("id") or payload.get("issueId")) or ""
    if not external_task_id:
        return None
    assignee_payload = payload.get("assigneeAgentId") or payload.get("assigneeId")
    assignee = _string(assignee_payload)
    assignee_mapping = _mapping(payload.get("assignee"))
    if not assignee:
        assignee = _string(
            assignee_mapping.get("id") or assignee_mapping.get("agentId")
        )
    project = _mapping(payload.get("project"))
    goal = _mapping(payload.get("goal"))
    return OrchestratorTask(
        provider=provider,
        task_id=normalize_task_id(provider, external_task_id),
        external_task_id=external_task_id,
        title=_string(payload.get("title")) or external_task_id,
        status=_string(payload.get("status")),
        assignee_agent_id=_resolve_agent_id(
            provider,
            assignee,
            agent_ids_by_external=agent_ids_by_external,
            payload=assignee_mapping,
        ),
        priority=_string(payload.get("priority")),
        project_name=_string(project.get("name"))
        or _string(payload.get("projectName")),
        goal_name=_string(goal.get("name")) or _string(payload.get("goalName")),
        summary=_string(payload.get("description")) or _string(payload.get("summary")),
    )


def _normalize_activity(
    payload: Mapping[str, Any],
    *,
    agent_ids_by_external: Mapping[str, str],
) -> Any:
    provider = _string(payload.get("provider")) or "paperclip"
    actor = _mapping(payload.get("actor"))
    actor_id = _string(
        actor.get("id") or actor.get("agentId") or payload.get("agentId")
    )
    actor_name = _string(actor.get("name")) or _string(payload.get("actorName"))
    entity_type = _string(payload.get("entityType"))
    entity_id = _string(payload.get("entityId"))
    action = _string(payload.get("action"))
    label_parts = [
        part
        for part in (actor_name or actor_id, action, entity_type, entity_id)
        if part
    ]
    object_refs: list[str] = []
    if entity_type == "issue" and entity_id:
        object_refs.append(normalize_task_id(provider, entity_id))
    elif entity_type == "agent" and entity_id:
        object_refs.append(normalize_agent_id(provider, entity_id))
    run_id = _string(_mapping(payload.get("details")).get("runId"))
    if run_id:
        object_refs.append(f"run:{run_id}")
    return OrchestratorActivityItem(
        provider=provider,
        label=" ".join(label_parts) or "Paperclip activity",
        action=action,
        created_at=_string(payload.get("createdAt")),
        agent_id=_resolve_agent_id(
            provider,
            actor_id,
            agent_ids_by_external=agent_ids_by_external,
            payload=actor,
        ),
        agent_name=actor_name,
        task_id=(
            normalize_task_id(provider, entity_id)
            if entity_type == "issue" and entity_id
            else None
        ),
        status=_string(_mapping(payload.get("details")).get("status")),
        object_refs=object_refs,
        metadata={
            key: value
            for key, value in {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "details": (
                    _string(payload.get("details"))
                    if not isinstance(payload.get("details"), Mapping)
                    else None
                ),
            }.items()
            if value not in {None, ""}
        },
    )


def _resolve_integration_mode(
    payloads: list[Mapping[str, Any]],
) -> str:
    for payload in payloads:
        mode = _string(
            payload.get("integrationMode")
            or payload.get("integration_mode")
            or payload.get("veiIntegrationMode")
            or payload.get("vei_integration_mode")
            or payload.get("mode")
        ).lower()
        if mode in {"proxy", "ingest", "observe"}:
            return mode
    return "observe"


def _resolve_surfaces(payloads: list[Mapping[str, Any]]) -> list[str]:
    for payload in payloads:
        surfaces = _normalize_surfaces(
            payload.get("allowedSurfaces")
            or payload.get("allowed_surfaces")
            or payload.get("routeableSurfaces")
            or payload.get("supportedSurfaces")
            or payload.get("veiAllowedSurfaces")
            or payload.get("vei_allowed_surfaces")
        )
        if surfaces:
            return surfaces
    return []


def _resolve_policy_profile(
    payload: Mapping[str, Any],
    payloads: list[Mapping[str, Any]],
) -> str:
    for item in payloads:
        profile_id = _string(
            item.get("policyProfileId")
            or item.get("policy_profile_id")
            or item.get("veiPolicyProfileId")
            or item.get("vei_policy_profile_id")
        ).lower()
        if profile_id in {"observer", "operator", "approver", "admin"}:
            return profile_id
    text = " ".join(
        part
        for part in (
            _string(payload.get("role")),
            _string(payload.get("title")),
            _string(payload.get("capabilities")),
        )
        if part
    ).lower()
    if any(
        token in text
        for token in (
            "approver",
            "manager",
            "lead",
            "director",
            "chief",
            "head",
            "ceo",
            "cto",
        )
    ):
        return "approver"
    if text:
        return "operator"
    return "observer"


def _build_agent_ids_by_external(
    agents: list[OrchestratorAgent],
) -> dict[str, str]:
    counts: dict[str, int] = {}
    for agent in agents:
        external_agent_id = agent.external_agent_id.strip()
        if not external_agent_id:
            continue
        counts[external_agent_id] = counts.get(external_agent_id, 0) + 1

    resolved: dict[str, str] = {}
    for agent in agents:
        external_agent_id = agent.external_agent_id.strip()
        if not external_agent_id:
            continue
        if counts.get(external_agent_id, 0) != 1:
            continue
        resolved[external_agent_id] = agent.agent_id
    return resolved


def _resolve_agent_id(
    default_provider: str,
    external_agent_id: str,
    *,
    agent_ids_by_external: Mapping[str, str],
    payload: Mapping[str, Any] | None = None,
) -> str | None:
    external = _string(external_agent_id)
    if not external:
        return None
    resolved = agent_ids_by_external.get(external)
    if resolved:
        return resolved
    provider = _string(_mapping(payload).get("provider")) or default_provider
    return normalize_agent_id(provider, external)


def _coerce_records(
    payload: dict[str, Any] | list[Any] | None,
    *,
    keys: tuple[str, ...],
) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, Mapping)]
    if isinstance(payload, Mapping):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return [dict(item) for item in value if isinstance(item, Mapping)]
    return []


def _coerce_counts(
    payload: Mapping[str, Any],
    *,
    keys: tuple[str, ...],
) -> dict[str, int]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, Mapping):
            return {
                str(name): int(count or 0) for name, count in value.items() if str(name)
            }
    return {}


def _count_records(values: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[str(value)] = counts.get(str(value), 0) + 1
    return counts


def _normalize_surfaces(raw: Any) -> list[str]:
    values: list[str] = []
    if isinstance(raw, str):
        values = [part.strip() for part in raw.replace(",", "\n").splitlines()]
    elif isinstance(raw, list):
        values = [str(item).strip() for item in raw if str(item).strip()]
    normalized: list[str] = []
    for value in values:
        token = _SURFACE_ALIASES.get(value.strip().lower(), value.strip().lower())
        if token and token not in normalized:
            normalized.append(token)
    return normalized


def _first_int(*values: Any, default: int | None = None) -> int | None:
    for value in values:
        if value is None:
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            text = value.strip()
            if not text:
                continue
            try:
                return int(float(text))
            except ValueError:
                continue
    return default


def _first_float(*values: Any) -> float | None:
    for value in values:
        if value is None:
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            text = value.strip().rstrip("%")
            if not text:
                continue
            try:
                numeric = float(text)
            except ValueError:
                continue
            if "%" in value:
                return numeric / 100.0
            return numeric
    return None


def _string(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text


def _mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {}


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()
