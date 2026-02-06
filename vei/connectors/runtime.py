from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from .adapters import build_default_adapter_triplets
from .api import AdapterTriplet, TOOL_ROUTES, PolicyGate
from .models import (
    AdapterMode,
    ConnectorInvocationError,
    ConnectorReceipt,
    ConnectorRequest,
    ConnectorResult,
    PolicyDecisionAction,
    ServiceName,
)
from .policy import DefaultPolicyGate
from .redaction import redact_mapping


class ConnectorRuntime:
    """Runtime dispatcher for typed connector adapters."""

    def __init__(
        self,
        *,
        mode: AdapterMode,
        adapters: Dict[ServiceName, AdapterTriplet],
        policy_gate: Optional[PolicyGate] = None,
        receipts_path: Optional[Path] = None,
    ) -> None:
        self.mode = mode
        self.adapters = adapters
        self.policy_gate = policy_gate or DefaultPolicyGate.from_env()
        self._receipts_path = receipts_path
        self._request_seq = 0
        self._receipts: list[ConnectorReceipt] = []

    def managed_tool(self, tool: str) -> bool:
        route = TOOL_ROUTES.get(tool)
        return bool(route and route.service in self.adapters)

    def last_receipt(self) -> Optional[Dict[str, Any]]:
        if not self._receipts:
            return None
        return self._receipts[-1].model_dump()

    def invoke_tool(
        self,
        tool: str,
        args: Dict[str, Any],
        *,
        actor: str = "agent",
        time_ms: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Any:
        route = TOOL_ROUTES.get(tool)
        if not route:
            raise ConnectorInvocationError(
                "unknown_tool",
                f"Unsupported connector tool: {tool}",
                status_code=404,
            )

        adapter_group = self.adapters.get(route.service)
        if not adapter_group:
            raise ConnectorInvocationError(
                "service_unavailable",
                f"No adapter registered for service: {route.service.value}",
                status_code=503,
            )

        request = ConnectorRequest(
            request_id=self._next_request_id(route.service),
            service=route.service,
            operation=route.operation,
            operation_class=route.operation_class,
            payload=dict(args or {}),
            actor=actor,
            metadata=dict(metadata or {}),
        )

        decision = self.policy_gate.evaluate(request, self.mode)
        if decision.action == PolicyDecisionAction.DENY:
            self._record_receipt(
                request=request,
                policy_action=decision.action,
                result=None,
                time_ms=time_ms,
                metadata={"policy_reason": decision.reason},
            )
            raise ConnectorInvocationError(
                "policy.denied",
                decision.reason or "operation denied by policy gate",
                status_code=403,
                detail={"tool": tool},
            )
        if decision.action == PolicyDecisionAction.REQUIRE_APPROVAL:
            self._record_receipt(
                request=request,
                policy_action=decision.action,
                result=None,
                time_ms=time_ms,
                metadata={"policy_reason": decision.reason},
            )
            raise ConnectorInvocationError(
                "policy.approval_required",
                decision.reason or "operation requires human approval",
                status_code=403,
                detail={"tool": tool},
            )

        adapter = adapter_group.for_mode(self.mode)
        result = adapter.execute(request)
        self._record_receipt(
            request=request,
            policy_action=decision.action,
            result=result,
            time_ms=time_ms,
            metadata={"policy_reason": decision.reason},
        )
        if not result.ok:
            err = result.error
            raise ConnectorInvocationError(
                err.code if err else "connector.failed",
                err.message if err else "adapter call failed",
                status_code=result.status_code or 400,
                detail=err.detail if err else {"tool": tool},
            )
        return result.data

    def _next_request_id(self, service: ServiceName) -> str:
        self._request_seq += 1
        return f"{service.value}-{self._request_seq:06d}"

    def _record_receipt(
        self,
        *,
        request: ConnectorRequest,
        policy_action: PolicyDecisionAction,
        result: Optional[ConnectorResult],
        time_ms: int,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        receipt = ConnectorReceipt(
            request_id=request.request_id,
            mode=self.mode,
            service=request.service,
            operation=request.operation,
            operation_class=request.operation_class,
            policy_action=policy_action,
            ok=True if result is None else bool(result.ok),
            status_code=200 if result is None else int(result.status_code),
            request_payload=redact_mapping(request.payload),
            response_payload=redact_mapping(
                result.raw if result is not None else {"policy": str(policy_action)}
            ),
            latency_ms=0 if result is None else int(result.latency_ms),
            time_ms=int(time_ms),
            metadata=dict(metadata or {}),
        )
        self._receipts.append(receipt)
        if len(self._receipts) > 200:
            self._receipts = self._receipts[-200:]
        self._flush_receipt(receipt)

    def _flush_receipt(self, receipt: ConnectorReceipt) -> None:
        if not self._receipts_path:
            return
        self._receipts_path.parent.mkdir(parents=True, exist_ok=True)
        with self._receipts_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(receipt.model_dump(), sort_keys=True) + "\n")


def create_default_runtime(
    *,
    mode: AdapterMode,
    slack: Any,
    mail: Any,
    calendar: Any,
    docs: Any,
    tickets: Any,
    database: Any,
    erp: Optional[Any] = None,
    crm: Optional[Any] = None,
    okta: Optional[Any] = None,
    servicedesk: Optional[Any] = None,
    receipts_path: Optional[Path] = None,
) -> ConnectorRuntime:
    return ConnectorRuntime(
        mode=mode,
        adapters=build_default_adapter_triplets(
            slack=slack,
            mail=mail,
            calendar=calendar,
            docs=docs,
            tickets=tickets,
            database=database,
            erp=erp,
            crm=crm,
            okta=okta,
            servicedesk=servicedesk,
        ),
        policy_gate=DefaultPolicyGate.from_env(),
        receipts_path=receipts_path,
    )
