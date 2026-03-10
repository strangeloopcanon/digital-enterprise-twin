from __future__ import annotations

import json
from pathlib import Path

import typer.testing

from vei.benchmark.api import (
    get_benchmark_family_manifest,
    list_benchmark_family_manifest,
    resolve_scenarios,
    run_benchmark_batch,
    run_benchmark_case,
    score_enterprise_dimensions,
)
from vei.benchmark.models import BenchmarkCaseSpec
from vei.cli.vei_eval import app as eval_app
from vei.cli.vei_report import load_all_results
from vei.data.rollout import rollout_procurement
from vei.world.api import create_world_session, get_catalog_scenario


def test_run_benchmark_case_scripted_writes_kernel_diagnostics(tmp_path: Path) -> None:
    artifacts = tmp_path / "scripted_case"
    spec = BenchmarkCaseSpec(
        runner="scripted",
        scenario_name="multi_channel",
        seed=101,
        artifacts_dir=artifacts,
        score_mode="email",
    )

    result = run_benchmark_case(spec)

    assert result.status == "ok"
    assert result.diagnostics.branch == "multi_channel"
    assert result.diagnostics.snapshot_count >= 2
    assert "dimensions" in result.score
    assert (artifacts / "benchmark_result.json").exists()
    assert (artifacts / "score.json").exists()


def test_run_benchmark_case_overlay_replay_uses_dataset_events(tmp_path: Path) -> None:
    dataset = rollout_procurement(episodes=1, seed=222, scenario_name="multi_channel")
    dataset_path = tmp_path / "overlay_dataset.json"
    dataset_path.write_text(
        json.dumps(dataset.model_dump(), indent=2), encoding="utf-8"
    )

    artifacts = tmp_path / "overlay_case"
    spec = BenchmarkCaseSpec(
        runner="scripted",
        scenario_name="multi_channel",
        seed=222,
        artifacts_dir=artifacts,
        dataset_path=dataset_path,
        replay_mode="overlay",
        score_mode="email",
    )

    result = run_benchmark_case(spec)

    assert result.status == "ok"
    assert result.diagnostics.replay_mode == "overlay"
    assert result.diagnostics.replay_scheduled > 0


def test_run_benchmark_batch_writes_report_compatible_aggregate(tmp_path: Path) -> None:
    run_dir = tmp_path / "batch"
    batch = run_benchmark_batch(
        [
            BenchmarkCaseSpec(
                runner="scripted",
                scenario_name="multi_channel",
                seed=303,
                artifacts_dir=run_dir / "multi_channel",
                score_mode="email",
            )
        ],
        run_id="scripted_suite",
        output_dir=run_dir,
    )

    assert batch.summary.total_runs == 1
    aggregate = json.loads(
        (run_dir / "aggregate_results.json").read_text(encoding="utf-8")
    )
    assert isinstance(aggregate, list)
    assert aggregate[0]["scenario"] == "multi_channel"
    assert aggregate[0]["model"] == "scripted"
    assert aggregate[0]["provider"] == "baseline"
    assert "score" in aggregate[0]
    assert "dimensions" in aggregate[0]["score"]


def test_vei_eval_benchmark_cli_scripted(tmp_path: Path) -> None:
    runner = typer.testing.CliRunner()
    result = runner.invoke(
        eval_app,
        [
            "benchmark",
            "--runner",
            "scripted",
            "--scenario",
            "multi_channel",
            "--artifacts-root",
            str(tmp_path),
            "--run-id",
            "scripted_cli",
        ],
    )

    assert result.exit_code == 0, result.output
    assert (tmp_path / "scripted_cli" / "aggregate_results.json").exists()
    assert (tmp_path / "scripted_cli" / "benchmark_summary.json").exists()


def test_report_loads_batch_results_without_double_counting(tmp_path: Path) -> None:
    run_dir = tmp_path / "report_batch"
    run_benchmark_batch(
        [
            BenchmarkCaseSpec(
                runner="scripted",
                scenario_name="multi_channel",
                seed=404,
                artifacts_dir=run_dir / "multi_channel",
                score_mode="email",
            )
        ],
        run_id="report_suite",
        output_dir=run_dir,
    )

    results = load_all_results(run_dir)

    assert len(results) == 1
    assert results[0]["model"] == "scripted"
    assert results[0]["provider"] == "baseline"


def test_benchmark_family_catalog_and_resolution() -> None:
    families = {item.name: item for item in list_benchmark_family_manifest()}

    assert "security_containment" in families
    assert "enterprise_onboarding_migration" in families
    assert "revenue_incident_mitigation" in families
    assert get_benchmark_family_manifest("security_containment").scenario_names == [
        "oauth_app_containment"
    ]
    assert resolve_scenarios(family_names=["revenue_incident_mitigation"]) == [
        "checkout_spike_mitigation"
    ]


def test_enterprise_dimension_scoring_for_security_containment(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("VEI_STATE_DIR", str(tmp_path / "state"))
    artifacts = tmp_path / "oauth_dims"
    session = create_world_session(
        seed=42042,
        artifacts_dir=str(artifacts),
        scenario=get_catalog_scenario("oauth_app_containment"),
    )
    session.call_tool(
        "google_admin.preserve_oauth_evidence",
        {"app_id": "OAUTH-9001", "note": "preserve before containment"},
    )
    session.call_tool(
        "google_admin.suspend_oauth_app",
        {"app_id": "OAUTH-9001", "reason": "containment"},
    )
    session.call_tool(
        "siem.update_case",
        {
            "case_id": "CASE-0001",
            "customer_notification_required": True,
            "note": "Will notify impacted customers.",
        },
    )
    session.snapshot("final")

    score = score_enterprise_dimensions(
        scenario_name="oauth_app_containment",
        artifacts_dir=artifacts,
        raw_score={},
        state=session.current_state(),
    )

    assert score["benchmark_family"] == "security_containment"
    assert score["success"] is True
    assert score["dimensions"]["evidence_preservation"] == 1.0
    assert score["dimensions"]["blast_radius_minimization"] >= 0.75


def test_run_benchmark_case_for_family_scenario_includes_family_dimensions(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "family_case"
    spec = BenchmarkCaseSpec(
        runner="scripted",
        scenario_name="oauth_app_containment",
        seed=202,
        artifacts_dir=artifacts,
        score_mode="full",
    )

    result = run_benchmark_case(spec)

    assert result.status == "ok"
    assert result.score["benchmark_family"] == "security_containment"
    assert result.diagnostics.benchmark_family == "security_containment"
    assert "evidence_preservation" in result.score["dimensions"]
