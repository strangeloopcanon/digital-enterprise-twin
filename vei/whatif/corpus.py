from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from vei.context.models import ContextSnapshot

from .models import (
    WhatIfActorProfile,
    WhatIfArtifactFlags,
    WhatIfEvent,
    WhatIfEventMatch,
    WhatIfEventReference,
    WhatIfEventSearchResult,
    WhatIfScenario,
    WhatIfThreadSummary,
    WhatIfWorld,
    WhatIfWorldSummary,
)

ENRON_DOMAIN = "enron.com"
CONTENT_NOTICE = (
    "Historical email bodies are built from Rosetta excerpts and event metadata. "
    "They are grounded, but they are not full original messages."
)
MAIL_ARCHIVE_CONTENT_NOTICE = (
    "Historical email bodies come from the supplied mail archive snapshot. "
    "They reflect the available archive text for each message."
)
EXECUTIVE_MARKERS = ("skilling", "lay", "fastow", "kean")
MAIL_ARCHIVE_FILE_NAMES = (
    "context_snapshot.json",
    "mail_archive.json",
    "historical_mail_archive.json",
    "whatif_mail_archive.json",
)


def detect_whatif_source(source_dir: str | Path) -> str:
    resolved = Path(source_dir).expanduser().resolve()
    if _looks_like_enron_rosetta(resolved):
        return "enron"
    if _looks_like_mail_archive(resolved):
        return "mail_archive"
    raise ValueError(f"could not detect historical source from: {resolved}")


def load_enron_world(
    *,
    rosetta_dir: str | Path,
    scenarios: Sequence[WhatIfScenario] | None = None,
    time_window: tuple[str, str] | None = None,
    custodian_filter: Sequence[str] | None = None,
    max_events: int | None = None,
    include_content: bool = False,
) -> WhatIfWorld:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - guarded by dependency
        raise RuntimeError(
            "pyarrow is required for `vei whatif` parquet loading"
        ) from exc

    base = Path(rosetta_dir).expanduser().resolve()
    metadata_path = base / "enron_rosetta_events_metadata.parquet"
    content_path = base / "enron_rosetta_events_content.parquet"
    if not metadata_path.exists():
        raise ValueError(f"metadata parquet not found: {metadata_path}")
    if not content_path.exists():
        raise ValueError(f"content parquet not found: {content_path}")

    metadata_rows = pq.read_table(
        metadata_path,
        columns=[
            "event_id",
            "timestamp",
            "actor_id",
            "target_id",
            "event_type",
            "thread_task_id",
            "artifacts",
        ],
    ).to_pylist()
    content_by_id = (
        load_content_by_event_ids(
            rosetta_dir=base,
            event_ids=[
                str(row.get("event_id", ""))
                for row in metadata_rows
                if str(row.get("event_id", "")).strip()
            ],
        )
        if include_content
        else {}
    )

    time_bounds = resolve_time_window(time_window)
    custodian_tokens = {item.strip().lower() for item in custodian_filter or [] if item}
    events: list[WhatIfEvent] = []
    for row in metadata_rows:
        event = build_event(row, content_by_id.get(str(row.get("event_id", "")), ""))
        if event is None:
            continue
        if time_bounds is not None and not (
            time_bounds[0] <= event.timestamp_ms <= time_bounds[1]
        ):
            continue
        if custodian_tokens and not matches_custodian_filter(event, custodian_tokens):
            continue
        events.append(event)

    events.sort(key=lambda item: (item.timestamp_ms, item.event_id))
    if max_events is not None:
        events = events[: max(0, int(max_events))]

    threads = build_thread_summaries(events, organization_domain=ENRON_DOMAIN)
    actors = build_actor_profiles(events, organization_domain=ENRON_DOMAIN)
    summary = WhatIfWorldSummary(
        source="enron",
        organization_name="Enron Corporation",
        organization_domain=ENRON_DOMAIN,
        event_count=len(events),
        thread_count=len(threads),
        actor_count=len(actors),
        custodian_count=len(
            {
                custodian
                for actor in actors
                for custodian in actor.custodian_ids
                if custodian
            }
        ),
        first_timestamp=events[0].timestamp if events else "",
        last_timestamp=events[-1].timestamp if events else "",
        event_type_counts=dict(Counter(event.event_type for event in events)),
        key_actor_ids=[actor.actor_id for actor in actors[:5]],
    )
    return WhatIfWorld(
        source="enron",
        source_dir=base,
        summary=summary,
        scenarios=list(scenarios or []),
        actors=actors,
        threads=threads,
        events=events,
        metadata={"content_notice": CONTENT_NOTICE},
    )


def load_mail_archive_world(
    *,
    source_dir: str | Path,
    scenarios: Sequence[WhatIfScenario] | None = None,
    time_window: tuple[str, str] | None = None,
    max_events: int | None = None,
    include_content: bool = False,
) -> WhatIfWorld:
    resolved_source_dir = Path(source_dir).expanduser().resolve()
    snapshot = _load_mail_archive_snapshot(resolved_source_dir)
    source_payload = _mail_archive_source_payload(snapshot)
    threads_payload = _archive_threads_from_snapshot(snapshot)
    if not threads_payload:
        raise ValueError("mail archive source does not contain any threads")

    organization_name = str(snapshot.organization_name or "").strip()
    organization_domain = str(snapshot.organization_domain or "").strip().lower()
    if not organization_domain:
        organization_domain = _organization_domain_from_threads(threads_payload)
    if not organization_name:
        organization_name = _organization_name_from_domain(organization_domain)

    time_bounds = resolve_time_window(time_window)
    events: list[WhatIfEvent] = []
    for thread_index, thread in enumerate(threads_payload):
        if not isinstance(thread, dict):
            continue
        thread_id = _archive_thread_id(thread, index=thread_index)
        thread_subject = _archive_thread_subject(thread, fallback=thread_id)
        messages = [
            item for item in (thread.get("messages") or []) if isinstance(item, dict)
        ]
        for message_index, message in enumerate(messages):
            event = build_archive_event(
                message=message,
                thread_id=thread_id,
                thread_subject=thread_subject,
                organization_domain=organization_domain,
                thread_index=thread_index,
                message_index=message_index,
                include_content=include_content,
            )
            if event is None:
                continue
            if time_bounds is not None and not (
                time_bounds[0] <= event.timestamp_ms <= time_bounds[1]
            ):
                continue
            events.append(event)

    events.sort(key=lambda item: (item.timestamp_ms, item.event_id))
    if max_events is not None:
        events = events[: max(0, int(max_events))]

    archive_actor_payload = source_payload.get("actors", [])
    actors = _override_actor_profiles(
        build_actor_profiles(events, organization_domain=organization_domain),
        actor_payload=(
            archive_actor_payload if isinstance(archive_actor_payload, list) else []
        ),
    )
    threads = build_thread_summaries(
        events,
        organization_domain=organization_domain,
    )
    summary = WhatIfWorldSummary(
        source="mail_archive",
        organization_name=organization_name,
        organization_domain=organization_domain,
        event_count=len(events),
        thread_count=len(threads),
        actor_count=len(actors),
        custodian_count=0,
        first_timestamp=events[0].timestamp if events else "",
        last_timestamp=events[-1].timestamp if events else "",
        event_type_counts=dict(Counter(event.event_type for event in events)),
        key_actor_ids=[actor.actor_id for actor in actors[:5]],
    )
    return WhatIfWorld(
        source="mail_archive",
        source_dir=resolved_source_dir,
        summary=summary,
        scenarios=list(scenarios or []),
        actors=actors,
        threads=threads,
        events=events,
        metadata={"content_notice": MAIL_ARCHIVE_CONTENT_NOTICE},
    )


def _looks_like_enron_rosetta(path: Path) -> bool:
    if path.is_file():
        return False
    return (path / "enron_rosetta_events_metadata.parquet").exists()


def _looks_like_mail_archive(path: Path) -> bool:
    if path.is_file():
        return path.suffix.lower() == ".json"
    return any((path / filename).exists() for filename in MAIL_ARCHIVE_FILE_NAMES)


def _load_mail_archive_snapshot(path: Path) -> ContextSnapshot:
    if path.is_file():
        return _snapshot_from_json_payload(path)
    for filename in MAIL_ARCHIVE_FILE_NAMES:
        candidate = path / filename
        if candidate.exists():
            return _snapshot_from_json_payload(candidate)
    raise ValueError(f"mail archive snapshot not found under: {path}")


def _snapshot_from_json_payload(path: Path) -> ContextSnapshot:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("sources"), list):
        return ContextSnapshot.model_validate(payload)
    if isinstance(payload, dict) and isinstance(payload.get("threads"), list):
        return _snapshot_from_archive_payload(payload)
    raise ValueError(f"unsupported mail archive payload: {path}")


def _snapshot_from_archive_payload(payload: dict[str, Any]) -> ContextSnapshot:
    organization_name = str(payload.get("organization_name", "") or "").strip()
    organization_domain = str(payload.get("organization_domain", "") or "").strip()
    threads = payload.get("threads", [])
    actors = payload.get("actors", [])
    captured_at = str(payload.get("captured_at", "") or "")
    return ContextSnapshot(
        organization_name=organization_name
        or _organization_name_from_domain(organization_domain),
        organization_domain=organization_domain,
        captured_at=captured_at,
        sources=[
            {
                "provider": "mail_archive",
                "captured_at": captured_at,
                "status": "ok",
                "record_counts": {
                    "threads": len(threads) if isinstance(threads, list) else 0,
                    "actors": len(actors) if isinstance(actors, list) else 0,
                },
                "data": {
                    "threads": threads if isinstance(threads, list) else [],
                    "actors": actors if isinstance(actors, list) else [],
                },
            }
        ],
        metadata=dict(payload.get("metadata", {}) or {}),
    )


def _mail_archive_source_payload(snapshot: ContextSnapshot) -> dict[str, Any]:
    mail_archive_source = snapshot.source_for("mail_archive")
    if mail_archive_source is not None and isinstance(mail_archive_source.data, dict):
        return mail_archive_source.data
    gmail_source = snapshot.source_for("gmail")
    if gmail_source is not None and isinstance(gmail_source.data, dict):
        return {
            "threads": _archive_threads_from_gmail_payload(gmail_source.data),
            "actors": [],
        }
    raise ValueError("snapshot does not contain a mail archive or gmail mail source")


def _archive_threads_from_snapshot(snapshot: ContextSnapshot) -> list[dict[str, Any]]:
    source_payload = _mail_archive_source_payload(snapshot)
    threads = source_payload.get("threads", [])
    return [thread for thread in threads if isinstance(thread, dict)]


def _archive_threads_from_gmail_payload(
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    threads: list[dict[str, Any]] = []
    for thread in payload.get("threads", []):
        if not isinstance(thread, dict):
            continue
        messages: list[dict[str, Any]] = []
        for message in thread.get("messages", []):
            if not isinstance(message, dict):
                continue
            messages.append(
                {
                    "message_id": str(message.get("id", "") or ""),
                    "from": str(message.get("from", "") or ""),
                    "to": str(message.get("to", "") or ""),
                    "subject": str(
                        message.get("subject", thread.get("subject", "")) or ""
                    ),
                    "body_text": str(
                        message.get("snippet", message.get("body_text", "")) or ""
                    ),
                    "time_ms": safe_int(message.get("internal_date", 0)),
                    "unread": bool(message.get("unread", False)),
                }
            )
        if not messages:
            continue
        threads.append(
            {
                "thread_id": str(thread.get("thread_id", "") or ""),
                "subject": str(thread.get("subject", "") or ""),
                "category": "historical",
                "messages": messages,
            }
        )
    return threads


def build_archive_event(
    *,
    message: dict[str, Any],
    thread_id: str,
    thread_subject: str,
    organization_domain: str,
    thread_index: int,
    message_index: int,
    include_content: bool,
) -> WhatIfEvent | None:
    actor_id = str(message.get("from", "") or "").strip()
    recipients = _recipient_list(message.get("to"))
    subject = _archive_subject(message, fallback=thread_subject)
    body_text = _archive_body_text(message)
    cc_recipients = _recipient_list(message.get("cc"))
    event_id = _archive_event_id(
        message=message,
        thread_id=thread_id,
        thread_index=thread_index,
        message_index=message_index,
    )
    if not actor_id and not recipients:
        return None

    timestamp_ms, timestamp_text = _archive_timestamp(
        message=message,
        thread_index=thread_index,
        message_index=message_index,
    )
    is_forward = _message_flag(
        message,
        key="is_forward",
        subject=subject,
        prefixes=("fw:", "fwd:"),
    )
    is_reply = _message_flag(
        message,
        key="is_reply",
        subject=subject,
        prefixes=("re:",),
    )
    is_escalation = bool(message.get("is_escalation", False)) or _contains_keyword(
        body_text,
        ("escalate", "urgent", "executive", "leadership"),
    )
    event_type = _archive_event_type(
        message=message,
        subject=subject,
        body_text=body_text,
        is_forward=is_forward,
        is_reply=is_reply,
        is_escalation=is_escalation,
    )

    snippet = body_text if include_content else _truncate_snippet(body_text)
    flags = WhatIfArtifactFlags(
        consult_legal_specialist=_contains_keyword(
            " ".join(
                [subject, body_text, " ".join(recipients), " ".join(cc_recipients)]
            ),
            ("legal", "counsel", "attorney", "compliance", "regulatory"),
        ),
        consult_trading_specialist=_contains_keyword(
            " ".join(
                [subject, body_text, " ".join(recipients), " ".join(cc_recipients)]
            ),
            ("trading", "trade", "desk", "market"),
        ),
        has_attachment_reference=_has_attachment_reference(message, body_text),
        is_escalation=is_escalation,
        is_forward=is_forward,
        is_reply=is_reply,
        cc_count=len(cc_recipients),
        to_count=len(recipients),
        to_recipients=recipients,
        cc_recipients=cc_recipients,
        subject=subject,
        norm_subject=subject.lower().strip(),
        body_sha1=str(message.get("body_sha1", "") or ""),
        custodian_id=str(message.get("custodian_id", "") or ""),
        message_id=str(
            message.get("message_id", message.get("id", message.get("mid", ""))) or ""
        ),
        folder=str(message.get("folder", "") or ""),
        source="mail_archive",
    )
    return WhatIfEvent(
        event_id=event_id,
        timestamp=timestamp_text,
        timestamp_ms=timestamp_ms,
        actor_id=actor_id or _fallback_internal_address(organization_domain, "unknown"),
        target_id=recipients[0] if recipients else "",
        event_type=event_type,
        thread_id=thread_id,
        subject=subject,
        snippet=snippet,
        flags=flags,
    )


def _archive_thread_id(thread: dict[str, Any], *, index: int) -> str:
    thread_id = str(thread.get("thread_id", "") or "").strip()
    if thread_id:
        return thread_id
    return f"archive-thread-{index + 1:04d}"


def _archive_thread_subject(thread: dict[str, Any], *, fallback: str) -> str:
    subject = str(thread.get("subject", thread.get("title", "")) or "").strip()
    return subject or fallback


def _archive_subject(message: dict[str, Any], *, fallback: str) -> str:
    subject = str(message.get("subject", message.get("subj", "")) or "").strip()
    return subject or fallback


def _archive_body_text(message: dict[str, Any]) -> str:
    return str(
        message.get(
            "body_text",
            message.get("snippet", message.get("content", "")),
        )
        or ""
    ).strip()


def _archive_event_id(
    *,
    message: dict[str, Any],
    thread_id: str,
    thread_index: int,
    message_index: int,
) -> str:
    for key in ("event_id", "message_id", "id", "mid"):
        value = str(message.get(key, "") or "").strip()
        if value:
            return value
    safe_thread_id = thread_id.replace(" ", "-")
    return f"archive_{safe_thread_id}_{thread_index + 1}_{message_index + 1}"


def _archive_timestamp(
    *,
    message: dict[str, Any],
    thread_index: int,
    message_index: int,
) -> tuple[int, str]:
    for key in ("timestamp", "sent_at", "date", "created_at"):
        value = message.get(key)
        if value:
            return (timestamp_to_ms(value), timestamp_to_text(value))
    raw_time_ms = message.get("time_ms")
    if raw_time_ms not in {None, ""}:
        numeric = safe_int(raw_time_ms)
        return (
            numeric,
            timestamp_to_text(datetime.fromtimestamp(numeric / 1000, tz=timezone.utc)),
        )
    synthetic_time_ms = ((thread_index + 1) * 1_000_000) + ((message_index + 1) * 1_000)
    return (
        synthetic_time_ms,
        timestamp_to_text(
            datetime.fromtimestamp(synthetic_time_ms / 1000, tz=timezone.utc)
        ),
    )


def _recipient_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    normalized = text.replace(";", ",")
    return [item.strip() for item in normalized.split(",") if item.strip()]


def _message_flag(
    message: dict[str, Any],
    *,
    key: str,
    subject: str,
    prefixes: Sequence[str],
) -> bool:
    if bool(message.get(key, False)):
        return True
    lowered = subject.lower().strip()
    return any(lowered.startswith(prefix) for prefix in prefixes)


def _archive_event_type(
    *,
    message: dict[str, Any],
    subject: str,
    body_text: str,
    is_forward: bool,
    is_reply: bool,
    is_escalation: bool,
) -> str:
    explicit = str(message.get("event_type", "") or "").strip().lower()
    if explicit:
        return explicit
    if is_escalation:
        return "escalation"
    if _contains_keyword(" ".join([subject, body_text]), ("approval", "approved")):
        return "approval"
    if _contains_keyword(
        " ".join([subject, body_text]), ("assign", "owner", "handoff")
    ):
        return "assignment"
    if is_forward:
        return "forward"
    if is_reply:
        return "reply"
    return "message"


def _has_attachment_reference(message: dict[str, Any], body_text: str) -> bool:
    if bool(message.get("has_attachment_reference", False)):
        return True
    attachments = message.get("attachments")
    if isinstance(attachments, list) and attachments:
        return True
    attachment_names = message.get("attachment_names")
    if isinstance(attachment_names, list) and attachment_names:
        return True
    return _contains_keyword(
        body_text, ("attach", "attachment", "draft", ".pdf", ".doc")
    )


def _contains_keyword(text: str, keywords: Sequence[str]) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in keywords)


def _truncate_snippet(value: str, *, max_chars: int = 280) -> str:
    cleaned = " ".join(value.split()).strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 1].rstrip() + "…"


def _organization_domain_from_threads(threads: Sequence[dict[str, Any]]) -> str:
    sender_counts: Counter[str] = Counter()
    participant_counts: Counter[str] = Counter()
    for thread in threads:
        if not isinstance(thread, dict):
            continue
        for message in thread.get("messages", []):
            if not isinstance(message, dict):
                continue
            sender_domain = _email_domain(str(message.get("from", "") or ""))
            if sender_domain:
                sender_counts[sender_domain] += 1
                participant_counts[sender_domain] += 1
            for key in ("to", "cc"):
                for recipient in _recipient_list(message.get(key)):
                    domain = _email_domain(recipient)
                    if domain:
                        participant_counts[domain] += 1
    if sender_counts:
        return sorted(
            sender_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )[
            0
        ][0]
    if participant_counts:
        return sorted(
            participant_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )[0][0]
    return ""


def _organization_name_from_domain(domain: str) -> str:
    cleaned = str(domain or "").strip().lower()
    if not cleaned:
        return "Historical Archive"
    token = cleaned.split(".", 1)[0].replace("-", " ").replace("_", " ")
    label = " ".join(part.capitalize() for part in token.split() if part)
    return label or "Historical Archive"


def _fallback_internal_address(domain: str, local_part: str) -> str:
    normalized_domain = str(domain or "").strip().lower()
    if not normalized_domain:
        return f"{local_part}@archive.local"
    return f"{local_part}@{normalized_domain}"


def _email_domain(value: str) -> str:
    email = str(value or "").strip().lower()
    if "@" not in email:
        return ""
    return email.split("@", 1)[1]


def _override_actor_profiles(
    actors: Sequence[WhatIfActorProfile],
    *,
    actor_payload: Sequence[dict[str, Any]],
) -> list[WhatIfActorProfile]:
    directory: dict[str, dict[str, str]] = {}
    for actor in actor_payload:
        if not isinstance(actor, dict):
            continue
        actor_id = str(actor.get("actor_id", actor.get("email", "")) or "").strip()
        if not actor_id:
            continue
        directory[actor_id] = {
            "email": str(actor.get("email", actor_id) or actor_id).strip(),
            "display_name": str(actor.get("display_name", "") or "").strip(),
        }

    updated: list[WhatIfActorProfile] = []
    for actor in actors:
        override = directory.get(actor.actor_id)
        if not override:
            updated.append(actor)
            continue
        updated.append(
            actor.model_copy(
                update={
                    "email": override["email"] or actor.email,
                    "display_name": override["display_name"] or actor.display_name,
                }
            )
        )
    return updated


def load_content_by_event_ids(
    *,
    rosetta_dir: str | Path,
    event_ids: Sequence[str],
) -> dict[str, str]:
    unique_event_ids = sorted(
        {str(item).strip() for item in event_ids if str(item).strip()}
    )
    if not unique_event_ids:
        return {}
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - guarded by dependency
        raise RuntimeError(
            "pyarrow is required for `vei whatif` parquet loading"
        ) from exc

    content_path = (
        Path(rosetta_dir).expanduser().resolve()
        / "enron_rosetta_events_content.parquet"
    )
    if not content_path.exists():
        return {}
    content_rows = pq.read_table(
        content_path,
        columns=["event_id", "content"],
        filters=[("event_id", "in", unique_event_ids)],
    ).to_pylist()
    return {
        str(row.get("event_id", "")): str(row.get("content", "") or "")
        for row in content_rows
        if str(row.get("event_id", "")).strip()
    }


def hydrate_event_snippets(
    *,
    rosetta_dir: str | Path,
    events: Sequence[WhatIfEvent],
) -> list[WhatIfEvent]:
    missing_ids = [event.event_id for event in events if not event.snippet]
    if not missing_ids:
        return list(events)
    content_by_id = load_content_by_event_ids(
        rosetta_dir=rosetta_dir,
        event_ids=missing_ids,
    )
    hydrated: list[WhatIfEvent] = []
    for event in events:
        snippet = content_by_id.get(event.event_id, event.snippet)
        hydrated.append(event.model_copy(update={"snippet": snippet}))
    return hydrated


def build_event(row: dict[str, Any], content: str) -> WhatIfEvent | None:
    event_id = str(row.get("event_id", "")).strip()
    if not event_id:
        return None
    timestamp = row.get("timestamp")
    timestamp_ms = timestamp_to_ms(timestamp)
    timestamp_text = timestamp_to_text(timestamp)
    artifacts = artifact_flags(row.get("artifacts"))
    thread_id = str(row.get("thread_task_id", "") or event_id)
    subject = artifacts.subject or artifacts.norm_subject or thread_id
    return WhatIfEvent(
        event_id=event_id,
        timestamp=timestamp_text,
        timestamp_ms=timestamp_ms,
        actor_id=str(row.get("actor_id", "") or ""),
        target_id=str(row.get("target_id", "") or ""),
        event_type=str(row.get("event_type", "") or ""),
        thread_id=thread_id,
        subject=subject,
        snippet=str(content or ""),
        flags=artifacts,
    )


def artifact_flags(raw: Any) -> WhatIfArtifactFlags:
    if isinstance(raw, str):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {}
    elif isinstance(raw, dict):
        payload = dict(raw)
    else:
        payload = {}

    return WhatIfArtifactFlags(
        consult_legal_specialist=bool(payload.get("consult_legal_specialist", False)),
        consult_trading_specialist=bool(
            payload.get("consult_trading_specialist", False)
        ),
        has_attachment_reference=bool(payload.get("has_attachment_reference", False)),
        is_escalation=bool(payload.get("is_escalation", False)),
        is_forward=bool(payload.get("is_forward", False)),
        is_reply=bool(payload.get("is_reply", False)),
        cc_count=safe_int(payload.get("cc_count")),
        bcc_count=safe_int(payload.get("bcc_count")),
        to_count=safe_int(payload.get("to_count")),
        to_recipients=string_list(payload.get("to_recipients")),
        cc_recipients=string_list(payload.get("cc_recipients")),
        subject=str(payload.get("subject", "") or ""),
        norm_subject=str(payload.get("norm_subject", "") or ""),
        body_sha1=str(payload.get("body_sha1", "") or ""),
        custodian_id=str(payload.get("custodian_id", "") or ""),
        message_id=str(payload.get("message_id", "") or ""),
        folder=str(payload.get("folder", "") or ""),
        source=str(payload.get("source", "") or ""),
    )


def build_thread_summaries(
    events: Sequence[WhatIfEvent],
    *,
    organization_domain: str = ENRON_DOMAIN,
) -> list[WhatIfThreadSummary]:
    buckets: dict[str, dict[str, Any]] = {}
    for event in events:
        bucket = buckets.setdefault(
            event.thread_id,
            {
                "thread_id": event.thread_id,
                "subject": event.subject or event.thread_id,
                "event_count": 0,
                "actor_ids": set(),
                "first_timestamp": event.timestamp,
                "last_timestamp": event.timestamp,
                "legal_event_count": 0,
                "trading_event_count": 0,
                "escalation_event_count": 0,
                "assignment_event_count": 0,
                "approval_event_count": 0,
                "forward_event_count": 0,
                "attachment_event_count": 0,
                "external_recipient_event_count": 0,
                "event_type_counts": Counter(),
            },
        )
        bucket["event_count"] += 1
        bucket["actor_ids"].add(event.actor_id)
        if event.target_id:
            bucket["actor_ids"].add(event.target_id)
        bucket["last_timestamp"] = event.timestamp
        if event.flags.consult_legal_specialist:
            bucket["legal_event_count"] += 1
        if event.flags.consult_trading_specialist:
            bucket["trading_event_count"] += 1
        if event.flags.is_escalation or event.event_type == "escalation":
            bucket["escalation_event_count"] += 1
        if event.event_type == "assignment":
            bucket["assignment_event_count"] += 1
        if event.event_type == "approval":
            bucket["approval_event_count"] += 1
        if event.flags.is_forward:
            bucket["forward_event_count"] += 1
        if event.flags.has_attachment_reference:
            bucket["attachment_event_count"] += 1
        if has_external_recipients(
            event.flags.to_recipients,
            organization_domain=organization_domain,
        ):
            bucket["external_recipient_event_count"] += 1
        bucket["event_type_counts"][event.event_type] += 1

    threads = [
        WhatIfThreadSummary(
            thread_id=payload["thread_id"],
            subject=payload["subject"],
            event_count=payload["event_count"],
            actor_ids=sorted(actor_id for actor_id in payload["actor_ids"] if actor_id),
            first_timestamp=payload["first_timestamp"],
            last_timestamp=payload["last_timestamp"],
            legal_event_count=payload["legal_event_count"],
            trading_event_count=payload["trading_event_count"],
            escalation_event_count=payload["escalation_event_count"],
            assignment_event_count=payload["assignment_event_count"],
            approval_event_count=payload["approval_event_count"],
            forward_event_count=payload["forward_event_count"],
            attachment_event_count=payload["attachment_event_count"],
            external_recipient_event_count=payload["external_recipient_event_count"],
            event_type_counts=dict(payload["event_type_counts"]),
        )
        for payload in buckets.values()
    ]
    return sorted(threads, key=lambda item: (-item.event_count, item.thread_id))


def build_actor_profiles(
    events: Sequence[WhatIfEvent],
    *,
    organization_domain: str = ENRON_DOMAIN,
) -> list[WhatIfActorProfile]:
    buckets: dict[str, dict[str, Any]] = {}
    for event in events:
        touch_actor(
            buckets,
            actor_id=event.actor_id,
            sent=True,
            flagged=event_is_flagged(
                event,
                organization_domain=organization_domain,
            ),
            custodian_id=event.flags.custodian_id,
        )
        touch_actor(
            buckets,
            actor_id=event.target_id,
            received=True,
        )
    actors = [
        WhatIfActorProfile(
            actor_id=actor_id,
            email=actor_id,
            display_name=display_name(actor_id),
            custodian_ids=sorted(payload["custodian_ids"]),
            event_count=payload["event_count"],
            sent_count=payload["sent_count"],
            received_count=payload["received_count"],
            flagged_event_count=payload["flagged_event_count"],
        )
        for actor_id, payload in buckets.items()
        if actor_id
    ]
    return sorted(actors, key=lambda item: (-item.event_count, item.actor_id))


def touch_actor(
    buckets: dict[str, dict[str, Any]],
    *,
    actor_id: str,
    sent: bool = False,
    received: bool = False,
    flagged: bool = False,
    custodian_id: str = "",
) -> None:
    if not actor_id:
        return
    bucket = buckets.setdefault(
        actor_id,
        {
            "event_count": 0,
            "sent_count": 0,
            "received_count": 0,
            "flagged_event_count": 0,
            "custodian_ids": set(),
        },
    )
    bucket["event_count"] += 1
    if sent:
        bucket["sent_count"] += 1
    if received:
        bucket["received_count"] += 1
    if flagged:
        bucket["flagged_event_count"] += 1
    if custodian_id:
        bucket["custodian_ids"].add(custodian_id)


def thread_events(events: Sequence[WhatIfEvent], thread_id: str) -> list[WhatIfEvent]:
    return [
        event
        for event in sorted(events, key=lambda item: (item.timestamp_ms, item.event_id))
        if event.thread_id == thread_id
    ]


def event_by_id(events: Sequence[WhatIfEvent], event_id: str) -> WhatIfEvent | None:
    for event in events:
        if event.event_id == event_id:
            return event
    return None


def choose_branch_event(
    events: Sequence[WhatIfEvent],
    *,
    requested_event_id: str | None,
) -> WhatIfEvent:
    if not events:
        raise ValueError("cannot choose a branch event from an empty thread")
    if requested_event_id:
        selected = event_by_id(events, requested_event_id)
        if selected is None:
            raise ValueError(f"branch event not found in thread: {requested_event_id}")
        return selected
    if len(events) == 1:
        return events[0]
    prioritized = [
        event
        for event in events[:-1]
        if event.flags.is_escalation
        or event.flags.is_forward
        or event.event_type in {"assignment", "approval", "reply"}
    ]
    if prioritized:
        return prioritized[0]
    return events[max(0, (len(events) // 2) - 1)]


def thread_subject(
    threads: Sequence[WhatIfThreadSummary],
    thread_id: str,
    *,
    fallback: str,
) -> str:
    for thread in threads:
        if thread.thread_id == thread_id:
            return thread.subject
    return fallback or thread_id


def event_reference(event: WhatIfEvent) -> WhatIfEventReference:
    return WhatIfEventReference(
        event_id=event.event_id,
        timestamp=event.timestamp,
        actor_id=event.actor_id,
        target_id=event.target_id,
        event_type=event.event_type,
        thread_id=event.thread_id,
        subject=event.subject,
        snippet=event.snippet,
        to_recipients=list(event.flags.to_recipients),
        cc_recipients=list(event.flags.cc_recipients),
        has_attachment_reference=event.flags.has_attachment_reference,
        is_forward=event.flags.is_forward,
        is_reply=event.flags.is_reply,
        is_escalation=event.flags.is_escalation,
    )


def event_reason_labels(
    event: WhatIfEvent,
    *,
    organization_domain: str = ENRON_DOMAIN,
) -> list[str]:
    labels: list[str] = []
    if event.flags.consult_legal_specialist:
        labels.append("legal")
    if event.flags.consult_trading_specialist:
        labels.append("trading")
    if event.flags.has_attachment_reference:
        labels.append("attachment")
    if event.flags.is_forward:
        labels.append("forward")
    if event.flags.is_escalation or event.event_type == "escalation":
        labels.append("escalation")
    if event.event_type == "assignment":
        labels.append("assignment")
    if event.event_type == "approval":
        labels.append("approval")
    if has_external_recipients(
        event.flags.to_recipients,
        organization_domain=organization_domain,
    ):
        labels.append("external_recipient")
    return labels


def event_is_flagged(
    event: WhatIfEvent,
    *,
    organization_domain: str = ENRON_DOMAIN,
) -> bool:
    return bool(
        event_reason_labels(
            event,
            organization_domain=organization_domain,
        )
    )


def search_events(
    world: WhatIfWorld,
    *,
    actor: str | None = None,
    participant: str | None = None,
    thread_id: str | None = None,
    event_type: str | None = None,
    query: str | None = None,
    flagged_only: bool = False,
    limit: int = 20,
) -> WhatIfEventSearchResult:
    actor_token = (actor or "").strip().lower()
    participant_token = (participant or "").strip().lower()
    thread_token = (thread_id or "").strip()
    event_type_token = (event_type or "").strip().lower()
    query_token = (query or "").strip().lower()
    query_terms = _query_terms(query_token)
    effective_limit = max(1, int(limit))
    thread_by_id = {thread.thread_id: thread for thread in world.threads}

    raw_matches: list[tuple[WhatIfEvent, list[str], list[str], int, int]] = []
    total_match_count = 0
    for event in world.events:
        match_reasons: list[str] = []
        if actor_token:
            if actor_token not in event.actor_id.lower():
                continue
            match_reasons.append("actor")
        if participant_token:
            participants = [
                event.actor_id,
                event.target_id,
                *event.flags.to_recipients,
                *event.flags.cc_recipients,
            ]
            if not any(
                participant_token in item.lower() for item in participants if item
            ):
                continue
            match_reasons.append("participant")
        if thread_token:
            if event.thread_id != thread_token:
                continue
            match_reasons.append("thread")
        if event_type_token:
            if event.event_type.lower() != event_type_token:
                continue
            match_reasons.append("event_type")
        if query_terms:
            haystack = " ".join(
                [
                    event.event_id,
                    event.thread_id,
                    event.subject,
                    event.actor_id,
                    display_name(event.actor_id),
                    event.target_id,
                    display_name(event.target_id),
                    " ".join(event.flags.to_recipients),
                    " ".join(display_name(item) for item in event.flags.to_recipients),
                    " ".join(event.flags.cc_recipients),
                    " ".join(display_name(item) for item in event.flags.cc_recipients),
                    event.snippet,
                ]
            ).lower()
            if not all(term in haystack for term in query_terms):
                continue
            match_reasons.append("query")
        reason_labels = event_reason_labels(
            event,
            organization_domain=world.summary.organization_domain,
        )
        if flagged_only and not reason_labels:
            continue
        if flagged_only:
            match_reasons.append("flagged")

        total_match_count += 1
        if len(raw_matches) >= effective_limit:
            continue
        thread = thread_by_id.get(event.thread_id)
        raw_matches.append(
            (
                event,
                match_reasons,
                reason_labels,
                thread.event_count if thread is not None else 0,
                len(thread.actor_ids) if thread is not None else 0,
            )
        )

    if world.source == "enron":
        hydrated_events = hydrate_event_snippets(
            rosetta_dir=world.source_dir,
            events=[event for event, *_ in raw_matches],
        )
    else:
        hydrated_events = [event for event, *_ in raw_matches]
    matches = [
        WhatIfEventMatch(
            event=event_reference(event),
            match_reasons=match_reasons,
            reason_labels=reason_labels,
            thread_event_count=thread_event_count,
            participant_count=participant_count,
        )
        for event, (
            _,
            match_reasons,
            reason_labels,
            thread_event_count,
            participant_count,
        ) in zip(
            hydrated_events,
            raw_matches,
        )
    ]

    filters: dict[str, str | int | bool] = {"limit": effective_limit}
    if actor_token:
        filters["actor"] = actor_token
    if participant_token:
        filters["participant"] = participant_token
    if thread_token:
        filters["thread_id"] = thread_token
    if event_type_token:
        filters["event_type"] = event_type_token
    if query_token:
        filters["query"] = query_token
    if flagged_only:
        filters["flagged_only"] = True
    return WhatIfEventSearchResult(
        source=world.source,
        filters=filters,
        match_count=total_match_count,
        truncated=total_match_count > len(matches),
        matches=matches,
    )


def _query_terms(query: str) -> list[str]:
    if not query:
        return []
    normalized = query.replace("@", " ").replace(".", " ").replace("_", " ").strip()
    parts = [part for part in normalized.split() if len(part) >= 2]
    return parts or [query]


def touches_executive(event: WhatIfEvent) -> bool:
    haystack = " ".join(
        [
            event.actor_id.lower(),
            event.target_id.lower(),
            " ".join(value.lower() for value in event.flags.to_recipients),
            " ".join(value.lower() for value in event.flags.cc_recipients),
        ]
    )
    return any(marker in haystack for marker in EXECUTIVE_MARKERS)


def has_external_recipients(
    recipients: Sequence[str],
    *,
    organization_domain: str = ENRON_DOMAIN,
) -> bool:
    internal_domain = organization_domain.strip().lower()
    for recipient in recipients:
        recipient_domain = _email_domain(recipient)
        if not recipient_domain:
            continue
        if internal_domain and recipient_domain == internal_domain:
            continue
        if not internal_domain and recipient_domain.endswith(".local"):
            continue
        return True
    return False


def matches_custodian_filter(
    event: WhatIfEvent,
    tokens: set[str],
) -> bool:
    if event.flags.custodian_id.lower() in tokens:
        return True
    return event.actor_id.lower() in tokens or event.target_id.lower() in tokens


def resolve_time_window(
    time_window: tuple[str, str] | None,
) -> tuple[int, int] | None:
    if time_window is None:
        return None
    start_raw, end_raw = time_window
    return (parse_time_value(start_raw), parse_time_value(end_raw))


def parse_time_value(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return int(parsed.timestamp() * 1000)


def timestamp_to_ms(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, datetime):
        return int(value.timestamp() * 1000)
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value)
    if not text:
        return 0
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return int(parsed.timestamp() * 1000)


def timestamp_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    text = str(value)
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def display_name(actor_id: str) -> str:
    token = actor_id.split("@", 1)[0].replace(".", " ").replace("_", " ").strip()
    if not token:
        return actor_id
    return " ".join(part.capitalize() for part in token.split())


def safe_int(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if value in (None, ""):
        return []
    return [str(value)]
