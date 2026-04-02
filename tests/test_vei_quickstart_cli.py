from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from vei.cli.vei import app
from vei.cli import vei_quickstart
from vei.workspace.api import create_workspace_from_template


def test_quickstart_reports_invalid_live_demo_combo(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner = CliRunner()
    root = tmp_path / "quickstart_workspace"

    fake_state = SimpleNamespace(
        mission=SimpleNamespace(mission_name="service_day_collision"),
        run_id="human_play_123",
    )

    monkeypatch.setattr(
        "vei.playable.prepare_playable_workspace",
        lambda *args, **kwargs: fake_state,
    )
    monkeypatch.setattr(
        vei_quickstart,
        "_ensure_twin_bundle",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ValueError("mirror demo mode requires connector_mode='sim'")
        ),
    )

    result = runner.invoke(
        app,
        [
            "quickstart",
            "run",
            "--world",
            "service_ops",
            "--root",
            str(root),
            "--mirror-demo",
            "--connector-mode",
            "live",
            "--no-baseline",
        ],
    )

    assert result.exit_code == 2
    assert "mirror demo mode requires connector_mode='sim'" in result.output
    assert "Traceback" not in result.output


def test_ensure_twin_bundle_tracks_custom_ports_and_preserves_token(
    tmp_path: Path,
) -> None:
    root = tmp_path / "quickstart_workspace"
    create_workspace_from_template(
        root=root,
        source_kind="vertical",
        source_ref="service_ops",
        overwrite=True,
    )

    vei_quickstart._ensure_twin_bundle(
        root,
        "service_ops",
        studio_port=3311,
        gateway_port=3312,
        connector_mode="sim",
        mirror_demo=True,
        mirror_demo_interval_ms=900,
    )

    manifest_path = root / "twin_manifest.json"
    first_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    first_token = first_manifest["gateway"]["auth_token"]

    assert first_manifest["gateway"]["host"] == "127.0.0.1"
    assert first_manifest["gateway"]["port"] == 3312
    assert "--port 3311" in first_manifest["gateway"]["ui_command"]

    vei_quickstart._ensure_twin_bundle(
        root,
        "service_ops",
        studio_port=4411,
        gateway_port=4412,
        connector_mode="sim",
        mirror_demo=True,
        mirror_demo_interval_ms=900,
    )

    second_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert second_manifest["gateway"]["auth_token"] == first_token
    assert second_manifest["gateway"]["port"] == 4412
    assert "--port 4411" in second_manifest["gateway"]["ui_command"]
