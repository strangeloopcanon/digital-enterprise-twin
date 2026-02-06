from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Set

from .api import PolicyGate
from .models import (
    AdapterMode,
    ConnectorRequest,
    OperationClass,
    PolicyDecision,
    PolicyDecisionAction,
)


def _parse_bool(raw: str | None, default: bool = False) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _parse_blocked_operations(raw: str | None) -> Set[str]:
    if not raw:
        return set()
    return {item.strip() for item in raw.split(",") if item.strip()}


@dataclass
class DefaultPolicyGate(PolicyGate):
    """Default write safety gate for connector operations."""

    live_allow_write_safe: bool = False
    live_allow_write_risky: bool = False
    blocked_operations: Set[str] | None = None

    @classmethod
    def from_env(cls) -> "DefaultPolicyGate":
        return cls(
            live_allow_write_safe=_parse_bool(
                os.environ.get("VEI_LIVE_ALLOW_WRITE_SAFE"), False
            ),
            live_allow_write_risky=_parse_bool(
                os.environ.get("VEI_LIVE_ALLOW_WRITE_RISKY"), False
            ),
            blocked_operations=_parse_blocked_operations(
                os.environ.get("VEI_LIVE_BLOCK_OPS")
            ),
        )

    def evaluate(self, request: ConnectorRequest, mode: AdapterMode) -> PolicyDecision:
        blocked = self.blocked_operations or set()
        operation_id = f"{request.service.value}.{request.operation}"
        if operation_id in blocked:
            return PolicyDecision(
                action=PolicyDecisionAction.DENY,
                reason=f"blocked operation: {operation_id}",
            )

        if mode != AdapterMode.LIVE:
            return PolicyDecision(
                action=PolicyDecisionAction.ALLOW, reason="non-live mode"
            )

        if request.operation_class == OperationClass.READ:
            return PolicyDecision(
                action=PolicyDecisionAction.ALLOW, reason="live read allowed"
            )

        if request.operation_class == OperationClass.WRITE_SAFE:
            if self.live_allow_write_safe:
                return PolicyDecision(
                    action=PolicyDecisionAction.ALLOW,
                    reason="live safe-write allowed",
                )
            return PolicyDecision(
                action=PolicyDecisionAction.REQUIRE_APPROVAL,
                reason="live safe-write requires approval",
            )

        if request.operation_class == OperationClass.WRITE_RISKY:
            if self.live_allow_write_risky:
                return PolicyDecision(
                    action=PolicyDecisionAction.ALLOW,
                    reason="live risky-write allowed",
                )
            return PolicyDecision(
                action=PolicyDecisionAction.DENY,
                reason="live risky-write blocked",
            )

        return PolicyDecision(
            action=PolicyDecisionAction.ALLOW, reason="fallback allow"
        )
