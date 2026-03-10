"""CLI for running frontier model evaluations with multi-dimensional scoring.

Usage:
    vei-eval-frontier --model gpt-5 --scenario f1_budget_reconciliation --max-steps 60
    vei-eval-frontier --model gpt-5 --scenario-set all_frontier --provider openai
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

import typer

from vei.benchmark.api import (
    FRONTIER_SCENARIO_SETS,
    resolve_scenarios,
    run_benchmark_batch,
)
from vei.benchmark.models import BenchmarkCaseSpec
from vei.score_frontier import compute_frontier_score
from vei.world.scenarios import list_scenarios

app = typer.Typer(name="vei-eval-frontier", help="Run frontier model evaluations")


@app.command(name="run")
def run_frontier_eval(
    model: Optional[str] = typer.Option(
        None, help="Model name (e.g., gpt-5, claude-sonnet-4-5)"
    ),
    scenario: Optional[str] = typer.Option(
        None, help="Single scenario to run (e.g., f1_budget_reconciliation)"
    ),
    scenario_set: Optional[str] = typer.Option(
        None, help="Scenario set to run (all_frontier, reasoning, safety, expertise)"
    ),
    provider: str = typer.Option(
        "auto", help="LLM provider: openai, anthropic, google, openrouter, auto"
    ),
    runner: str = typer.Option("llm", help="Runner: llm|scripted|bc"),
    bc_model: Optional[Path] = typer.Option(
        None, exists=True, readable=True, help="BC policy path when runner=bc"
    ),
    max_steps: int = typer.Option(80, help="Maximum steps per scenario"),
    artifacts_root: Path = typer.Option(
        Path("_vei_out/frontier_eval"), help="Root directory for artifacts"
    ),
    seed: int = typer.Option(42042, help="Random seed for reproducibility"),
    use_llm_judge: bool = typer.Option(
        False, help="Use LLM-as-judge for communication quality scoring"
    ),
    task: Optional[str] = typer.Option(
        None, help="Optional task prompt for llm runner"
    ),
) -> None:
    normalized_runner = runner.strip().lower()
    if normalized_runner not in {"llm", "scripted", "bc"}:
        raise typer.BadParameter("runner must be llm, scripted, or bc")
    if normalized_runner == "llm" and not model:
        raise typer.BadParameter("llm runner requires --model")
    if normalized_runner == "bc" and bc_model is None:
        raise typer.BadParameter("bc runner requires --bc-model")
    if scenario and scenario_set:
        raise typer.BadParameter("specify either --scenario or --scenario-set")

    scenario_names = resolve_scenarios(
        scenario_names=[scenario] if scenario else [],
        scenario_set=None if scenario else (scenario_set or "all_frontier"),
    )

    run_id = f"{(model or normalized_runner).replace('/', '_')}_{int(time.time())}"
    run_dir = artifacts_root / run_id
    specs = [
        BenchmarkCaseSpec(
            runner=normalized_runner,  # type: ignore[arg-type]
            scenario_name=scenario_name,
            seed=seed,
            artifacts_dir=run_dir / scenario_name,
            branch=scenario_name,
            frontier=True,
            model=model,
            provider=provider,
            bc_model_path=bc_model,
            task=task,
            max_steps=max_steps,
            use_llm_judge=use_llm_judge,
        )
        for scenario_name in scenario_names
    ]

    typer.echo(f"Starting frontier evaluation: {len(specs)} scenarios")
    typer.echo(f"Runner: {normalized_runner}")
    if model:
        typer.echo(f"Model: {model}")
    typer.echo(f"Artifacts: {run_dir}")
    typer.echo("")

    batch = run_benchmark_batch(specs, run_id=run_id, output_dir=run_dir)

    for result in batch.results:
        score = result.score
        success_icon = "✅" if score.get("success") else "❌"
        composite = float(score.get("composite_score", 0.0))
        typer.echo(f"{result.spec.scenario_name}")
        typer.echo(
            f"  {success_icon} Composite Score: {composite:.3f} | Steps: {score.get('steps_taken', 0)} | Status: {result.status}"
        )
        if result.error:
            typer.echo(f"  Error: {result.error}")

    typer.echo("")
    typer.echo("=" * 70)
    typer.echo(f"Evaluation Complete: {run_id}")
    typer.echo("=" * 70)
    typer.echo(
        f"Success Rate: {batch.summary.success_count}/{batch.summary.total_runs} ({batch.summary.success_rate*100:.1f}%)"
    )
    typer.echo(f"Average Composite Score: {batch.summary.average_composite_score:.3f}")
    typer.echo(f"P95 Latency (trace): {batch.summary.p95_latency_ms} ms")
    typer.echo(f"\nResults saved to: {run_dir}")
    typer.echo(f"Aggregate: {run_dir / 'aggregate_results.json'}")
    typer.echo("")
    typer.echo("Generate detailed report with: vei-report --root " + str(run_dir))


@app.command(name="list")
def list_frontier_scenarios() -> None:
    """List all available frontier scenarios."""
    scenarios = list_scenarios()
    frontier_scenarios = {k: v for k, v in scenarios.items() if k.startswith("f")}

    typer.echo("Frontier Evaluation Scenarios")
    typer.echo("=" * 70)

    for name, scenario in sorted(frontier_scenarios.items()):
        metadata = getattr(scenario, "metadata", {})
        difficulty = metadata.get("difficulty", "unknown")
        expected_steps = metadata.get("expected_steps", [0, 0])

        typer.echo(f"\n{name}")
        typer.echo(f"  Difficulty: {difficulty}")
        typer.echo(f"  Expected steps: {expected_steps[0]}-{expected_steps[1]}")

        if metadata.get("rubric"):
            typer.echo(f"  Rubric dimensions: {', '.join(metadata['rubric'].keys())}")

    typer.echo("\n" + "=" * 70)
    typer.echo(f"\nTotal frontier scenarios: {len(frontier_scenarios)}")
    typer.echo("\nScenario sets available:")
    for set_name, scenarios_list in FRONTIER_SCENARIO_SETS.items():
        typer.echo(f"  - {set_name}: {len(scenarios_list)} scenarios")


@app.command(name="score")
def score_existing_run(
    artifacts_dir: Path = typer.Option(..., help="Directory containing trace.jsonl"),
    use_llm_judge: bool = typer.Option(
        False, help="Use LLM-as-judge for quality scoring"
    ),
    output: Optional[Path] = typer.Option(None, help="Output path for score JSON"),
) -> None:
    """Score an existing run with frontier scoring system."""

    if not artifacts_dir.exists():
        typer.echo(f"Directory not found: {artifacts_dir}", err=True)
        raise typer.Exit(1)

    trace_path = artifacts_dir / "trace.jsonl"
    if not trace_path.exists():
        typer.echo(f"No trace.jsonl found in {artifacts_dir}", err=True)
        raise typer.Exit(1)

    typer.echo(f"Computing frontier score for: {artifacts_dir}")

    try:
        score = compute_frontier_score(artifacts_dir, use_llm_judge=use_llm_judge)

        if output:
            with open(output, "w", encoding="utf-8") as f:
                json.dump(score, f, indent=2)
            typer.echo(f"Score saved to: {output}")
        else:
            typer.echo(json.dumps(score, indent=2))

    except Exception as e:
        typer.echo(f"Scoring failed: {e}", err=True)
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
