from __future__ import annotations

import json
from datetime import datetime, timezone
from importlib import resources

from .models import (
    WhatIfPublicContext,
    WhatIfPublicFinancialSnapshot,
    WhatIfPublicNewsEvent,
)


def empty_enron_public_context(
    *,
    window_start: str = "",
    window_end: str = "",
    branch_timestamp: str = "",
) -> WhatIfPublicContext:
    return WhatIfPublicContext(
        pack_name="enron_public_context",
        organization_name="Enron Corporation",
        organization_domain="enron.com",
        window_start=window_start,
        window_end=window_end,
        branch_timestamp=branch_timestamp,
    )


def load_enron_public_context(
    *,
    window_start: str = "",
    window_end: str = "",
) -> WhatIfPublicContext:
    empty = empty_enron_public_context(
        window_start=window_start,
        window_end=window_end,
    )
    try:
        fixture = resources.files("vei.whatif").joinpath(
            "fixtures/enron_public_context/enron_public_context_v1.json"
        )
        payload = fixture.read_text(encoding="utf-8")
        context = WhatIfPublicContext.model_validate(json.loads(payload))
    except Exception:  # noqa: BLE001
        return empty
    return slice_public_context_to_window(
        context,
        window_start=window_start,
        window_end=window_end,
    )


def slice_public_context_to_window(
    context: WhatIfPublicContext | None,
    *,
    window_start: str = "",
    window_end: str = "",
) -> WhatIfPublicContext | None:
    if context is None:
        return None

    start_day = _date_value(window_start)
    end_day = _date_value(window_end)

    financial_snapshots = [
        snapshot
        for snapshot in context.financial_snapshots
        if _within_bounds(
            _date_value(snapshot.as_of), start_day=start_day, end_day=end_day
        )
    ]
    financial_snapshots = _sort_financial_snapshots(financial_snapshots)
    public_news_events = [
        event
        for event in context.public_news_events
        if _within_bounds(
            _date_value(event.timestamp),
            start_day=start_day,
            end_day=end_day,
        )
    ]
    public_news_events = _sort_public_news_events(public_news_events)
    return context.model_copy(
        update={
            "window_start": window_start,
            "window_end": window_end,
            "branch_timestamp": "",
            "financial_snapshots": financial_snapshots,
            "public_news_events": public_news_events,
        }
    )


def slice_public_context_to_branch(
    context: WhatIfPublicContext | None,
    *,
    branch_timestamp: str = "",
) -> WhatIfPublicContext | None:
    if context is None:
        return None

    branch_day = _date_value(branch_timestamp)
    if branch_day is None:
        return context.model_copy(
            update={
                "branch_timestamp": branch_timestamp,
                "financial_snapshots": _sort_financial_snapshots(
                    context.financial_snapshots
                ),
                "public_news_events": _sort_public_news_events(
                    context.public_news_events
                ),
            }
        )

    financial_snapshots = [
        snapshot
        for snapshot in context.financial_snapshots
        if _date_value(snapshot.as_of) is not None
        and _date_value(snapshot.as_of) <= branch_day
    ]
    financial_snapshots = _sort_financial_snapshots(financial_snapshots)
    public_news_events = [
        event
        for event in context.public_news_events
        if _date_value(event.timestamp) is not None
        and _date_value(event.timestamp) <= branch_day
    ]
    public_news_events = _sort_public_news_events(public_news_events)
    return context.model_copy(
        update={
            "branch_timestamp": branch_timestamp,
            "financial_snapshots": financial_snapshots,
            "public_news_events": public_news_events,
        }
    )


def public_context_has_items(context: WhatIfPublicContext | None) -> bool:
    if context is None:
        return False
    return bool(context.financial_snapshots or context.public_news_events)


def public_context_prompt_lines(
    context: WhatIfPublicContext | None,
    *,
    max_financial: int = 3,
    max_news: int = 3,
) -> list[str]:
    if not public_context_has_items(context):
        return []

    lines = ["Public company context known by this date:"]

    financial_snapshots = list(context.financial_snapshots[-max(1, max_financial) :])
    if financial_snapshots:
        lines.append("Financial checkpoints:")
        for snapshot in financial_snapshots:
            lines.append(
                f"- {snapshot.as_of[:10]} {snapshot.label}: {snapshot.summary}"
            )

    public_news_events = list(context.public_news_events[-max(1, max_news) :])
    if public_news_events:
        lines.append("Public news checkpoints:")
        for event in public_news_events:
            lines.append(f"- {event.timestamp[:10]} {event.headline}: {event.summary}")

    return lines


def _within_bounds(
    date_value: int | None,
    *,
    start_day: int | None,
    end_day: int | None,
) -> bool:
    if date_value is None:
        return False
    if start_day is not None and date_value < start_day:
        return False
    if end_day is not None and date_value > end_day:
        return False
    return True


def _sort_financial_snapshots(
    snapshots: list[WhatIfPublicFinancialSnapshot],
) -> list[WhatIfPublicFinancialSnapshot]:
    return sorted(
        snapshots,
        key=lambda snapshot: _date_sort_key(
            snapshot.as_of,
            tie_breaker=snapshot.snapshot_id,
        ),
    )


def _sort_public_news_events(
    events: list[WhatIfPublicNewsEvent],
) -> list[WhatIfPublicNewsEvent]:
    return sorted(
        events,
        key=lambda event: _date_sort_key(
            event.timestamp,
            tie_breaker=event.event_id,
        ),
    )


def _date_sort_key(value: str, *, tie_breaker: str) -> tuple[int, int, str]:
    date_value = _date_value(value)
    if date_value is None:
        return (1, 0, tie_breaker)
    return (0, date_value, tie_breaker)


def _date_value(value: str) -> int | None:
    timestamp_ms = _timestamp_ms(value)
    if timestamp_ms is None:
        return None
    return int(
        datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).date().toordinal()
    )


def _timestamp_ms(value: str) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(
            datetime.fromisoformat(text.replace("Z", "+00:00"))
            .astimezone(timezone.utc)
            .timestamp()
            * 1000
        )
    except ValueError:
        return None
