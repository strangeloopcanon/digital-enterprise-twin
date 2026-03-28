from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from vei.world.compiler import _sample_number, compile_scene, load_scene_spec


def test_compile_scene_renders_synthetic_assets() -> None:
    spec = {
        "meta": {"name": "demo", "description": "Procurement flow"},
        "budget": {"cap_usd": 3300, "approval_threshold": 1500},
        "slack": {"initial_message": "Remember to cite sources", "derail_prob": 0.05},
        "vendors": [
            {
                "name": "MacroCompute",
                "price": [3100, 3200],
                "eta_days": [3, 5],
                "templates": ["{vendor} quote ${price}, ETA {eta} days"],
            }
        ],
        "participants": [
            {
                "participant_id": "approver",
                "name": "Sam",
                "role": "manager",
                "email": "sam@example.com",
            }
        ],
        "documents": [
            {
                "doc_id": "DOC-1",
                "title": "Budget Policy",
                "body": "All purchases need approval.",
                "tags": ["policy"],
            }
        ],
        "calendar_events": [
            {
                "event_id": "EVT-1",
                "title": "Kickoff",
                "start_ms": 10_000,
                "end_ms": 11_000,
                "attendees": ["sam@example.com"],
            }
        ],
        "tickets": [
            {
                "ticket_id": "TCK-1",
                "title": "Laptop approval",
                "status": "open",
                "assignee": "approver",
            }
        ],
        "triggers": [
            {"at_ms": 5_000, "target": "slack", "payload": {"text": "Reminder"}},
        ],
    }

    scenario = compile_scene(spec, seed=123)

    assert scenario.budget_cap_usd == 3300
    assert scenario.derail_prob == 0.05
    assert scenario.slack_initial_message.startswith("Remember")
    assert (
        scenario.vendor_reply_variants
        and "MacroCompute" in scenario.vendor_reply_variants[0]
    )

    assert (
        scenario.participants and scenario.participants[0].participant_id == "approver"
    )
    assert scenario.documents and "DOC-1" in scenario.documents
    assert scenario.documents["DOC-1"].title == "Budget Policy"

    assert scenario.calendar_events and scenario.calendar_events[0].event_id == "EVT-1"
    assert scenario.tickets and scenario.tickets["TCK-1"].status == "open"

    assert scenario.metadata and scenario.metadata["name"] == "demo"
    assert scenario.triggers and scenario.triggers[0]["target"] == "slack"


def test_scene_compiler_loaders_and_numeric_helpers_cover_edge_cases(
    tmp_path: Path,
) -> None:
    spec = {
        "meta": {"name": "demo", "description": "Minimal"},
        "budget": {"cap_usd": 1000, "approval_threshold": 500},
        "slack": {},
        "vendors": [{"name": "MacroCompute", "price": [10, 20], "eta_days": [2]}],
        "participants": [],
        "documents": [],
        "calendar_events": [],
        "tickets": [],
        "triggers": [],
    }
    spec_path = tmp_path / "scene.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    json_payload = (
        '{"meta":{"name":"demo-json","description":"Minimal"},'
        '"budget":{"cap_usd":1,"approval_threshold":1},"slack":{},'
        '"vendors":[],"participants":[],"documents":[],"calendar_events":[],'
        '"tickets":[],"triggers":[]}'
    )

    assert load_scene_spec(spec).meta.name == "demo"
    assert load_scene_spec(json_payload).meta.name == "demo-json"
    assert load_scene_spec(spec_path).meta.name == "demo"

    with pytest.raises(ValueError, match="not JSON or path"):
        load_scene_spec("not-json")
    with pytest.raises(TypeError, match="unsupported scene spec payload"):
        load_scene_spec(123)

    scenario = compile_scene(spec, seed=1)
    assert scenario.vendor_reply_variants
    assert scenario.vendor_reply_variants[0].startswith("MacroCompute quote: $")
    assert scenario.vendor_reply_variants[0].endswith("ETA: 2 days.")
    assert scenario.participants is None
    assert scenario.documents is None
    assert scenario.calendar_events is None
    assert scenario.tickets is None

    rng = random.Random(5)
    assert _sample_number(7, rng) == 7.0
    assert _sample_number([3], rng) == 3.0
    sampled = _sample_number([5, 2], rng)
    assert 2.0 <= sampled <= 5.0
    with pytest.raises(ValueError, match="range bounds must be numeric"):
        _sample_number(["a", "b"], rng)
    with pytest.raises(ValueError, match="unsupported numeric source"):
        _sample_number({"bad": True}, rng)
