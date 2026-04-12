from __future__ import annotations

from vei.whatif.models import (
    WhatIfExperimentResult,
    WhatIfRankedExperimentResult,
)


def render_experiment_overview(result: WhatIfExperimentResult) -> str:
    lines = [
        f"# {result.label}",
        "",
        f"Thread: `{result.intervention.thread_id}`",
        f"Branch event: `{result.intervention.branch_event_id}`",
        f"Changed actor: `{result.materialization.branch_event.actor_id}`",
        f"Historical event type: {result.materialization.branch_event.event_type}",
        f"Historical subject: {result.materialization.branch_event.subject}",
        f"Prompt: {result.intervention.prompt}",
        "",
        "## Historical Event",
        f"- Timestamp: {result.materialization.branch_event.timestamp}",
        f"- To: {', '.join(result.materialization.branch_event.to_recipients) or result.materialization.branch_event.target_id or '(none)'}",
        f"- Forward: {'yes' if result.materialization.branch_event.is_forward else 'no'}",
        f"- Escalation: {'yes' if result.materialization.branch_event.is_escalation else 'no'}",
        f"- Attachment: {'yes' if result.materialization.branch_event.has_attachment_reference else 'no'}",
        "",
        "## Baseline",
        f"- Scheduled historical future events: {result.baseline.scheduled_event_count}",
        f"- Delivered historical future events: {result.baseline.delivered_event_count}",
        f"- Baseline forecast risk score: {result.baseline.forecast.risk_score}",
    ]
    if result.materialization.baseline_future_preview:
        lines.extend(["- First baseline events:"])
        for event in result.materialization.baseline_future_preview[:3]:
            lines.append(
                f"  - `{event.event_id}` {event.event_type} from `{event.actor_id}`: {event.subject}"
            )
    if result.llm_result is not None:
        lines.extend(
            [
                "",
                "## LLM Actor",
                f"- Status: {result.llm_result.status}",
                f"- Summary: {result.llm_result.summary}",
                f"- Delivered messages: {result.llm_result.delivered_event_count}",
                f"- Inbox count: {result.llm_result.inbox_count}",
            ]
        )
        for message in result.llm_result.messages[:3]:
            lines.append(
                f"- `{message.actor_id}` -> `{message.to}` after {message.delay_ms} ms: {message.subject}"
            )
    if result.forecast_result is not None:
        lines.extend(
            [
                "",
                "## Forecast",
                f"- Status: {result.forecast_result.status}",
                f"- Backend: {result.forecast_result.backend}",
                f"- Summary: {result.forecast_result.summary}",
                f"- Baseline risk: {result.forecast_result.baseline.risk_score}",
                f"- Predicted risk: {result.forecast_result.predicted.risk_score}",
                f"- External-send delta: {result.forecast_result.delta.external_event_delta}",
                f"- Escalation delta: {result.forecast_result.delta.escalation_delta}",
            ]
        )
    return "\n".join(lines)


def render_ranked_experiment_overview(result: WhatIfRankedExperimentResult) -> str:
    branch_event = result.materialization.branch_event
    lines = [
        f"# {result.label}",
        "",
        f"Objective: {result.objective_pack.title}",
        f"Selected thread: `{result.materialization.thread_id}`",
        f"Branch event: `{result.materialization.branch_event_id}`",
        f"Historical subject: {branch_event.subject}",
        f"Recommended candidate: {result.recommended_candidate_label or '(none)'}",
        "",
        "## Historical Baseline",
        f"- Delivered historical future events: {result.baseline.delivered_event_count}",
        f"- Historical risk score: {result.baseline.forecast.risk_score}",
        "",
        "## Ranked Candidates",
    ]
    for candidate in result.candidates:
        lines.extend(
            [
                f"- Rank {candidate.rank}: {candidate.intervention.label}",
                f"  - Score: {candidate.outcome_score.overall_score}",
                f"  - Prompt: {candidate.intervention.prompt}",
                f"  - Reason: {candidate.reason}",
                (
                    f"  - Signals: exposure={candidate.average_outcome_signals.exposure_risk}, "
                    f"delay={candidate.average_outcome_signals.delay_risk}, "
                    f"relationship={candidate.average_outcome_signals.relationship_protection}"
                ),
            ]
        )
        if candidate.shadow is not None:
            lines.append(
                f"  - Shadow ({candidate.shadow.backend}): {candidate.shadow.outcome_score.overall_score}"
            )
    return "\n".join(lines)


def slug_artifact_label(value: str) -> str:
    return "_".join(part for part in value.strip().lower().replace("-", " ").split())


__all__ = [
    "render_experiment_overview",
    "render_ranked_experiment_overview",
    "slug_artifact_label",
]
