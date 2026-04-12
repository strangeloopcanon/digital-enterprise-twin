from __future__ import annotations

import json
from pathlib import Path


def test_enron_public_context_fixture_is_present_and_cross_referenced() -> None:
    fixture_root = (
        Path(__file__).resolve().parents[1]
        / "vei"
        / "whatif"
        / "fixtures"
        / "enron_public_context"
    )
    package_payload = json.loads(
        (fixture_root / "package.json").read_text(encoding="utf-8")
    )
    dataset_payload = json.loads(
        (fixture_root / "enron_public_context_v1.json").read_text(encoding="utf-8")
    )

    source_ids = {source["source_id"] for source in package_payload["sources"]}
    assert package_payload["name"] == "enron_public_context"
    assert dataset_payload["pack_name"] == "enron_public_context"
    assert len(package_payload["sources"]) == 7
    assert len(dataset_payload["financial_snapshots"]) == 7
    assert len(dataset_payload["public_news_events"]) == 7
    assert dataset_payload["financial_snapshots"][0]["as_of"] == "1998-12-31T00:00:00Z"
    assert (
        dataset_payload["public_news_events"][-1]["timestamp"] == "2001-12-02T00:00:00Z"
    )

    for source in package_payload["sources"]:
        path = fixture_root / source["relative_path"]
        assert path.exists(), f"missing source file: {path}"
        assert path.stat().st_size > 0

    for snapshot in dataset_payload["financial_snapshots"]:
        assert snapshot["source_ids"]
        assert set(snapshot["source_ids"]).issubset(source_ids)

    for event in dataset_payload["public_news_events"]:
        assert event["source_ids"]
        assert set(event["source_ids"]).issubset(source_ids)
