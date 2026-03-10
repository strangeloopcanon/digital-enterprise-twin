from __future__ import annotations

import json
import time
from pathlib import Path

import typer
from typer.models import OptionInfo

from vei.benchmark.api import (
    FRONTIER_SCENARIO_SETS,
    list_benchmark_family_manifest,
    resolve_benchmark_workflow_name,
    resolve_scenarios,
    run_benchmark_batch,
    run_benchmark_case,
)
from vei.benchmark.models import BenchmarkCaseSpec
from vei.benchmark.workflows import get_benchmark_family_workflow_spec
from vei.benchmark.workflows import get_benchmark_family_workflow_variant


app = typer.Typer(add_completion=False)


def _coerce_option(value: object, default: str) -> str:
    return default if isinstance(value, OptionInfo) else str(value)


@app.command()
def scripted(
    seed: int = typer.Option(42042, help="Router seed"),
    dataset: Path = typer.Option(Path("-"), help="Optional dataset JSON for replay"),
    artifacts: Path = typer.Option(Path("_vei_out/eval"), help="Artifacts directory"),
    scenario: str = typer.Option("multi_channel", help="Scenario name"),
    score_success_mode: str = typer.Option(
        "email", help="Score success criteria: email|full."
    ),
) -> None:
    scenario = _coerce_option(scenario, "multi_channel")
    score_success_mode = _coerce_option(score_success_mode, "email")
    spec = BenchmarkCaseSpec(
        runner="scripted",
        scenario_name=scenario,
        seed=seed,
        artifacts_dir=artifacts,
        dataset_path=None if dataset == Path("-") else dataset,
        replay_mode="overlay" if dataset != Path("-") else None,
        score_mode=score_success_mode.lower().strip(),
    )
    result = run_benchmark_case(spec)
    typer.echo(json.dumps(result.raw_score, indent=2))


@app.command()
def bc(
    model: Path = typer.Option(
        ..., "--model", "-m", exists=True, readable=True, help="Trained BC policy"
    ),
    seed: int = typer.Option(42042, help="Router seed"),
    dataset: Path = typer.Option(Path("-"), help="Optional dataset JSON for replay"),
    artifacts: Path = typer.Option(
        Path("_vei_out/eval_bc"), help="Artifacts directory"
    ),
    max_steps: int = typer.Option(12, help="Max policy steps"),
    scenario: str = typer.Option("multi_channel", help="Scenario name"),
    score_success_mode: str = typer.Option(
        "email", help="Score success criteria: email|full."
    ),
) -> None:
    scenario = _coerce_option(scenario, "multi_channel")
    score_success_mode = _coerce_option(score_success_mode, "email")
    spec = BenchmarkCaseSpec(
        runner="bc",
        scenario_name=scenario,
        seed=seed,
        artifacts_dir=artifacts,
        dataset_path=None if dataset == Path("-") else dataset,
        replay_mode="overlay" if dataset != Path("-") else None,
        score_mode=score_success_mode.lower().strip(),
        bc_model_path=model,
        max_steps=max_steps,
    )
    result = run_benchmark_case(spec)
    typer.echo(json.dumps(result.raw_score, indent=2))


@app.command()
def benchmark(
    runner: str = typer.Option("llm", help="Runner: scripted|bc|llm|workflow"),
    scenario: list[str] = typer.Option(
        [], "--scenario", "-s", help="Scenario(s) to run"
    ),
    family: list[str] = typer.Option(
        [], "--family", "-f", help="Benchmark family/families to run"
    ),
    scenario_set: str | None = typer.Option(
        None,
        help=f"Scenario set to run ({', '.join(FRONTIER_SCENARIO_SETS.keys())})",
    ),
    workflow_name: str | None = typer.Option(
        None, help="Optional explicit workflow name when runner=workflow"
    ),
    workflow_variant: str | None = typer.Option(
        None, help="Optional workflow variant name when runner=workflow"
    ),
    model: str | None = typer.Option(None, help="Model name for llm runner"),
    provider: str = typer.Option(
        "auto", help="LLM provider: openai, anthropic, google, openrouter, auto"
    ),
    bc_model: Path | None = typer.Option(
        None, exists=True, readable=True, help="BC policy file when runner=bc"
    ),
    dataset: Path | None = typer.Option(None, help="Optional replay dataset"),
    artifacts_root: Path = typer.Option(
        Path("_vei_out/benchmark"), help="Root directory for benchmark artifacts"
    ),
    seed: int = typer.Option(42042, help="Seed for reproducibility"),
    max_steps: int = typer.Option(40, help="Maximum steps per scenario"),
    task: str | None = typer.Option(None, help="Task prompt for llm runner"),
    tool_top_k: int = typer.Option(0, help="Visible tool top-k for llm runner"),
    score_success_mode: str = typer.Option(
        "full", help="Score success criteria: email|full."
    ),
    frontier: bool = typer.Option(
        False, help="Use frontier scoring for every selected scenario"
    ),
    use_llm_judge: bool = typer.Option(
        False, help="Use LLM-as-judge during frontier scoring"
    ),
    run_id: str | None = typer.Option(None, help="Optional benchmark run id"),
) -> None:
    normalized_runner = runner.strip().lower()
    if normalized_runner not in {"scripted", "bc", "llm", "workflow"}:
        raise typer.BadParameter("runner must be one of scripted|bc|llm|workflow")
    if normalized_runner == "llm" and not model:
        raise typer.BadParameter("llm runner requires --model")
    if normalized_runner == "bc" and bc_model is None:
        raise typer.BadParameter("bc runner requires --bc-model")
    if workflow_name and normalized_runner != "workflow":
        raise typer.BadParameter("--workflow-name only applies when runner=workflow")
    if workflow_variant and normalized_runner != "workflow":
        raise typer.BadParameter("--workflow-variant only applies when runner=workflow")

    selected_families = family
    if scenario or family or scenario_set:
        selected = scenario
    elif normalized_runner == "workflow":
        selected = []
        selected_families = [item.name for item in list_benchmark_family_manifest()]
    else:
        selected = (
            FRONTIER_SCENARIO_SETS["all_frontier"] if frontier else ["multi_channel"]
        )
    scenario_names = resolve_scenarios(
        scenario_names=selected,
        scenario_set=scenario_set,
        family_names=selected_families,
    )
    if workflow_name:
        if len(scenario_names) != 1:
            raise typer.BadParameter(
                "--workflow-name requires exactly one selected scenario"
            )
        try:
            get_benchmark_family_workflow_spec(workflow_name)
        except KeyError as exc:
            raise typer.BadParameter(str(exc)) from exc
    if workflow_variant:
        if len(scenario_names) != 1:
            raise typer.BadParameter(
                "--workflow-variant requires exactly one selected scenario"
            )
        resolved_workflow_name = workflow_name or resolve_benchmark_workflow_name(
            scenario_name=scenario_names[0]
        )
        if resolved_workflow_name is None:
            raise typer.BadParameter(
                f"no benchmark workflow is registered for scenario {scenario_names[0]}"
            )
        try:
            get_benchmark_family_workflow_variant(
                resolved_workflow_name, workflow_variant
            )
        except KeyError as exc:
            raise typer.BadParameter(str(exc)) from exc

    batch_id = run_id or f"{normalized_runner}_{int(time.time())}"
    run_dir = artifacts_root / batch_id
    specs = [
        BenchmarkCaseSpec(
            runner=normalized_runner,  # type: ignore[arg-type]
            scenario_name=scenario_name,
            workflow_name=(
                workflow_name
                or resolve_benchmark_workflow_name(scenario_name=scenario_name)
                if normalized_runner == "workflow"
                else None
            ),
            workflow_variant=(
                workflow_variant if normalized_runner == "workflow" else None
            ),
            seed=seed,
            artifacts_dir=run_dir / scenario_name,
            branch=scenario_name,
            dataset_path=dataset,
            replay_mode="overlay" if dataset else None,
            score_mode=score_success_mode.lower().strip(),
            frontier=frontier or scenario_name.startswith("f"),
            model=model,
            provider=provider if normalized_runner == "llm" else None,
            bc_model_path=bc_model,
            task=task,
            max_steps=max_steps,
            tool_top_k=tool_top_k,
            use_llm_judge=use_llm_judge,
        )
        for scenario_name in scenario_names
    ]
    batch = run_benchmark_batch(specs, run_id=batch_id, output_dir=run_dir)
    typer.echo(json.dumps(batch.summary.model_dump(), indent=2))
    typer.echo(f"results saved to {run_dir}")


if __name__ == "__main__":
    app()
