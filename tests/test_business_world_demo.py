from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from vei.cli.vei import app
from vei.verticals import (
    BusinessWorldDemoSpec,
    load_business_world_demo_bundle,
    prepare_business_world_demo,
)


def test_prepare_business_world_demo_writes_bundle(tmp_path: Path) -> None:
    bundle = prepare_business_world_demo(
        BusinessWorldDemoSpec(
            root=tmp_path / "showcase",
        )
    )

    assert bundle.manifest_path.exists()
    assert bundle.guide_path.exists()
    assert bundle.story.vertical_name == "service_ops"
    assert bundle.story.story_manifest_path.exists()

    loaded = load_business_world_demo_bundle(bundle.root)
    assert loaded.run_id == "business_world_demo"
    assert loaded.sections[0].section_id == "live_world"

    guide = bundle.guide_path.read_text(encoding="utf-8")
    assert "VEI Business World Demo" in guide
    assert (
        "python -m vei.cli.vei quickstart run --world service_ops --governor-demo"
        in guide
    )
    assert "Historical Capstone" not in guide


def test_showcase_business_world_command_generates_bundle(tmp_path: Path) -> None:
    runner = CliRunner()
    root = tmp_path / "showcase_cli"

    result = runner.invoke(
        app,
        [
            "showcase",
            "business-world",
            "--root",
            str(root),
            "--run-id",
            "demo_bundle",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["run_id"] == "demo_bundle"
    assert payload["story"]["vertical_name"] == "service_ops"
    assert "historical_capstone" not in payload

    bundle_root = root / "demo_bundle"
    assert (bundle_root / "business_world_demo_manifest.json").exists()
    assert (bundle_root / "business_world_demo_guide.md").exists()
    assert (bundle_root / "service_ops_story" / "story_manifest.json").exists()
    assert (bundle_root / "service_ops_story" / "presentation_guide.md").exists()
