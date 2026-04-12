from __future__ import annotations

from vei.whatif.corpus import has_external_recipients
from vei.whatif.models import WhatIfEvent, WhatIfScenario

_SUPPORTED_SCENARIOS: dict[str, WhatIfScenario] = {
    "compliance_gateway": WhatIfScenario(
        scenario_id="compliance_gateway",
        title="Compliance Gateway",
        description=(
            "Threads touching both legal and trading signals require review before "
            "forwarding or escalation."
        ),
        decision_branches=[
            "Block flagged threads until compliance clears them.",
            "Allow them through but log them for post-hoc audit.",
        ],
    ),
    "escalation_firewall": WhatIfScenario(
        scenario_id="escalation_firewall",
        title="Escalation Firewall",
        description=(
            "Direct escalations to senior executives require a department-head gate."
        ),
        decision_branches=[
            "Require sign-off before executive escalation.",
            "Allow direct escalation but flag the thread for governance review.",
        ],
    ),
    "external_dlp": WhatIfScenario(
        scenario_id="external_dlp",
        title="External Sharing DLP",
        description=(
            "Messages with attachment references to outside recipients are held for "
            "review."
        ),
        decision_branches=[
            "Hold the message until DLP review clears it.",
            "Allow send but retain a mandatory audit trail.",
        ],
    ),
    "approval_chain_enforcement": WhatIfScenario(
        scenario_id="approval_chain_enforcement",
        title="Approval Chain Enforcement",
        description=(
            "Assignment-heavy threads require explicit approval before the next "
            "handoff proceeds."
        ),
        decision_branches=[
            "Stop handoffs until an approval is recorded.",
            "Allow handoff but mark the thread out of policy.",
        ],
    ),
}


def list_supported_scenarios() -> list[WhatIfScenario]:
    return list(_SUPPORTED_SCENARIOS.values())


def resolve_scenario(
    *,
    scenario: str | None,
    prompt: str | None,
) -> WhatIfScenario:
    if scenario:
        resolved = _SUPPORTED_SCENARIOS.get(scenario.strip().lower())
        if resolved is None:
            raise ValueError(f"unsupported what-if scenario: {scenario}")
        return resolved
    if not prompt:
        raise ValueError("provide --scenario or --prompt")
    lowered = prompt.strip().lower()
    if "legal" in lowered and "trading" in lowered:
        return _SUPPORTED_SCENARIOS["compliance_gateway"]
    if (
        any(token in lowered for token in ("compliance", "review", "audit"))
        and "thread" in lowered
    ):
        return _SUPPORTED_SCENARIOS["compliance_gateway"]
    if any(
        token in lowered
        for token in ("c-suite", "executive", "skilling", "lay", "fastow", "kean")
    ):
        return _SUPPORTED_SCENARIOS["escalation_firewall"]
    if any(token in lowered for token in ("external", "attachment", "dlp", "outside")):
        return _SUPPORTED_SCENARIOS["external_dlp"]
    if any(
        token in lowered for token in ("approval", "sign-off", "handoff", "assignment")
    ):
        return _SUPPORTED_SCENARIOS["approval_chain_enforcement"]
    supported = ", ".join(sorted(_SUPPORTED_SCENARIOS))
    raise ValueError(f"could not map prompt to a supported scenario ({supported})")


def resolve_scenario_from_specific_event(
    *,
    prompt: str,
    event: WhatIfEvent | None,
    organization_domain: str,
) -> WhatIfScenario:
    try:
        return resolve_scenario(scenario=None, prompt=prompt)
    except ValueError:
        if event is None:
            return _SUPPORTED_SCENARIOS["compliance_gateway"]
        if event.flags.has_attachment_reference and has_external_recipients(
            event.flags.to_recipients,
            organization_domain=organization_domain,
        ):
            return _SUPPORTED_SCENARIOS["external_dlp"]
        if (
            event.flags.consult_legal_specialist
            or event.flags.consult_trading_specialist
        ):
            return _SUPPORTED_SCENARIOS["compliance_gateway"]
        if event.flags.is_escalation or event.event_type == "escalation":
            return _SUPPORTED_SCENARIOS["escalation_firewall"]
        if event.event_type == "assignment":
            return _SUPPORTED_SCENARIOS["approval_chain_enforcement"]
        return _SUPPORTED_SCENARIOS["compliance_gateway"]


__all__ = [
    "list_supported_scenarios",
    "resolve_scenario",
    "resolve_scenario_from_specific_event",
]
