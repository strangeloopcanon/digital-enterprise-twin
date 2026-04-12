from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

EXAMPLE_PLACEHOLDER = "not-included-in-repo-example"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _rewrite_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    updated = dict(payload)
    updated["source_dir"] = EXAMPLE_PLACEHOLDER
    updated["workspace_root"] = "workspace"
    return updated


def _rewrite_forecast_result(payload: dict[str, Any]) -> dict[str, Any]:
    updated = dict(payload)
    artifacts = updated.get("artifacts")
    if isinstance(artifacts, dict):
        updated["artifacts"] = {key: EXAMPLE_PLACEHOLDER for key in artifacts.keys()}
    return updated


def _rewrite_experiment_result(payload: dict[str, Any]) -> dict[str, Any]:
    updated = dict(payload)
    materialization = dict(updated.get("materialization") or {})
    if materialization:
        materialization["manifest_path"] = "workspace/whatif_episode_manifest.json"
        materialization["bundle_path"] = EXAMPLE_PLACEHOLDER
        materialization["context_snapshot_path"] = "workspace/context_snapshot.json"
        materialization["baseline_dataset_path"] = (
            "workspace/whatif_baseline_dataset.json"
        )
        materialization["workspace_root"] = "workspace"
        updated["materialization"] = materialization

    baseline = dict(updated.get("baseline") or {})
    if baseline:
        baseline["workspace_root"] = "workspace"
        baseline["baseline_dataset_path"] = "workspace/whatif_baseline_dataset.json"
        updated["baseline"] = baseline

    forecast_result = updated.get("forecast_result")
    if isinstance(forecast_result, dict):
        updated["forecast_result"] = _rewrite_forecast_result(forecast_result)

    artifacts = dict(updated.get("artifacts") or {})
    if artifacts:
        artifacts["root"] = "."
        artifacts["result_json_path"] = "whatif_experiment_result.json"
        artifacts["overview_markdown_path"] = "whatif_experiment_overview.md"
        artifacts["llm_json_path"] = "whatif_llm_result.json"
        artifacts["forecast_json_path"] = "whatif_ejepa_result.json"
        updated["artifacts"] = artifacts
    return updated


def package_example(source_root: Path, output_root: Path) -> None:
    workspace_root = source_root / "workspace"
    target_workspace = output_root / "workspace"
    if output_root.exists():
        shutil.rmtree(output_root)
    target_workspace.mkdir(parents=True, exist_ok=True)

    _copy_file(
        source_root / "whatif_experiment_overview.md",
        output_root / "whatif_experiment_overview.md",
    )
    _copy_file(
        source_root / "whatif_llm_result.json", output_root / "whatif_llm_result.json"
    )
    _write_json(
        output_root / "whatif_ejepa_result.json",
        _rewrite_forecast_result(_read_json(source_root / "whatif_ejepa_result.json")),
    )
    _write_json(
        output_root / "whatif_experiment_result.json",
        _rewrite_experiment_result(
            _read_json(source_root / "whatif_experiment_result.json")
        ),
    )

    for relative_path in (
        "context_snapshot.json",
        "whatif_baseline_dataset.json",
        "vei_project.json",
        "contracts/default.contract.json",
        "scenarios/default.json",
        "imports/source_registry.json",
        "imports/source_sync_history.json",
        "runs/index.json",
        "sources/blueprint_asset.json",
    ):
        _copy_file(workspace_root / relative_path, target_workspace / relative_path)

    _write_json(
        target_workspace / "whatif_episode_manifest.json",
        _rewrite_manifest(_read_json(workspace_root / "whatif_episode_manifest.json")),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Package the repo-owned Enron Master Agreement example bundle."
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path(
            "_vei_out/whatif_repo_examples/master_agreement_internal_review_public_context_20260412"
        ),
        help="Fresh local what-if experiment root to package.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("docs/examples/enron-master-agreement-public-context"),
        help="Tracked repo path for the packaged example bundle.",
    )
    args = parser.parse_args()
    package_example(
        args.source_root.expanduser().resolve(), args.output_root.expanduser().resolve()
    )


if __name__ == "__main__":
    main()
