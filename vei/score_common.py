from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


def trace_artifact_path(artifacts_dir: str | Path) -> Path:
    return Path(artifacts_dir) / "trace.jsonl"


def load_trace_records(artifacts_dir: str | Path) -> list[dict[str, Any]]:
    trace_path = trace_artifact_path(artifacts_dir)
    if not trace_path.exists():
        return []

    records: list[dict[str, Any]] = []
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records


def load_json_artifact(
    artifacts_dir: str | Path,
    filename: str,
) -> dict[str, Any]:
    path = Path(artifacts_dir) / filename
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def trace_summary(records: list[dict[str, Any]]) -> dict[str, int]:
    calls = [record for record in records if record.get("type") == "call"]
    max_time = max((int(record.get("time_ms", 0)) for record in records), default=0)
    return {
        "steps_taken": len(calls),
        "time_elapsed_ms": max_time,
    }


def build_score_envelope(
    *,
    success: bool,
    composite_score: float | None = None,
    costs: Mapping[str, Any] | None = None,
    dimensions: Mapping[str, Any] | None = None,
    steps_taken: int | None = None,
    time_elapsed_ms: int | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"success": success}
    if composite_score is not None:
        payload["composite_score"] = round(float(composite_score), 3)
    if costs is not None:
        payload["costs"] = dict(costs)
    if dimensions is not None:
        payload["dimensions"] = dict(dimensions)
    if steps_taken is not None:
        payload["steps_taken"] = int(steps_taken)
    if time_elapsed_ms is not None:
        payload["time_elapsed_ms"] = int(time_elapsed_ms)
    if extra:
        payload.update(dict(extra))
    return payload
