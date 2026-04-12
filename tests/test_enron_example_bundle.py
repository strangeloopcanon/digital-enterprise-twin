from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from vei.ui import api as ui_api

EXAMPLE_ROOT = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "examples"
    / "enron-master-agreement-public-context"
)


def test_repo_owned_enron_example_bundle_is_present_and_clean() -> None:
    assert EXAMPLE_ROOT.exists()

    required_paths = [
        EXAMPLE_ROOT / "README.md",
        EXAMPLE_ROOT / "whatif_experiment_overview.md",
        EXAMPLE_ROOT / "whatif_experiment_result.json",
        EXAMPLE_ROOT / "whatif_llm_result.json",
        EXAMPLE_ROOT / "whatif_ejepa_result.json",
        EXAMPLE_ROOT / "workspace" / "vei_project.json",
        EXAMPLE_ROOT / "workspace" / "context_snapshot.json",
        EXAMPLE_ROOT / "workspace" / "whatif_episode_manifest.json",
    ]
    for path in required_paths:
        assert path.exists(), path

    manifest = json.loads(
        (EXAMPLE_ROOT / "workspace" / "whatif_episode_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["source"] == "enron"
    assert manifest["source_dir"] == "not-included-in-repo-example"
    assert manifest["workspace_root"] == "workspace"
    assert manifest["history_message_count"] == 6
    assert manifest["future_event_count"] == 84
    assert [
        item["label"] for item in manifest["public_context"]["financial_snapshots"]
    ] == [
        "FY1998 selected financial data",
        "FY1999 selected financial data",
    ]
    assert manifest["public_context"]["public_news_events"] == []

    for relative_path in (
        "whatif_experiment_result.json",
        "whatif_ejepa_result.json",
        "workspace/whatif_episode_manifest.json",
    ):
        text = (EXAMPLE_ROOT / relative_path).read_text(encoding="utf-8")
        assert "/Users/" not in text

    overview_text = (EXAMPLE_ROOT / "whatif_experiment_overview.md").read_text(
        encoding="utf-8"
    )
    assert "External-send delta: -29" in overview_text
    assert "Predicted risk: 0.983" in overview_text


def test_repo_owned_enron_example_workspace_loads_saved_scene() -> None:
    workspace_root = EXAMPLE_ROOT / "workspace"
    client = TestClient(ui_api.create_ui_app(workspace_root))

    status_response = client.get("/api/workspace/whatif")
    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["available"] is True
    assert status_payload["source"] == "mail_archive"

    historical_response = client.get("/api/workspace/historical")
    assert historical_response.status_code == 200
    historical_payload = historical_response.json()
    assert historical_payload["organization_name"] == "Enron Corporation"

    scene_response = client.post(
        "/api/workspace/whatif/scene",
        json={
            "source": "auto",
            "event_id": historical_payload["branch_event_id"],
            "thread_id": historical_payload["thread_id"],
        },
    )
    assert scene_response.status_code == 200
    scene_payload = scene_response.json()
    assert scene_payload["organization_name"] == "Enron Corporation"
    assert scene_payload["branch_event_id"] == "enron_bcda1b925800af8c"
    assert scene_payload["history_message_count"] == 6
    assert scene_payload["future_event_count"] == 84
    assert [
        item["label"] for item in scene_payload["public_context"]["financial_snapshots"]
    ] == [
        "FY1998 selected financial data",
        "FY1999 selected financial data",
    ]
    assert scene_payload["public_context"]["public_news_events"] == []
