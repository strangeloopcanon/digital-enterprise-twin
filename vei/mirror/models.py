from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

MirrorConnectorMode = Literal["sim", "live"]
MirrorAgentMode = Literal["proxy", "ingest", "demo"]
MirrorAgentStatus = Literal["registered", "active", "idle", "error"]
MirrorHandleMode = Literal[
    "dispatch",
    "inject",
    "record_only",
    "denied",
    "pending_approval",
]
MirrorPolicyProfileId = Literal["observer", "operator", "approver", "admin"]
MirrorOperationClass = Literal["read", "write_safe", "write_risky"]
MirrorApprovalStatus = Literal[
    "pending",
    "approved",
    "rejected",
    "executed",
    "failed",
]
MirrorConnectorAvailability = Literal["healthy", "degraded"]
MirrorConnectorWriteCapability = Literal["interactive", "read_only", "unsupported"]
MirrorActionDecision = Literal["allow", "deny", "approval_required"]


class MirrorPolicyProfile(BaseModel):
    profile_id: MirrorPolicyProfileId
    label: str
    description: str
    can_approve: bool = False
    read_access: bool = True
    safe_write_access: Literal["allow", "deny"] = "deny"
    risky_write_access: Literal["allow", "deny", "require_approval"] = "deny"


class MirrorWorkspaceConfig(BaseModel):
    connector_mode: MirrorConnectorMode = "sim"
    demo_mode: bool = False
    autoplay: bool = False
    demo_interval_ms: int = 1500
    hero_world: str | None = None

    @model_validator(mode="after")
    def validate_demo_connector_mode(self) -> "MirrorWorkspaceConfig":
        if self.demo_mode and self.connector_mode != "sim":
            raise ValueError("mirror demo mode requires connector_mode='sim'")
        return self


class MirrorAgentSpec(BaseModel):
    agent_id: str
    name: str
    mode: MirrorAgentMode = "ingest"
    role: str | None = None
    team: str | None = None
    allowed_surfaces: list[str] = Field(default_factory=list)
    policy_profile_id: MirrorPolicyProfileId = "admin"
    resolved_policy_profile: MirrorPolicyProfile | None = None
    status: MirrorAgentStatus = "registered"
    last_seen_at: str | None = None
    source: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    denied_count: int = 0
    throttled_count: int = 0
    last_action: str | None = None

    @model_validator(mode="before")
    @classmethod
    def upgrade_legacy_policy_profile(
        cls,
        value: Any,
    ) -> Any:
        if not isinstance(value, dict):
            return value
        if value.get("policy_profile_id") is not None:
            return value
        legacy = str(value.get("policy_profile") or "").strip().lower()
        if not legacy:
            return {**value, "policy_profile_id": "admin"}
        mapped = {
            "observe": "observer",
            "observer": "observer",
            "write_safe": "operator",
            "operator": "operator",
            "approver": "approver",
            "full": "admin",
            "admin": "admin",
            "dispatch_safe": "operator",
            "billing_safe": "operator",
        }.get(legacy, "admin")
        return {**value, "policy_profile_id": mapped}


class MirrorIngestEvent(BaseModel):
    event_id: str | None = None
    agent_id: str
    external_tool: str
    resolved_tool: str | None = None
    focus_hint: str | None = None
    target: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)
    label: str | None = None
    source_mode: MirrorAgentMode = "ingest"


class MirrorEventResult(BaseModel):
    ok: bool = True
    handled_by: MirrorHandleMode
    agent_id: str
    remaining_demo_steps: int = 0
    result: dict[str, Any] = Field(default_factory=dict)


class MirrorRecentEvent(BaseModel):
    event_id: str | None = None
    agent_id: str
    tool: str
    handled_by: MirrorHandleMode
    resolved_tool: str | None = None
    surface: str | None = None
    label: str | None = None
    reason_code: str | None = None
    reason: str | None = None
    timestamp: str


class MirrorPendingApproval(BaseModel):
    approval_id: str
    agent_id: str
    surface: str
    resolved_tool: str
    operation_class: MirrorOperationClass
    args: dict[str, Any] = Field(default_factory=dict)
    reason_code: str
    reason: str
    status: MirrorApprovalStatus = "pending"
    created_at: str
    resolved_by: str | None = None
    resolved_at: str | None = None
    execution_result: dict[str, Any] = Field(default_factory=dict)
    external_tool: str | None = None
    focus_hint: str | None = None
    target: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    source_mode: MirrorAgentMode = "ingest"


class MirrorConnectorStatus(BaseModel):
    surface: str
    source_mode: MirrorConnectorMode
    availability: MirrorConnectorAvailability
    write_capability: MirrorConnectorWriteCapability
    reason: str | None = None
    last_checked_at: str | None = None


class MirrorActionPlan(BaseModel):
    action: Literal["dispatch", "inject"]
    surface: str
    resolved_tool: str
    operation_class: MirrorOperationClass
    decision: MirrorActionDecision = "allow"
    reason_code: str | None = None
    reason: str | None = None


class MirrorRuntimeSnapshot(BaseModel):
    config: MirrorWorkspaceConfig
    agents: list[MirrorAgentSpec] = Field(default_factory=list)
    policy_profiles: list[MirrorPolicyProfile] = Field(default_factory=list)
    event_count: int = 0
    denied_event_count: int = 0
    throttled_event_count: int = 0
    pending_demo_steps: int = 0
    last_event_at: str | None = None
    autoplay_running: bool = False
    pending_approvals: list[MirrorPendingApproval] = Field(default_factory=list)
    connector_status: list[MirrorConnectorStatus] = Field(default_factory=list)
    recent_events: list[MirrorRecentEvent] = Field(default_factory=list)
