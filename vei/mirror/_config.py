from __future__ import annotations

from typing import Any, Mapping, cast

from .models import (
    MirrorPolicyProfile,
    MirrorPolicyProfileId,
    MirrorWorkspaceConfig,
)

_PROFILE_REGISTRY: dict[MirrorPolicyProfileId, MirrorPolicyProfile] = {
    "observer": MirrorPolicyProfile(
        profile_id="observer",
        label="Observer",
        description="Can read governed surfaces but cannot make changes.",
        can_approve=False,
        read_access=True,
        safe_write_access="deny",
        risky_write_access="deny",
    ),
    "operator": MirrorPolicyProfile(
        profile_id="operator",
        label="Operator",
        description="Can read and perform safe changes. Risky changes pause for approval.",
        can_approve=False,
        read_access=True,
        safe_write_access="allow",
        risky_write_access="require_approval",
    ),
    "approver": MirrorPolicyProfile(
        profile_id="approver",
        label="Approver",
        description="Can operate like an operator and resolve approval holds.",
        can_approve=True,
        read_access=True,
        safe_write_access="allow",
        risky_write_access="require_approval",
    ),
    "admin": MirrorPolicyProfile(
        profile_id="admin",
        label="Admin",
        description="Full access inside surface allowlists and connector safety rules.",
        can_approve=True,
        read_access=True,
        safe_write_access="allow",
        risky_write_access="allow",
    ),
}


def default_mirror_workspace_config(
    *,
    connector_mode: str = "sim",
    demo_mode: bool = False,
    autoplay: bool = False,
    demo_interval_ms: int = 1500,
    hero_world: str | None = None,
) -> MirrorWorkspaceConfig:
    return MirrorWorkspaceConfig(
        connector_mode=(
            "live" if str(connector_mode).strip().lower() == "live" else "sim"
        ),
        demo_mode=bool(demo_mode),
        autoplay=bool(autoplay),
        demo_interval_ms=max(250, int(demo_interval_ms)),
        hero_world=hero_world,
    )


def mirror_policy_profiles() -> list[MirrorPolicyProfile]:
    return [profile.model_copy(deep=True) for profile in _PROFILE_REGISTRY.values()]


def resolve_mirror_policy_profile(
    profile_id: MirrorPolicyProfileId | str | None,
) -> MirrorPolicyProfile:
    normalized = str(profile_id or "admin").strip().lower() or "admin"
    if normalized not in _PROFILE_REGISTRY:
        normalized = "admin"
    resolved_id = cast(MirrorPolicyProfileId, normalized)
    return _PROFILE_REGISTRY[resolved_id].model_copy(deep=True)


def mirror_metadata_payload(
    config: MirrorWorkspaceConfig | None = None,
    *,
    connector_mode: str = "sim",
    demo_mode: bool = False,
    autoplay: bool = False,
    demo_interval_ms: int = 1500,
    hero_world: str | None = None,
) -> dict[str, Any]:
    resolved = config or default_mirror_workspace_config(
        connector_mode=connector_mode,
        demo_mode=demo_mode,
        autoplay=autoplay,
        demo_interval_ms=demo_interval_ms,
        hero_world=hero_world,
    )
    return resolved.model_dump(mode="json")


def load_mirror_workspace_config(
    metadata: Mapping[str, Any] | None,
) -> MirrorWorkspaceConfig:
    if not isinstance(metadata, Mapping):
        return default_mirror_workspace_config()
    payload = metadata.get("mirror")
    if not isinstance(payload, Mapping):
        return default_mirror_workspace_config()
    return MirrorWorkspaceConfig.model_validate(dict(payload))
