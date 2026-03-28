from __future__ import annotations

import json
from pathlib import Path

from vei.visualization.api import (
    _shorten,
    build_flow_steps,
    discover_question,
    flow_channel_from_focus,
    flow_channel_from_tool,
    flow_events_from_trace_record,
    flow_events_from_transcript_entry,
    load_flow_dataset,
    load_trace,
    load_transcript,
)


def test_visualization_loaders_support_json_and_jsonl(tmp_path: Path) -> None:
    jsonl_path = tmp_path / "trace.jsonl"
    jsonl_path.write_text(
        "\n".join(
            [
                json.dumps({"type": "call", "tool": "docs.read"}),
                json.dumps({"type": "event", "target": "world"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    json_path = tmp_path / "transcript.json"
    json_path.write_text(
        json.dumps(
            [{"llm_plan": "Inspect source"}, {"action": {"tool": "mail.compose"}}]
        ),
        encoding="utf-8",
    )

    assert load_trace(jsonl_path)[0]["tool"] == "docs.read"
    assert load_transcript(json_path)[1]["action"]["tool"] == "mail.compose"


def test_visualization_discovers_question_in_parent_summary(tmp_path: Path) -> None:
    run_dir = tmp_path / "nested" / "run"
    run_dir.mkdir(parents=True)
    (tmp_path / "nested" / "summary.txt").write_text(
        "Task: Figure out the renewal blocker.\nOther: ignored\n",
        encoding="utf-8",
    )

    assert discover_question(run_dir) == "Figure out the renewal blocker."
    assert discover_question(tmp_path / "missing") is None


def test_visualization_event_builders_cover_trace_and_transcript_variants() -> None:
    assert flow_channel_from_tool("slack.send_message") == "Slack"
    assert flow_channel_from_tool("unknown.tool") == "Misc"
    assert flow_channel_from_focus("salesforce") == "CRM"
    assert flow_channel_from_focus(None) == "Misc"
    assert _shorten("short text", 20) == "short text"
    assert _shorten("x" * 8, 5) == "xxxx…"

    plan_events = flow_events_from_transcript_entry(
        {"llm_plan": "Plan out next steps", "meta": {"time_ms": 10}}
    )
    action_events = flow_events_from_transcript_entry(
        {
            "action": {"tool": "mail.compose", "to": "ops@example.com"},
            "meta": {"time_ms": 20},
        }
    )
    observation_events = flow_events_from_transcript_entry(
        {
            "observation": {
                "focus": "docs",
                "summary": "Observed the operator runbook.",
                "time_ms": 30,
            }
        }
    )
    trace_call_events = flow_events_from_trace_record(
        {
            "type": "call",
            "tool": "slack.send_message",
            "args": {"channel": "#ops", "text": "Budget is approved."},
            "time_ms": 40,
        }
    )
    trace_event_events = flow_events_from_trace_record(
        {
            "type": "event",
            "target": "identity",
            "payload": {"actor": "maya.ops"},
            "time_ms": 50,
        }
    )

    assert plan_events[0]["channel"] == "Plan"
    assert action_events[0]["channel"] == "Mail"
    assert observation_events[0]["channel"] == "Docs"
    assert trace_call_events[0]["channel"] == "Slack"
    assert trace_event_events[0]["channel"] == "World"
    assert flow_events_from_trace_record({"type": "noop"}) == []


def test_visualization_load_flow_dataset_prefers_trace_and_builds_step_chain(
    tmp_path: Path,
) -> None:
    trace_dir = tmp_path / "trace_run"
    trace_dir.mkdir()
    (trace_dir / "summary.txt").write_text(
        "Task: Handle the procurement escalation.\n",
        encoding="utf-8",
    )
    (trace_dir / "trace.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "call",
                        "tool": "browser.read",
                        "args": {"url": "https://example.com"},
                        "time_ms": 100,
                    }
                ),
                json.dumps(
                    {
                        "type": "call",
                        "tool": "docs.read",
                        "args": {"doc_id": "RUNBOOK-1"},
                        "time_ms": 200,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    dataset = load_flow_dataset(trace_dir)
    assert dataset.source == "trace"
    assert dataset.question == "Handle the procurement escalation."
    assert [step.channel for step in dataset.steps] == ["Browser", "Docs"]
    assert dataset.steps[0].prev_channel == "Plan"
    assert dataset.steps[1].prev_channel == "Browser"

    transcript_dir = tmp_path / "transcript_run"
    transcript_dir.mkdir()
    (tmp_path / "summary.txt").write_text(
        "Task: Coordinate the customer update.\n",
        encoding="utf-8",
    )
    (transcript_dir / "transcript.json").write_text(
        json.dumps(
            [
                {"llm_plan": "Review the latest state", "meta": {"time_ms": 5}},
                {
                    "action": {
                        "tool": "slack.send_message",
                        "channel": "#ops",
                        "text": "Sharing the customer-safe update.",
                    },
                    "meta": {"time_ms": 15},
                },
            ]
        ),
        encoding="utf-8",
    )

    transcript_dataset = load_flow_dataset(transcript_dir)
    assert transcript_dataset.source == "transcript"
    assert transcript_dataset.question == "Coordinate the customer update."
    assert [step.channel for step in transcript_dataset.steps] == ["Plan", "Slack"]

    steps = build_flow_steps(
        [
            {
                "channel": "Mail",
                "label": "Draft email",
                "tool": "mail.compose",
                "time_ms": 10,
            },
            {
                "channel": "CRM",
                "label": "Log note",
                "tool": "crm.create",
                "time_ms": 20,
            },
        ]
    )
    assert steps[0].prev_channel == "Plan"
    assert steps[1].prev_channel == "Mail"
