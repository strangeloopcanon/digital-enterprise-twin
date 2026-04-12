from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from vei.whatif import (
    build_branch_point_benchmark,
    build_saved_decision_scene,
    load_episode_manifest,
    load_world,
    materialize_episode,
)
from vei.whatif.api import _allowed_thread_participants, _llm_counterfactual_prompt
from vei.whatif.models import (
    WhatIfPublicContext,
    WhatIfPublicFinancialSnapshot,
    WhatIfPublicNewsEvent,
    WhatIfResearchCandidate,
    WhatIfResearchCase,
    WhatIfResearchPack,
)
from vei.whatif.public_context import (
    load_enron_public_context,
    public_context_prompt_lines,
    slice_public_context_to_branch,
)


def _write_public_context_rosetta_fixture(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    metadata_rows = [
        {
            "event_id": "evt-200",
            "timestamp": "2001-04-17T14:00:00Z",
            "actor_id": "vince.kaminski@enron.com",
            "target_id": "sara.shackleton@enron.com",
            "event_type": "message",
            "thread_task_id": "thr-public-context",
            "artifacts": json.dumps(
                {
                    "subject": "Q1 numbers follow-up",
                    "to_recipients": ["sara.shackleton@enron.com"],
                    "to_count": 1,
                }
            ),
        },
        {
            "event_id": "evt-201",
            "timestamp": "2001-05-03T09:00:00Z",
            "actor_id": "jeff.skilling@enron.com",
            "target_id": "outside@lawfirm.com",
            "event_type": "message",
            "thread_task_id": "thr-public-context",
            "artifacts": json.dumps(
                {
                    "subject": "Draft term sheet",
                    "to_recipients": ["outside@lawfirm.com"],
                    "to_count": 1,
                    "has_attachment_reference": True,
                }
            ),
        },
        {
            "event_id": "evt-202",
            "timestamp": "2001-05-03T11:00:00Z",
            "actor_id": "sara.shackleton@enron.com",
            "target_id": "jeff.skilling@enron.com",
            "event_type": "reply",
            "thread_task_id": "thr-public-context",
            "artifacts": json.dumps(
                {
                    "subject": "Draft term sheet",
                    "to_recipients": ["jeff.skilling@enron.com"],
                    "to_count": 1,
                    "is_reply": True,
                }
            ),
        },
    ]
    content_rows = [
        {"event_id": "evt-200", "content": "Flagging the quarter numbers for review."},
        {"event_id": "evt-201", "content": "Sending the outside draft today."},
        {"event_id": "evt-202", "content": "Replying with legal concerns."},
    ]
    pq.write_table(
        pa.Table.from_pylist(metadata_rows),
        root / "enron_rosetta_events_metadata.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist(content_rows),
        root / "enron_rosetta_events_content.parquet",
    )


def _public_context_research_pack() -> WhatIfResearchPack:
    return WhatIfResearchPack(
        pack_id="fixture_public_context_pack",
        title="Fixture Public Context Pack",
        summary="Held-out case that exercises Enron public context slicing.",
        objective_pack_ids=[
            "contain_exposure",
            "reduce_delay",
            "protect_relationship",
        ],
        rollout_seeds=[42042],
        cases=[
            WhatIfResearchCase(
                case_id="public_context_case",
                title="Public Context Case",
                event_id="evt-201",
                thread_id="thr-public-context",
                summary="A branch point with dated public company context.",
                candidates=[
                    WhatIfResearchCandidate(
                        candidate_id="hold_internal",
                        label="Hold internal",
                        prompt="Keep the draft inside Enron and route it through legal review.",
                    ),
                    WhatIfResearchCandidate(
                        candidate_id="narrow_status",
                        label="Narrow status",
                        prompt="Send a short status update outside without the draft.",
                    ),
                    WhatIfResearchCandidate(
                        candidate_id="broad_send",
                        label="Broad send",
                        prompt="Send the draft now and widen the outside loop.",
                    ),
                ],
            )
        ],
    )


def test_load_enron_public_context_slices_world_window() -> None:
    context = load_enron_public_context(
        window_start="2001-04-01T00:00:00Z",
        window_end="2001-05-31T23:59:59Z",
    )

    assert [snapshot.snapshot_id for snapshot in context.financial_snapshots] == [
        "q1_2001_earnings_release"
    ]
    assert [event.event_id for event in context.public_news_events] == [
        "cliff_baxter_resignation"
    ]


def test_load_enron_public_context_soft_fails_when_fixture_is_unavailable(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "vei.whatif.public_context.resources.files",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError("missing")),
    )

    context = load_enron_public_context(
        window_start="2001-04-01T00:00:00Z",
        window_end="2001-05-31T23:59:59Z",
    )

    assert context.pack_name == "enron_public_context"
    assert context.financial_snapshots == []
    assert context.public_news_events == []


def test_public_context_branch_slice_sorts_items_before_prompt_truncation() -> None:
    context = WhatIfPublicContext(
        pack_name="enron_public_context",
        financial_snapshots=[
            WhatIfPublicFinancialSnapshot(
                snapshot_id="later_financial",
                as_of="2001-05-01T00:00:00Z",
                kind="quarterly",
                label="Later financial checkpoint",
                summary="Later financial summary.",
            ),
            WhatIfPublicFinancialSnapshot(
                snapshot_id="earlier_financial",
                as_of="2001-04-01T00:00:00Z",
                kind="quarterly",
                label="Earlier financial checkpoint",
                summary="Earlier financial summary.",
            ),
        ],
        public_news_events=[
            WhatIfPublicNewsEvent(
                event_id="later_news",
                timestamp="2001-05-03T00:00:00Z",
                category="press",
                headline="Later news checkpoint",
                summary="Later news summary.",
            ),
            WhatIfPublicNewsEvent(
                event_id="earlier_news",
                timestamp="2001-04-17T00:00:00Z",
                category="press",
                headline="Earlier news checkpoint",
                summary="Earlier news summary.",
            ),
        ],
    )

    sliced = slice_public_context_to_branch(
        context,
        branch_timestamp="2001-05-03T09:00:00Z",
    )
    assert sliced is not None
    assert [snapshot.snapshot_id for snapshot in sliced.financial_snapshots] == [
        "earlier_financial",
        "later_financial",
    ]
    assert [event.event_id for event in sliced.public_news_events] == [
        "earlier_news",
        "later_news",
    ]

    prompt_lines = public_context_prompt_lines(
        sliced,
        max_financial=1,
        max_news=1,
    )

    assert any("Later financial checkpoint" in line for line in prompt_lines)
    assert not any("Earlier financial checkpoint" in line for line in prompt_lines)
    assert any("Later news checkpoint" in line for line in prompt_lines)
    assert not any("Earlier news checkpoint" in line for line in prompt_lines)


def test_load_world_materialize_episode_and_saved_scene_round_trip_public_context(
    tmp_path: Path,
) -> None:
    rosetta_dir = tmp_path / "rosetta"
    _write_public_context_rosetta_fixture(rosetta_dir)

    world = load_world(source="enron", rosetta_dir=rosetta_dir)
    materialization = materialize_episode(
        world,
        root=tmp_path / "episode",
        event_id="evt-201",
    )
    manifest = load_episode_manifest(materialization.workspace_root)
    scene = build_saved_decision_scene(materialization.workspace_root)
    snapshot_payload = json.loads(
        materialization.context_snapshot_path.read_text(encoding="utf-8")
    )

    assert world.public_context is not None
    assert [
        snapshot.snapshot_id for snapshot in world.public_context.financial_snapshots
    ] == ["q1_2001_earnings_release"]
    assert [event.event_id for event in world.public_context.public_news_events] == [
        "cliff_baxter_resignation"
    ]
    assert manifest.public_context is not None
    assert [
        snapshot.snapshot_id for snapshot in manifest.public_context.financial_snapshots
    ] == ["q1_2001_earnings_release"]
    assert [event.event_id for event in manifest.public_context.public_news_events] == [
        "cliff_baxter_resignation"
    ]
    assert scene.public_context is not None
    assert [event.event_id for event in scene.public_context.public_news_events] == [
        "cliff_baxter_resignation"
    ]
    assert (
        snapshot_payload["metadata"]["whatif"]["public_context"]["public_news_events"][
            0
        ]["event_id"]
        == "cliff_baxter_resignation"
    )


def test_llm_prompt_only_includes_public_facts_known_by_branch_date(
    tmp_path: Path,
) -> None:
    rosetta_dir = tmp_path / "rosetta"
    _write_public_context_rosetta_fixture(rosetta_dir)

    world = load_world(source="enron", rosetta_dir=rosetta_dir)
    materialization = materialize_episode(
        world,
        root=tmp_path / "episode",
        event_id="evt-201",
    )
    manifest = load_episode_manifest(materialization.workspace_root)
    context = json.loads(
        materialization.context_snapshot_path.read_text(encoding="utf-8")
    )
    allowed_actors, allowed_recipients = _allowed_thread_participants(
        context=context,
        manifest=manifest,
    )

    prompt = _llm_counterfactual_prompt(
        context=context,
        manifest=manifest,
        prompt="Keep the draft inside Enron.",
        allowed_actors=allowed_actors,
        allowed_recipients=allowed_recipients,
    )

    assert "Q1 2001 earnings release" in prompt
    assert "Vice chairman Cliff Baxter resigned" in prompt
    assert "Q2 2001 earnings release" not in prompt
    assert "third-quarter loss" not in prompt


def test_benchmark_dossier_includes_branch_filtered_public_context(
    tmp_path: Path,
    monkeypatch,
) -> None:
    rosetta_dir = tmp_path / "rosetta"
    _write_public_context_rosetta_fixture(rosetta_dir)
    world = load_world(source="enron", rosetta_dir=rosetta_dir)
    pack = _public_context_research_pack()

    monkeypatch.setattr(
        "vei.whatif.benchmark.get_research_pack",
        lambda _pack_id: pack,
    )

    result = build_branch_point_benchmark(
        world,
        artifacts_root=tmp_path / "benchmark_artifacts",
        label="public_context_benchmark",
        heldout_pack_id="fixture_public_context_pack",
    )
    dossier = (
        result.artifacts.dossier_root
        / "public_context_case"
        / "minimize_enterprise_risk.md"
    ).read_text(encoding="utf-8")

    assert result.cases[0].public_context is not None
    assert "## Public Company Context" in dossier
    assert "Q1 2001 earnings release" in dossier
    assert "Vice chairman Cliff Baxter resigned" in dossier
    assert "Q2 2001 earnings release" not in dossier


def test_non_enron_world_has_no_public_context(tmp_path: Path) -> None:
    archive_path = tmp_path / "mail_archive.json"
    archive_path.write_text(
        json.dumps(
            {
                "organization_name": "Py Corp",
                "organization_domain": "pycorp.example.com",
                "threads": [
                    {
                        "thread_id": "py-thread",
                        "subject": "Draft note",
                        "messages": [
                            {
                                "message_id": "py-msg-001",
                                "from": "emma@pycorp.example.com",
                                "to": "legal@pycorp.example.com",
                                "subject": "Draft note",
                                "body_text": "Please review.",
                                "timestamp": "2026-03-01T09:00:00Z",
                            }
                        ],
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    world = load_world(source="mail_archive", source_dir=archive_path)

    assert world.public_context is None
