from __future__ import annotations

import json
from pathlib import Path

import typer.testing

from vei.benchmark.api import run_benchmark_batch
from vei.benchmark.models import BenchmarkCaseSpec
from vei.cli.vei_release import app as release_app
from vei.data.rollout import rollout_procurement
from vei.release.api import (
    export_dataset_release,
    run_nightly_release,
    snapshot_benchmark_release,
)


def test_export_dataset_release_writes_manifest_and_checksums(tmp_path: Path) -> None:
    dataset = rollout_procurement(episodes=1, seed=123, scenario_name="multi_channel")
    input_path = tmp_path / "rollout.json"
    input_path.write_text(json.dumps(dataset.model_dump(), indent=2), encoding="utf-8")

    result = export_dataset_release(
        input_path=input_path,
        release_root=tmp_path / "releases",
        version="vtest",
        label="rollout",
    )

    assert result.manifest.kind == "dataset"
    assert result.manifest.metadata["events"] > 0
    assert (result.release_dir / "CHECKSUMS.txt").exists()
    assert (result.release_dir / "data" / "rollout.json").exists()


def test_snapshot_benchmark_release_copies_run_tree(tmp_path: Path) -> None:
    benchmark_dir = tmp_path / "benchmark_run"
    run_benchmark_batch(
        [
            BenchmarkCaseSpec(
                runner="scripted",
                scenario_name="multi_channel",
                seed=321,
                artifacts_dir=benchmark_dir / "multi_channel",
                score_mode="email",
            )
        ],
        run_id="bench-v1",
        output_dir=benchmark_dir,
    )

    result = snapshot_benchmark_release(
        benchmark_dir=benchmark_dir,
        release_root=tmp_path / "releases",
        version="bench-v1",
        label="scripted",
    )

    assert result.manifest.kind == "benchmark"
    assert (result.release_dir / "snapshot" / "aggregate_results.json").exists()
    assert any(
        item.path.endswith("benchmark_summary.json")
        for item in result.manifest.artifacts
    )


def test_run_nightly_release_creates_dataset_and_benchmark_releases(
    tmp_path: Path,
) -> None:
    result = run_nightly_release(
        release_root=tmp_path / "releases",
        workspace_root=tmp_path / "workspace",
        version="nightly-v1",
        seed=77,
        environment_count=2,
        scenarios_per_environment=2,
        rollout_episodes=1,
        benchmark_scenarios=["multi_channel"],
    )

    assert result.manifest.kind == "nightly"
    assert result.corpus_release.release_dir.exists()
    assert result.rollout_release.release_dir.exists()
    assert result.benchmark_release.release_dir.exists()
    assert (result.corpus_release.release_dir / "data" / "filter_report.json").exists()
    summary = json.loads(
        (result.release_dir / "summary.json").read_text(encoding="utf-8")
    )
    assert summary["benchmark_release"]["kind"] == "benchmark"


def test_vei_release_cli_nightly(tmp_path: Path) -> None:
    runner = typer.testing.CliRunner()
    result = runner.invoke(
        release_app,
        [
            "nightly",
            "--release-root",
            str(tmp_path / "releases"),
            "--workspace-root",
            str(tmp_path / "workspace"),
            "--version",
            "nightly-cli",
            "--environments",
            "2",
            "--scenarios-per-environment",
            "2",
            "--rollout-episodes",
            "1",
            "--benchmark-scenario",
            "multi_channel",
        ],
    )

    assert result.exit_code == 0, result.output
    assert (
        tmp_path / "releases" / "nightly" / "nightly-cli" / "manifest.json"
    ).exists()
