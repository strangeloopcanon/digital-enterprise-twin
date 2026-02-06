from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class AdapterMode(str, Enum):
    SIM = "sim"
    REPLAY = "replay"
    LIVE = "live"


class OperationClass(str, Enum):
    READ = "read"
    WRITE_SAFE = "write_safe"
    WRITE_RISKY = "write_risky"


class ServiceName(str, Enum):
    SLACK = "slack"
    MAIL = "mail"
    CALENDAR = "calendar"
    DOCS = "docs"
    TICKETS = "tickets"
    DB = "db"
    ERP = "erp"
    CRM = "crm"
    OKTA = "okta"
    SERVICEDESK = "servicedesk"


class ConnectorError(BaseModel):
    code: str
    message: str
    retryable: bool = False
    detail: Dict[str, Any] = Field(default_factory=dict)


class ConnectorRequest(BaseModel):
    request_id: str
    service: ServiceName
    operation: str
    operation_class: OperationClass
    payload: Dict[str, Any] = Field(default_factory=dict)
    actor: str = "agent"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ConnectorResult(BaseModel):
    ok: bool = True
    status_code: int = 200
    data: Any = Field(default_factory=dict)
    raw: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[ConnectorError] = None
    latency_ms: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class PolicyDecisionAction(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


class PolicyDecision(BaseModel):
    action: PolicyDecisionAction
    reason: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ConnectorReceipt(BaseModel):
    request_id: str
    mode: AdapterMode
    service: ServiceName
    operation: str
    operation_class: OperationClass
    policy_action: PolicyDecisionAction
    ok: bool
    status_code: int
    request_payload: Dict[str, Any] = Field(default_factory=dict)
    response_payload: Dict[str, Any] = Field(default_factory=dict)
    latency_ms: int = 0
    time_ms: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ConnectorInvocationError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.detail = dict(detail or {})
