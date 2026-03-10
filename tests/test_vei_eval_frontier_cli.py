from __future__ import annotations

from pathlib import Path

import typer
from typer.testing import CliRunner

from vei.benchmark.models import (
    BenchmarkBatchResult,
    BenchmarkBatchSummary,
    BenchmarkCaseResult,
    BenchmarkCaseSpec,
)
from vei.cli.vei_eval_frontier import app as frontier_app


def _make_batch(specs: list[BenchmarkCaseSpec], run_id: str) -> BenchmarkBatchResult:
    results = [
        BenchmarkCaseResult(
            spec=spec,
            status="ok",
            success=True,
            score={"success": True, "composite_score": 1.0, "steps_taken": 0},
        )
        for spec in specs
    ]
    return BenchmarkBatchResult(
        run_id=run_id,
        results=results,
        summary=BenchmarkBatchSummary(
            total_runs=len(results),
            success_count=len(results),
            success_rate=1.0 if results else 0.0,
            average_composite_score=1.0 if results else 0.0,
        ),
    )


def test_frontier_cli_explicit_scenario_does_not_expand_to_all(
    tmp_path: Path, monkeypatch
) -> None:
    captured_specs: list[BenchmarkCaseSpec] = []

    def fake_run_benchmark_batch(
        specs: list[BenchmarkCaseSpec], *, run_id: str, output_dir: Path | None = None
    ) -> BenchmarkBatchResult:
        captured_specs.extend(specs)
        return _make_batch(specs, run_id)

    monkeypatch.setattr(
        "vei.cli.vei_eval_frontier.run_benchmark_batch",
        fake_run_benchmark_batch,
    )

    runner = CliRunner()
    result = runner.invoke(
        frontier_app,
        [
            "run",
            "--runner",
            "scripted",
            "--scenario",
            "f1_budget_reconciliation",
            "--artifacts-root",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert [spec.scenario_name for spec in captured_specs] == [
        "f1_budget_reconciliation"
    ]


def test_frontier_cli_prints_progress_before_batch_runs(
    tmp_path: Path, monkeypatch
) -> None:
    def fake_run_benchmark_batch(
        specs: list[BenchmarkCaseSpec], *, run_id: str, output_dir: Path | None = None
    ) -> BenchmarkBatchResult:
        typer.echo("BATCH_START")
        return _make_batch(specs, run_id)

    monkeypatch.setattr(
        "vei.cli.vei_eval_frontier.run_benchmark_batch",
        fake_run_benchmark_batch,
    )

    runner = CliRunner()
    result = runner.invoke(
        frontier_app,
        [
            "run",
            "--runner",
            "scripted",
            "--scenario",
            "f1_budget_reconciliation",
            "--artifacts-root",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert result.output.index("Starting frontier evaluation") < result.output.index(
        "BATCH_START"
    )
