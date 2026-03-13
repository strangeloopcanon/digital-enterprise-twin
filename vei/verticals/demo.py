from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Literal

from pydantic import BaseModel, Field

from vei.run.api import launch_workspace_run
from vei.verticals.packs import (
    VerticalPackManifest,
    get_vertical_pack_manifest,
    list_vertical_pack_manifests,
)
from vei.workspace.api import (
    activate_workspace_contract_variant,
    activate_workspace_scenario_variant,
    create_workspace_from_template,
    preview_workspace_scenario,
)


VerticalCompareRunner = Literal["scripted", "bc", "llm"]


class VerticalDemoSpec(BaseModel):
    vertical_name: str
    workspace_root: Path
    scenario_variant: str | None = None
    contract_variant: str | None = None
    compare_runner: VerticalCompareRunner = "scripted"
    overwrite: bool = True
    seed: int = 42042
    max_steps: int = 18
    compare_model: str | None = None
    compare_provider: str | None = None
    compare_bc_model_path: Path | None = None
    compare_task: str | None = None


class VerticalDemoResult(BaseModel):
    manifest: VerticalPackManifest
    workspace_root: Path
    scenario_name: str
    scenario_variant: str | None = None
    contract_variant: str | None = None
    workflow_run_id: str
    comparison_run_id: str
    compare_runner: VerticalCompareRunner
    workflow_manifest_path: Path
    comparison_manifest_path: Path
    contract_path: Path
    overview_path: Path
    ui_command: str
    what_if_branches: list[str] = Field(default_factory=list)
    baseline_success: bool = False
    comparison_success: bool = False
    baseline_contract_ok: bool | None = None
    comparison_contract_ok: bool | None = None
    baseline_event_count: int = 0
    comparison_event_count: int = 0
    baseline_graph_action_count: int = 0
    comparison_graph_action_count: int = 0
    baseline_snapshot_count: int = 0
    comparison_snapshot_count: int = 0
    baseline_graph_domains: list[str] = Field(default_factory=list)
    comparison_graph_domains: list[str] = Field(default_factory=list)
    baseline_resolved_tools: list[str] = Field(default_factory=list)
    comparison_resolved_tools: list[str] = Field(default_factory=list)
    kernel_thesis: str = ""
    platform_uses: list[str] = Field(default_factory=list)


class VerticalShowcaseSpec(BaseModel):
    vertical_names: list[str] = Field(default_factory=list)
    root: Path
    compare_runner: VerticalCompareRunner = "scripted"
    overwrite: bool = True
    seed: int = 42042
    max_steps: int = 18
    compare_model: str | None = None
    compare_provider: str | None = None
    compare_bc_model_path: Path | None = None
    compare_task: str | None = None
    run_id: str = "vertical_showcase"


class VerticalShowcaseResult(BaseModel):
    run_id: str
    root: Path
    compare_runner: VerticalCompareRunner
    overview_path: Path
    result_path: Path
    demos: list[VerticalDemoResult] = Field(default_factory=list)
    kernel_thesis: str = ""
    platform_uses: list[str] = Field(default_factory=list)


class VerticalVariantMatrixCombination(BaseModel):
    name: str
    title: str
    scenario_variant: str
    contract_variant: str
    rationale: str


class VerticalVariantMatrixSpec(BaseModel):
    vertical_names: list[str] = Field(default_factory=list)
    root: Path
    compare_runner: VerticalCompareRunner = "scripted"
    overwrite: bool = True
    seed: int = 42042
    max_steps: int = 18
    compare_model: str | None = None
    compare_provider: str | None = None
    compare_bc_model_path: Path | None = None
    compare_task: str | None = None
    run_id: str = "variant_matrix"


class VerticalVariantMatrixRun(BaseModel):
    vertical_name: str
    company_name: str
    workspace_root: Path
    combination: VerticalVariantMatrixCombination
    workflow_run_id: str
    comparison_run_id: str
    workflow_contract_ok: bool | None = None
    comparison_contract_ok: bool | None = None
    workflow_event_count: int = 0
    comparison_event_count: int = 0
    kernel_thesis: str = ""
    ui_command: str


class VerticalVariantMatrixResult(BaseModel):
    run_id: str
    root: Path
    compare_runner: VerticalCompareRunner
    overview_path: Path
    result_path: Path
    runs: list[VerticalVariantMatrixRun] = Field(default_factory=list)
    kernel_thesis: str = ""
    platform_uses: list[str] = Field(default_factory=list)


def prepare_vertical_demo(spec: VerticalDemoSpec) -> VerticalDemoResult:
    if spec.compare_runner == "llm" and not spec.compare_model:
        raise ValueError("llm comparison requires compare_model")
    if spec.compare_runner == "bc" and spec.compare_bc_model_path is None:
        raise ValueError("bc comparison requires compare_bc_model_path")
    manifest = get_vertical_pack_manifest(spec.vertical_name)
    create_workspace_from_template(
        root=spec.workspace_root,
        source_kind="vertical",
        source_ref=manifest.name,
        overwrite=spec.overwrite,
    )
    if spec.scenario_variant:
        activate_workspace_scenario_variant(
            spec.workspace_root,
            spec.scenario_variant,
            bootstrap_contract=True,
        )
    if spec.contract_variant:
        activate_workspace_contract_variant(spec.workspace_root, spec.contract_variant)
    workflow_manifest = launch_workspace_run(
        spec.workspace_root,
        runner="workflow",
        run_id="workflow_baseline",
        seed=spec.seed,
        max_steps=spec.max_steps,
    )
    comparison_manifest = launch_workspace_run(
        spec.workspace_root,
        runner=spec.compare_runner,
        run_id=f"{spec.compare_runner}_comparison",
        seed=spec.seed,
        model=spec.compare_model,
        provider=spec.compare_provider,
        bc_model_path=spec.compare_bc_model_path,
        task=spec.compare_task,
        max_steps=spec.max_steps,
    )
    preview = preview_workspace_scenario(spec.workspace_root)
    workspace_root = Path(spec.workspace_root).expanduser().resolve()
    run_root = workspace_root / "runs"
    overview_path = workspace_root / "vertical_demo_overview.md"
    what_if_branches = _extract_what_if_branches(preview) or list(
        manifest.what_if_branches
    )
    baseline_summary = _summarize_run_spine(run_root / workflow_manifest.run_id)
    comparison_summary = _summarize_run_spine(run_root / comparison_manifest.run_id)
    result = VerticalDemoResult(
        manifest=manifest,
        workspace_root=workspace_root,
        scenario_name=str(preview["scenario"]["name"]),
        scenario_variant=preview.get("active_scenario_variant"),
        contract_variant=preview.get("active_contract_variant"),
        workflow_run_id=workflow_manifest.run_id,
        comparison_run_id=comparison_manifest.run_id,
        compare_runner=spec.compare_runner,
        workflow_manifest_path=run_root
        / workflow_manifest.run_id
        / "run_manifest.json",
        comparison_manifest_path=run_root
        / comparison_manifest.run_id
        / "run_manifest.json",
        contract_path=workspace_root
        / "contracts"
        / f"{preview['scenario']['name']}.contract.json",
        overview_path=overview_path,
        ui_command=(
            "python -m vei.cli.vei ui serve "
            f"--root {workspace_root} --host 127.0.0.1 --port 3011"
        ),
        what_if_branches=what_if_branches,
        baseline_success=workflow_manifest.success,
        comparison_success=comparison_manifest.success,
        baseline_contract_ok=(
            workflow_manifest.contract.ok if workflow_manifest.contract else None
        ),
        comparison_contract_ok=(
            comparison_manifest.contract.ok if comparison_manifest.contract else None
        ),
        baseline_event_count=int(baseline_summary["event_count"]),
        comparison_event_count=int(comparison_summary["event_count"]),
        baseline_graph_action_count=int(baseline_summary["graph_action_count"]),
        comparison_graph_action_count=int(comparison_summary["graph_action_count"]),
        baseline_snapshot_count=len(workflow_manifest.snapshots),
        comparison_snapshot_count=len(comparison_manifest.snapshots),
        baseline_graph_domains=list(baseline_summary["graph_domains"]),
        comparison_graph_domains=list(comparison_summary["graph_domains"]),
        baseline_resolved_tools=list(baseline_summary["resolved_tools"]),
        comparison_resolved_tools=list(comparison_summary["resolved_tools"]),
        kernel_thesis=_kernel_thesis_statement(),
        platform_uses=_platform_uses(),
    )
    overview_path.write_text(render_vertical_demo_overview(result), encoding="utf-8")
    (workspace_root / "vertical_demo_result.json").write_text(
        json.dumps(result.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    return result


def run_vertical_showcase(spec: VerticalShowcaseSpec) -> VerticalShowcaseResult:
    showcase_root = spec.root.expanduser().resolve() / spec.run_id
    showcase_root.mkdir(parents=True, exist_ok=True)
    selected = (
        [get_vertical_pack_manifest(name) for name in spec.vertical_names]
        if spec.vertical_names
        else list_vertical_pack_manifests()
    )
    demos: list[VerticalDemoResult] = []
    for item in selected:
        demos.append(
            prepare_vertical_demo(
                VerticalDemoSpec(
                    vertical_name=item.name,
                    workspace_root=showcase_root / item.name,
                    compare_runner=spec.compare_runner,
                    overwrite=spec.overwrite,
                    seed=spec.seed,
                    max_steps=spec.max_steps,
                    compare_model=spec.compare_model,
                    compare_provider=spec.compare_provider,
                    compare_bc_model_path=spec.compare_bc_model_path,
                    compare_task=spec.compare_task,
                )
            )
        )
    result = VerticalShowcaseResult(
        run_id=spec.run_id,
        root=showcase_root,
        compare_runner=spec.compare_runner,
        overview_path=showcase_root / "vertical_showcase_overview.md",
        result_path=showcase_root / "vertical_showcase_result.json",
        demos=demos,
        kernel_thesis=_kernel_thesis_statement(),
        platform_uses=_platform_uses(),
    )
    result.overview_path.write_text(
        render_vertical_showcase_overview(result), encoding="utf-8"
    )
    result.result_path.write_text(
        json.dumps(result.model_dump(mode="json"), indent=2), encoding="utf-8"
    )
    return result


def run_vertical_variant_matrix(
    spec: VerticalVariantMatrixSpec,
) -> VerticalVariantMatrixResult:
    showcase_root = spec.root.expanduser().resolve() / spec.run_id
    showcase_root.mkdir(parents=True, exist_ok=True)
    selected = (
        [get_vertical_pack_manifest(name) for name in spec.vertical_names]
        if spec.vertical_names
        else list_vertical_pack_manifests()
    )
    runs: list[VerticalVariantMatrixRun] = []
    for manifest in selected:
        for combo in _curated_variant_matrix(manifest.name):
            workspace_root = showcase_root / manifest.name / combo.name
            create_workspace_from_template(
                root=workspace_root,
                source_kind="vertical",
                source_ref=manifest.name,
                overwrite=spec.overwrite,
            )
            activate_workspace_scenario_variant(
                workspace_root,
                combo.scenario_variant,
                bootstrap_contract=True,
            )
            activate_workspace_contract_variant(workspace_root, combo.contract_variant)
            workflow_manifest = launch_workspace_run(
                workspace_root,
                runner="workflow",
                run_id=f"{combo.name}_workflow",
                seed=spec.seed,
                max_steps=spec.max_steps,
            )
            comparison_manifest = launch_workspace_run(
                workspace_root,
                runner=spec.compare_runner,
                run_id=f"{combo.name}_{spec.compare_runner}",
                seed=spec.seed,
                model=spec.compare_model,
                provider=spec.compare_provider,
                bc_model_path=spec.compare_bc_model_path,
                task=spec.compare_task,
                max_steps=spec.max_steps,
            )
            workflow_summary = _summarize_run_spine(
                workspace_root / "runs" / workflow_manifest.run_id
            )
            comparison_summary = _summarize_run_spine(
                workspace_root / "runs" / comparison_manifest.run_id
            )
            runs.append(
                VerticalVariantMatrixRun(
                    vertical_name=manifest.name,
                    company_name=manifest.company_name,
                    workspace_root=workspace_root,
                    combination=combo,
                    workflow_run_id=workflow_manifest.run_id,
                    comparison_run_id=comparison_manifest.run_id,
                    workflow_contract_ok=(
                        workflow_manifest.contract.ok
                        if workflow_manifest.contract
                        else None
                    ),
                    comparison_contract_ok=(
                        comparison_manifest.contract.ok
                        if comparison_manifest.contract
                        else None
                    ),
                    workflow_event_count=int(workflow_summary["event_count"]),
                    comparison_event_count=int(comparison_summary["event_count"]),
                    kernel_thesis=_kernel_thesis_statement(),
                    ui_command=(
                        "python -m vei.cli.vei ui serve "
                        f"--root {workspace_root} --host 127.0.0.1 --port 3011"
                    ),
                )
            )
    result = VerticalVariantMatrixResult(
        run_id=spec.run_id,
        root=showcase_root,
        compare_runner=spec.compare_runner,
        overview_path=showcase_root / "vertical_variant_matrix_overview.md",
        result_path=showcase_root / "vertical_variant_matrix_result.json",
        runs=runs,
        kernel_thesis=_kernel_thesis_statement(),
        platform_uses=_platform_uses(),
    )
    result.overview_path.write_text(
        render_vertical_variant_matrix_overview(result), encoding="utf-8"
    )
    result.result_path.write_text(
        json.dumps(result.model_dump(mode="json"), indent=2), encoding="utf-8"
    )
    return result


def render_vertical_demo_overview(result: VerticalDemoResult) -> str:
    lines = [
        f"# {result.manifest.title}",
        "",
        result.manifest.description,
        "",
        f"- Company: `{result.manifest.company_name}`",
        f"- Scenario: `{result.scenario_name}`",
        f"- Scenario variant: `{result.scenario_variant or 'default'}`",
        f"- Contract variant: `{result.contract_variant or 'default'}`",
        f"- Workflow baseline: `{result.workflow_run_id}`",
        f"- Comparison ({result.compare_runner}): `{result.comparison_run_id}`",
        f"- Contract path: `{result.contract_path}`",
        f"- UI: `{result.ui_command}`",
        "",
        "What this proves:",
    ]
    lines.extend(f"- {bullet}" for bullet in result.manifest.proves)
    lines.extend(
        [
            "",
            "Why the kernel matters:",
            f"- {result.kernel_thesis}",
            (
                f"- Baseline emitted `{result.baseline_event_count}` run events, "
                f"`{result.baseline_graph_action_count}` graph-native actions, and "
                f"`{result.baseline_snapshot_count}` snapshots."
            ),
        ]
    )
    if result.baseline_graph_domains:
        lines.append(
            "- Graph domains touched: "
            + ", ".join(f"`{item}`" for item in result.baseline_graph_domains)
        )
    if result.baseline_resolved_tools:
        lines.append(
            "- Resolved tools used: "
            + ", ".join(f"`{item}`" for item in result.baseline_resolved_tools[:5])
        )
    lines.extend(["", "What this becomes later:"])
    lines.extend(f"- {bullet}" for bullet in result.platform_uses)
    if result.what_if_branches:
        lines.extend(["", "What-if branches:"])
        lines.extend(f"- {branch}" for branch in result.what_if_branches)
    return "\n".join(lines).rstrip() + "\n"


def render_vertical_showcase_overview(result: VerticalShowcaseResult) -> str:
    lines = [
        "# VEI Vertical World Pack Showcase",
        "",
        f"Run ID: `{result.run_id}`",
        f"Comparison runner: `{result.compare_runner}`",
        f"Workspaces: `{len(result.demos)}`",
        "",
        "## One kernel, three companies",
        "",
        result.kernel_thesis,
        "",
        "This is why the same product can later become multiple layers above the kernel:",
        "",
    ]
    lines.extend(f"- {bullet}" for bullet in result.platform_uses)
    lines.extend(
        [
            "",
            "Each world pack below uses the same workspace model, event spine, snapshot/branch system, contract engine, and UI playback surface.",
            "",
        ]
    )
    for demo in result.demos:
        lines.extend(
            [
                f"## {demo.manifest.title}",
                "",
                demo.manifest.description,
                "",
                f"- Workspace: `{demo.workspace_root}`",
                f"- Baseline contract: `{demo.baseline_contract_ok}`",
                f"- Comparison contract: `{demo.comparison_contract_ok}`",
                (
                    f"- Baseline kernel proof: `{demo.baseline_event_count}` events, "
                    f"`{demo.baseline_graph_action_count}` graph actions, "
                    f"`{demo.baseline_snapshot_count}` snapshots"
                ),
                (
                    "- Domains touched: "
                    + ", ".join(f"`{item}`" for item in demo.baseline_graph_domains)
                    if demo.baseline_graph_domains
                    else "- Domains touched: `n/a`"
                ),
                f"- Overview: `{demo.overview_path}`",
                f"- UI: `{demo.ui_command}`",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def render_vertical_variant_matrix_overview(
    result: VerticalVariantMatrixResult,
) -> str:
    lines = [
        "# VEI Variant Matrix Showcase",
        "",
        result.kernel_thesis,
        "",
        "Same world pack, different problem overlays, different contract overlays, same runtime kernel.",
        "",
    ]
    for run in result.runs:
        lines.extend(
            [
                f"## {run.company_name} · {run.combination.title}",
                "",
                f"- Scenario variant: `{run.combination.scenario_variant}`",
                f"- Contract variant: `{run.combination.contract_variant}`",
                f"- Workflow baseline contract: `{run.workflow_contract_ok}`",
                f"- Comparison contract: `{run.comparison_contract_ok}`",
                f"- Baseline events: `{run.workflow_event_count}`",
                f"- Comparison events: `{run.comparison_event_count}`",
                f"- Rationale: {run.combination.rationale}",
                f"- UI: `{run.ui_command}`",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def resolve_vertical_names(names: Iterable[str] | None = None) -> list[str]:
    cleaned = [name.strip().lower() for name in (names or []) if name.strip()]
    if cleaned:
        return cleaned
    return [item.name for item in list_vertical_pack_manifests()]


def _extract_what_if_branches(preview: dict[str, object]) -> list[str]:
    scenario = preview.get("scenario")
    if not isinstance(scenario, dict):
        return []
    metadata = scenario.get("metadata")
    if not isinstance(metadata, dict):
        return []
    builder_environment = metadata.get("builder_environment")
    if not isinstance(builder_environment, dict):
        return []
    branches = builder_environment.get("what_if_branches")
    if not isinstance(branches, list):
        return []
    return [str(item) for item in branches if str(item).strip()]


def _kernel_thesis_statement() -> str:
    return (
        "VEI is the shared world kernel underneath every demo: the company-specific "
        "part is just the capability graph and contract, while the runtime, event "
        "spine, branching, replay, and inspection surfaces stay the same."
    )


def _platform_uses() -> list[str]:
    return [
        "RL environment: deterministic world state, snapshots, and contract-shaped outcomes become trainable episodes later.",
        "Continuous eval system: the workflow baseline and freer comparison runs already share the same scenario, contract, and event spine.",
        "AI agent management platform: live playback, resolved tools, provenance, and branch diffs make agent behavior inspectable and governable.",
    ]


def _curated_variant_matrix(
    vertical_name: str,
) -> list[VerticalVariantMatrixCombination]:
    curated: dict[str, list[VerticalVariantMatrixCombination]] = {
        "real_estate_management": [
            VerticalVariantMatrixCombination(
                name="opening_readiness",
                title="Opening Readiness",
                scenario_variant="tenant_opening_conflict",
                contract_variant="opening_readiness",
                rationale="Solve the flagship Harbor Point opening conflict cleanly.",
            ),
            VerticalVariantMatrixCombination(
                name="vendor_safety",
                title="Vendor Shock, Safety First",
                scenario_variant="vendor_no_show",
                contract_variant="safety_over_speed",
                rationale="Same property, different future: a vendor drop-out pushes the objective toward safety over schedule.",
            ),
            VerticalVariantMatrixCombination(
                name="tenant_disruption",
                title="Reservation Conflict, Tenant First",
                scenario_variant="double_booked_unit",
                contract_variant="minimize_tenant_disruption",
                rationale="Keep the same world but optimize for tenant continuity and trust.",
            ),
        ],
        "digital_marketing_agency": [
            VerticalVariantMatrixCombination(
                name="launch_safely",
                title="Launch Safely",
                scenario_variant="campaign_launch_guardrail",
                contract_variant="launch_safely",
                rationale="Flagship agency path: approval, pacing, and reporting all become safe together.",
            ),
            VerticalVariantMatrixCombination(
                name="protect_budget",
                title="Protect Budget",
                scenario_variant="budget_runaway",
                contract_variant="protect_budget",
                rationale="Same campaign world, but finance becomes the dominant objective.",
            ),
            VerticalVariantMatrixCombination(
                name="client_comms",
                title="Client Comms First",
                scenario_variant="client_reporting_mismatch",
                contract_variant="client_comms_first",
                rationale="Prioritize truthfulness and artifact integrity when reporting drifts.",
            ),
        ],
        "storage_solutions": [
            VerticalVariantMatrixCombination(
                name="no_overcommit",
                title="No Overcommit",
                scenario_variant="capacity_quote_commitment",
                contract_variant="no_overcommit",
                rationale="Flagship storage path: keep the commitment feasible before it reaches the customer.",
            ),
            VerticalVariantMatrixCombination(
                name="revenue_bias",
                title="Maximize Feasible Revenue",
                scenario_variant="fragmented_capacity",
                contract_variant="maximize_feasible_revenue",
                rationale="Preserve as much value as possible while still restoring feasibility.",
            ),
            VerticalVariantMatrixCombination(
                name="ops_consistency",
                title="Ops Consistency",
                scenario_variant="vendor_dispatch_gap",
                contract_variant="ops_consistency",
                rationale="The company stays the same; the objective changes to downstream execution discipline.",
            ),
        ],
    }
    if vertical_name not in curated:
        raise KeyError(f"unknown vertical pack: {vertical_name}")
    return curated[vertical_name]


def _summarize_run_spine(run_root: Path) -> dict[str, object]:
    events_path = run_root / "events.jsonl"
    if not events_path.exists():
        return {
            "event_count": 0,
            "graph_action_count": 0,
            "graph_domains": [],
            "resolved_tools": [],
        }
    graph_domains: list[str] = []
    resolved_tools: list[str] = []
    event_count = 0
    graph_action_count = 0
    with events_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            event_count += 1
            payload = json.loads(line)
            graph_domain = payload.get("graph_domain")
            if isinstance(graph_domain, str) and graph_domain:
                graph_action_count += 1
                if graph_domain not in graph_domains:
                    graph_domains.append(graph_domain)
            resolved_tool = payload.get("resolved_tool")
            if (
                isinstance(resolved_tool, str)
                and resolved_tool
                and resolved_tool not in resolved_tools
            ):
                resolved_tools.append(resolved_tool)
    return {
        "event_count": event_count,
        "graph_action_count": graph_action_count,
        "graph_domains": graph_domains,
        "resolved_tools": resolved_tools,
    }


__all__ = [
    "VerticalCompareRunner",
    "VerticalDemoResult",
    "VerticalDemoSpec",
    "VerticalShowcaseResult",
    "VerticalShowcaseSpec",
    "VerticalVariantMatrixCombination",
    "VerticalVariantMatrixResult",
    "VerticalVariantMatrixSpec",
    "prepare_vertical_demo",
    "render_vertical_demo_overview",
    "render_vertical_showcase_overview",
    "render_vertical_variant_matrix_overview",
    "resolve_vertical_names",
    "run_vertical_showcase",
    "run_vertical_variant_matrix",
]
