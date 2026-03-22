from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

from vei.benchmark.api import run_benchmark_case
from vei.benchmark.models import BenchmarkCaseSpec, BenchmarkRunner
from vei.capability_graph.api import build_runtime_capability_graphs
from vei.contract.models import ContractEvaluationResult
from vei.orientation.api import build_world_orientation
from vei.visualization.api import (
    flow_channel_from_focus,
    flow_channel_from_tool,
    load_trace,
)
from vei.world.models import WorldState
from vei.world.state import StateStore
from vei.workspace.api import (
    compile_workspace,
    evaluate_workspace_contract_against_state,
    list_workspace_runs,
    load_workspace,
    resolve_workspace_scenario,
    upsert_workspace_run,
)
from vei.workspace.models import WorkspaceRunEntry

from .events import (
    append_run_event,
    append_run_events,
    load_run_events,
)
from .models import (
    LivingSurfaceItem,
    LivingSurfacePanel,
    LivingSurfaceState,
    RunArtifactIndex,
    RunContractSummary,
    RunManifest,
    RunSnapshotRef,
    RunTimelineEvent,
)


def launch_workspace_run(
    root: str | Path,
    *,
    runner: str,
    scenario_name: Optional[str] = None,
    run_id: Optional[str] = None,
    seed: int = 42042,
    branch: Optional[str] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    bc_model_path: str | Path | None = None,
    task: Optional[str] = None,
    max_steps: int = 12,
) -> RunManifest:
    workspace_root = Path(root).expanduser().resolve()
    normalized_runner = normalize_runner(runner)
    resolved_bc_model_path = (
        Path(bc_model_path).expanduser().resolve()
        if bc_model_path is not None
        else None
    )
    if normalized_runner == "bc" and resolved_bc_model_path is None:
        raise ValueError("bc runner requires bc_model_path")
    summary = compile_workspace(workspace_root)
    manifest = summary.manifest
    scenario = resolve_workspace_scenario(workspace_root, manifest, scenario_name)

    resolved_run_id = run_id or generate_run_id()
    resolved_branch = branch or f"{manifest.name}.{resolved_run_id}"
    run_dir = workspace_root / manifest.runs_dir / resolved_run_id
    if run_dir.exists():
        raise ValueError(f"run_id already exists: {resolved_run_id}")
    artifacts_dir = run_dir / "artifacts"
    state_dir = run_dir / "state"
    events_path = run_dir / "events.jsonl"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)

    scenario_root = workspace_root / manifest.compiled_root / scenario.name
    blueprint_asset_path = scenario_root / "blueprint_asset.json"
    contract_path = (
        scenario.contract_path
        or f"{manifest.contracts_dir}/{scenario.name}.contract.json"
    )
    manifest_stub = RunManifest(
        run_id=resolved_run_id,
        workspace_name=manifest.name,
        scenario_name=scenario.name,
        runner=normalized_runner,
        status="running",
        started_at=_iso_now(),
        seed=seed,
        branch=resolved_branch,
        model=model,
        provider=provider,
        bc_model_path=(
            str(resolved_bc_model_path) if resolved_bc_model_path is not None else None
        ),
        workflow_name=scenario.workflow_name,
        workflow_variant=scenario.workflow_variant,
        artifacts=RunArtifactIndex(
            run_dir=str(run_dir.relative_to(workspace_root)),
            artifacts_dir=str(artifacts_dir.relative_to(workspace_root)),
            state_dir=str(state_dir.relative_to(workspace_root)),
            events_path=str(events_path.relative_to(workspace_root)),
            blueprint_asset_path=str(blueprint_asset_path.relative_to(workspace_root)),
            contract_path=contract_path,
        ),
        metadata={
            "workspace_scenario": scenario.name,
            "bc_model_path": (
                str(resolved_bc_model_path) if resolved_bc_model_path else None
            ),
        },
    )
    write_run_manifest(workspace_root, manifest_stub)
    append_run_event(
        events_path,
        RunTimelineEvent(
            index=0,
            kind="run_started",
            label=f"{normalized_runner} run started",
            channel="World",
            time_ms=0,
            runner=normalized_runner,
            status="running",
            branch=resolved_branch,
            payload={
                "workspace_name": manifest.name,
                "scenario_name": scenario.name,
                "seed": seed,
                "model": model,
                "provider": provider,
            },
        ),
    )
    upsert_workspace_run(
        workspace_root,
        WorkspaceRunEntry(
            run_id=resolved_run_id,
            scenario_name=scenario.name,
            runner=normalized_runner,
            status="running",
            manifest_path=str(
                (run_dir / "run_manifest.json").relative_to(workspace_root)
            ),
            started_at=manifest_stub.started_at,
            branch=resolved_branch,
        ),
    )

    spec = BenchmarkCaseSpec(
        runner=normalized_runner,
        scenario_name=scenario.scenario_name or scenario.name,
        family_name=scenario.workflow_name,
        workflow_name=scenario.workflow_name,
        workflow_variant=scenario.workflow_variant,
        blueprint_asset_path=blueprint_asset_path,
        seed=seed,
        artifacts_dir=artifacts_dir,
        branch=resolved_branch,
        model=model,
        provider=provider,
        bc_model_path=resolved_bc_model_path,
        task=task,
        max_steps=max_steps,
        metadata={"workspace_name": manifest.name, "workspace_scenario": scenario.name},
    )

    try:
        with _temporary_env("VEI_STATE_DIR", str(state_dir)):
            result = run_benchmark_case(spec)

        contract_eval = evaluate_run_workspace_contract(
            workspace_root,
            run_id=resolved_run_id,
            scenario_name=scenario.name,
        )
        _append_artifact_events(
            workspace_root, resolved_run_id, runner=normalized_runner
        )
        append_run_event(
            events_path,
            RunTimelineEvent(
                index=0,
                kind="run_completed",
                label=f"{normalized_runner} run completed",
                channel="World",
                time_ms=int(result.metrics.time_ms or result.metrics.elapsed_ms or 0),
                runner=normalized_runner,
                status="ok" if result.status == "ok" else "error",
                branch=result.diagnostics.branch or resolved_branch,
                payload={
                    "success": result.success,
                    "error": result.error,
                    "metrics": result.metrics.model_dump(mode="json"),
                    "diagnostics": result.diagnostics.model_dump(mode="json"),
                },
            ),
        )
        timeline = build_run_timeline(workspace_root, resolved_run_id)
        write_run_timeline(workspace_root, resolved_run_id, timeline)

        snapshots = list_run_snapshots(workspace_root, resolved_run_id)
        final_manifest = RunManifest(
            run_id=resolved_run_id,
            workspace_name=manifest.name,
            scenario_name=scenario.name,
            runner=normalized_runner,
            status=("ok" if result.status == "ok" else "error"),
            started_at=manifest_stub.started_at,
            completed_at=_iso_now(),
            seed=seed,
            branch=result.diagnostics.branch or resolved_branch,
            model=model,
            provider=provider,
            bc_model_path=(
                str(resolved_bc_model_path)
                if resolved_bc_model_path is not None
                else None
            ),
            workflow_name=result.diagnostics.workflow_name or scenario.workflow_name,
            workflow_variant=result.diagnostics.workflow_variant
            or scenario.workflow_variant,
            success=result.success,
            metrics=result.metrics,
            diagnostics=result.diagnostics,
            contract=_contract_summary(contract_eval, run_dir),
            artifacts=RunArtifactIndex(
                run_dir=str(run_dir.relative_to(workspace_root)),
                artifacts_dir=str(artifacts_dir.relative_to(workspace_root)),
                state_dir=str(state_dir.relative_to(workspace_root)),
                events_path=str(events_path.relative_to(workspace_root)),
                blueprint_asset_path=str(
                    blueprint_asset_path.relative_to(workspace_root)
                ),
                blueprint_path=_relative_if_exists(
                    workspace_root, artifacts_dir / "blueprint.json"
                ),
                contract_path=contract_path,
                timeline_path=str(
                    (run_dir / "timeline.json").relative_to(workspace_root)
                ),
                benchmark_result_path=_relative_if_exists(
                    workspace_root, artifacts_dir / "benchmark_result.json"
                ),
                score_path=_relative_if_exists(
                    workspace_root, artifacts_dir / "score.json"
                ),
                workflow_result_path=_relative_if_exists(
                    workspace_root, artifacts_dir / "workflow_result.json"
                ),
                transcript_path=_relative_if_exists(
                    workspace_root, artifacts_dir / "transcript.json"
                ),
                trace_path=_relative_if_exists(
                    workspace_root, artifacts_dir / "trace.jsonl"
                ),
            ),
            snapshots=snapshots,
            error=result.error,
            metadata={
                "workspace_scenario": scenario.name,
                "contract_ok": contract_eval.ok if contract_eval is not None else None,
                "bc_model_path": (
                    str(resolved_bc_model_path) if resolved_bc_model_path else None
                ),
            },
        )
        write_run_manifest(workspace_root, final_manifest)
        upsert_workspace_run(
            workspace_root,
            WorkspaceRunEntry(
                run_id=resolved_run_id,
                scenario_name=scenario.name,
                runner=normalized_runner,
                status=final_manifest.status,
                manifest_path=str(
                    (run_dir / "run_manifest.json").relative_to(workspace_root)
                ),
                started_at=manifest_stub.started_at,
                completed_at=final_manifest.completed_at,
                success=final_manifest.success,
                branch=final_manifest.branch,
            ),
        )
        return final_manifest
    except Exception as exc:
        _append_artifact_events(
            workspace_root, resolved_run_id, runner=normalized_runner
        )
        append_run_event(
            events_path,
            RunTimelineEvent(
                index=0,
                kind="run_failed",
                label=f"{normalized_runner} run failed",
                channel="World",
                time_ms=0,
                runner=normalized_runner,
                status="error",
                branch=resolved_branch,
                payload={"error": str(exc)},
            ),
        )
        timeline = build_run_timeline(workspace_root, resolved_run_id)
        if timeline:
            write_run_timeline(workspace_root, resolved_run_id, timeline)
        error_manifest = manifest_stub.model_copy(
            update={
                "status": "error",
                "completed_at": _iso_now(),
                "error": str(exc),
                "artifacts": manifest_stub.artifacts.model_copy(
                    update={
                        "timeline_path": _relative_if_exists(
                            workspace_root, run_dir / "timeline.json"
                        )
                    }
                ),
            }
        )
        write_run_manifest(workspace_root, error_manifest)
        upsert_workspace_run(
            workspace_root,
            WorkspaceRunEntry(
                run_id=resolved_run_id,
                scenario_name=scenario.name,
                runner=normalized_runner,
                status="error",
                manifest_path=str(
                    (run_dir / "run_manifest.json").relative_to(workspace_root)
                ),
                started_at=manifest_stub.started_at,
                completed_at=error_manifest.completed_at,
                success=False,
                branch=resolved_branch,
                metadata={"error": str(exc)},
            ),
        )
        raise


def generate_run_id(*, prefix: str = "run") -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    return f"{prefix}_{stamp}_{uuid4().hex[:6]}"


def list_run_manifests(root: str | Path) -> list[RunManifest]:
    workspace_root = Path(root).expanduser().resolve()
    manifests: list[RunManifest] = []
    for run_entry in list_workspace_runs(workspace_root):
        manifest_path = workspace_root / run_entry.manifest_path
        if manifest_path.exists():
            manifests.append(load_run_manifest(manifest_path))
    return manifests


def load_run_manifest(path: str | Path) -> RunManifest:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return RunManifest.model_validate(payload)


def write_run_manifest(root: str | Path, manifest: RunManifest) -> RunManifest:
    workspace_root = Path(root).expanduser().resolve()
    run_dir = workspace_root / manifest.artifacts.run_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run_manifest.json").write_text(
        manifest.model_dump_json(indent=2), encoding="utf-8"
    )
    return manifest


def get_workspace_runs_dir(root: str | Path) -> Path:
    workspace_root = Path(root).expanduser().resolve()
    manifest = load_workspace(workspace_root)
    return workspace_root / manifest.runs_dir


def get_workspace_run_dir(root: str | Path, run_id: str) -> Path:
    return get_workspace_runs_dir(root) / run_id


def get_workspace_run_manifest_path(root: str | Path, run_id: str) -> Path:
    return get_workspace_run_dir(root, run_id) / "run_manifest.json"


def load_run_timeline(path: str | Path) -> list[RunTimelineEvent]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return [RunTimelineEvent.model_validate(item) for item in payload]


def write_run_timeline(
    root: str | Path, run_id: str, events: list[RunTimelineEvent]
) -> Path:
    workspace_root = Path(root).expanduser().resolve()
    manifest = load_run_manifest(
        get_workspace_run_manifest_path(workspace_root, run_id)
    )
    path = workspace_root / manifest.artifacts.run_dir / "timeline.json"
    path.write_text(
        json.dumps([event.model_dump(mode="json") for event in events], indent=2),
        encoding="utf-8",
    )
    return path


def build_run_timeline(root: str | Path, run_id: str) -> list[RunTimelineEvent]:
    workspace_root = Path(root).expanduser().resolve()
    events_path = get_workspace_run_dir(workspace_root, run_id) / "events.jsonl"
    if events_path.exists():
        events = load_run_events(events_path)
        for idx, item in enumerate(events, start=1):
            item.index = idx
        return events
    return _build_run_timeline_from_artifacts(workspace_root, run_id)


def _build_run_timeline_from_artifacts(
    workspace_root: Path, run_id: str
) -> list[RunTimelineEvent]:
    run_dir = get_workspace_run_dir(workspace_root, run_id)
    artifacts_dir = run_dir / "artifacts"
    events: list[RunTimelineEvent] = []
    index = 1

    trace_path = artifacts_dir / "trace.jsonl"
    if trace_path.exists():
        for record in load_trace(trace_path):
            record_type = str(record.get("type", "")).lower()
            time_ms = int(record.get("time_ms", 0))
            if record_type == "call":
                tool = str(record.get("tool", ""))
                events.append(
                    RunTimelineEvent(
                        index=index,
                        kind="trace_call",
                        label=f"{tool}",
                        channel=flow_channel_from_tool(tool),
                        time_ms=time_ms,
                        tool=tool,
                        object_refs=_infer_object_refs(tool, record.get("args", {})),
                        payload={
                            "args": record.get("args", {}),
                            "response": record.get("response", {}),
                        },
                    )
                )
                index += 1
            elif record_type == "event":
                target = str(record.get("target", "world"))
                events.append(
                    RunTimelineEvent(
                        index=index,
                        kind="trace_event",
                        label=f"{target} event",
                        channel=flow_channel_from_focus(target),
                        time_ms=time_ms,
                        object_refs=_infer_object_refs(
                            target, record.get("payload", {})
                        ),
                        payload={
                            "target": target,
                            "payload": record.get("payload", {}),
                            "emitted": record.get("emitted", {}),
                        },
                    )
                )
                index += 1

    workflow_result_path = artifacts_dir / "workflow_result.json"
    if workflow_result_path.exists():
        workflow_payload = json.loads(workflow_result_path.read_text(encoding="utf-8"))
        for step in workflow_payload.get("steps", []):
            tool = str(step.get("tool", "vei.graph_action"))
            resolved_tool = (
                str(step.get("resolved_tool")) if step.get("resolved_tool") else None
            )
            graph_domain = (
                str(step.get("graph_domain")) if step.get("graph_domain") else None
            )
            graph_action = (
                str(step.get("graph_action")) if step.get("graph_action") else None
            )
            graph_intent = (
                str(step.get("graph_intent"))
                if step.get("graph_intent")
                else (
                    f"{graph_domain}.{graph_action}"
                    if graph_domain and graph_action
                    else None
                )
            )
            channel = flow_channel_from_tool(resolved_tool or tool)
            object_refs = [
                str(item)
                for item in (
                    step.get("object_refs")
                    or _infer_object_refs(
                        resolved_tool or tool,
                        {
                            **dict(step.get("result", {}) or {}),
                            **dict(step.get("args", {}) or {}),
                        },
                    )
                )
            ]
            events.append(
                RunTimelineEvent(
                    index=index,
                    kind="workflow_step",
                    label=str(step.get("step_id", "workflow-step")),
                    channel=channel,
                    time_ms=int(step.get("time_ms", 0) or 0),
                    tool=tool,
                    resolved_tool=resolved_tool,
                    graph_action_ref=(
                        str(step.get("graph_action_ref"))
                        if step.get("graph_action_ref")
                        else None
                    ),
                    graph_domain=graph_domain,
                    graph_action=graph_action,
                    graph_intent=graph_intent,
                    object_refs=object_refs,
                    payload={
                        "args": step.get("args", {}),
                        "result": step.get("result", {}),
                        "observation": step.get("observation", {}),
                        "assertion_failures": step.get("assertion_failures", []),
                    },
                )
            )
            index += 1

    receipts_path = artifacts_dir / "connector_receipts.jsonl"
    if receipts_path.exists():
        for raw in receipts_path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            receipt = json.loads(raw)
            events.append(
                RunTimelineEvent(
                    index=index,
                    kind="receipt",
                    label=f"{receipt.get('service', 'connector')}:{receipt.get('operation', 'receipt')}",
                    channel="World",
                    time_ms=int(receipt.get("time_ms", 0) or 0),
                    object_refs=_infer_object_refs(
                        f"{receipt.get('service', 'world')}.{receipt.get('operation', 'receipt')}",
                        receipt,
                    ),
                    payload=receipt,
                )
            )
            index += 1

    for snapshot in list_run_snapshots(workspace_root, run_id):
        events.append(
            RunTimelineEvent(
                index=index,
                kind="snapshot",
                label=snapshot.label or f"snapshot {snapshot.snapshot_id}",
                channel="World",
                time_ms=snapshot.time_ms,
                snapshot_id=snapshot.snapshot_id,
                branch=snapshot.branch,
                payload={"path": snapshot.path},
            )
        )
        index += 1

    contract_eval_path = run_dir / "workspace_contract_evaluation.json"
    if contract_eval_path.exists():
        contract_eval = json.loads(contract_eval_path.read_text(encoding="utf-8"))
        events.append(
            RunTimelineEvent(
                index=index,
                kind="contract",
                label=f"contract {'passed' if contract_eval.get('ok') else 'failed'}",
                channel="World",
                time_ms=int(contract_eval.get("metadata", {}).get("time_ms", 0) or 0),
                payload=contract_eval,
            )
        )

    events.sort(key=lambda item: (item.time_ms, item.index))
    for idx, item in enumerate(events, start=1):
        item.index = idx
    return events


def load_run_events_for_run(root: str | Path, run_id: str) -> list[RunTimelineEvent]:
    workspace_root = Path(root).expanduser().resolve()
    path = get_workspace_run_dir(workspace_root, run_id) / "events.jsonl"
    if not path.exists():
        return []
    return load_run_events(path)


def list_run_snapshots(root: str | Path, run_id: str) -> list[RunSnapshotRef]:
    workspace_root = Path(root).expanduser().resolve()
    run_dir = get_workspace_run_dir(workspace_root, run_id)
    manifest_path = get_workspace_run_manifest_path(workspace_root, run_id)
    branch = None
    if manifest_path.exists():
        branch = load_run_manifest(manifest_path).branch
    if branch is None:
        return []
    state_dir = run_dir / "state"
    store = StateStore(base_dir=state_dir, branch=branch)
    refs: list[RunSnapshotRef] = []
    for snapshot_path in store.list_snapshot_paths():
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        refs.append(
            RunSnapshotRef(
                snapshot_id=int(payload.get("index", 0)),
                branch=str(payload.get("branch", branch)),
                label=(str(payload.get("label")) if payload.get("label") else None),
                time_ms=int(payload.get("clock_ms", 0) or 0),
                path=str(snapshot_path.relative_to(workspace_root)),
            )
        )
    return refs


def load_run_snapshot_payload(
    root: str | Path, run_id: str, snapshot_id: int
) -> Dict[str, Any]:
    workspace_root = Path(root).expanduser().resolve()
    for snapshot in list_run_snapshots(workspace_root, run_id):
        if snapshot.snapshot_id == snapshot_id:
            return json.loads(
                (workspace_root / snapshot.path).read_text(encoding="utf-8")
            )
    raise ValueError(f"snapshot not found: {snapshot_id}")


def diff_run_snapshots(
    root: str | Path, run_id: str, snapshot_from: int, snapshot_to: int
) -> Dict[str, Any]:
    before = load_run_snapshot_payload(root, run_id, snapshot_from)
    after = load_run_snapshot_payload(root, run_id, snapshot_to)
    flat_before: Dict[str, Any] = {}
    flat_after: Dict[str, Any] = {}
    _flatten_json("", before.get("data", {}), flat_before)
    _flatten_json("", after.get("data", {}), flat_after)
    keys = sorted(set(flat_before) | set(flat_after))
    return {
        "from": snapshot_from,
        "to": snapshot_to,
        "added": {key: flat_after[key] for key in keys if key not in flat_before},
        "removed": {key: flat_before[key] for key in keys if key not in flat_after},
        "changed": {
            key: {"from": flat_before[key], "to": flat_after[key]}
            for key in keys
            if key in flat_before
            and key in flat_after
            and flat_before[key] != flat_after[key]
        },
    }


def get_run_orientation(root: str | Path, run_id: str) -> Dict[str, Any]:
    state = _latest_run_state(root, run_id)
    return build_world_orientation(state).model_dump(mode="json")


def get_run_capability_graphs(root: str | Path, run_id: str) -> Dict[str, Any]:
    state = _latest_run_state(root, run_id)
    return build_runtime_capability_graphs(state).model_dump(mode="json")


def get_run_surface_state(root: str | Path, run_id: str) -> LivingSurfaceState:
    workspace_root = Path(root).expanduser().resolve()
    state = _latest_run_state(workspace_root, run_id)
    if state is None:
        raise ValueError(f"run has no snapshots: {run_id}")

    workspace = load_workspace(workspace_root)
    run_manifest = load_run_manifest(
        get_workspace_run_manifest_path(workspace_root, run_id)
    )
    orientation = build_world_orientation(state)
    vertical_name = _surface_vertical_name(state, workspace)
    company_name = orientation.organization_name or workspace.title or workspace.name
    current_tension = _surface_current_tension(state, orientation)
    latest_snapshot = list_run_snapshots(workspace_root, run_id)

    panels = [
        _build_chat_panel(state.components.get("slack", {})),
        _build_mail_panel(state.components.get("mail", {})),
        _build_ticket_panel(state.components.get("tickets", {})),
        _build_docs_panel(
            state.components.get("docs", {}),
            state.components.get("google_admin", {}),
        ),
        _build_approval_panel(state.components.get("servicedesk", {})),
        _build_vertical_panel(vertical_name, state.components),
    ]

    return LivingSurfaceState(
        company_name=company_name,
        vertical_name=vertical_name,
        run_id=run_id,
        branch=run_manifest.branch or state.branch,
        snapshot_id=(latest_snapshot[-1].snapshot_id if latest_snapshot else 0),
        current_tension=current_tension,
        panels=[panel for panel in panels if panel is not None],
    )


def load_run_contract_evaluation(
    root: str | Path, run_id: str
) -> Dict[str, Any] | None:
    workspace_root = Path(root).expanduser().resolve()
    path = (
        get_workspace_run_dir(workspace_root, run_id)
        / "workspace_contract_evaluation.json"
    )
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate_run_workspace_contract(
    root: str | Path,
    *,
    run_id: str,
    scenario_name: Optional[str] = None,
) -> ContractEvaluationResult | None:
    workspace_root = Path(root).expanduser().resolve()
    run_dir = get_workspace_run_dir(workspace_root, run_id)
    if not run_dir.exists():
        return None
    evaluation_inputs = _extract_run_evaluation_inputs(workspace_root, run_id)
    if evaluation_inputs is None:
        return None
    result = evaluate_workspace_contract_against_state(
        root=workspace_root,
        scenario_name=scenario_name,
        **evaluation_inputs,
    )
    (run_dir / "workspace_contract_evaluation.json").write_text(
        result.model_dump_json(indent=2), encoding="utf-8"
    )
    return result


def _extract_run_evaluation_inputs(
    workspace_root: Path, run_id: str
) -> Dict[str, Any] | None:
    run_dir = get_workspace_run_dir(workspace_root, run_id)
    artifacts_dir = run_dir / "artifacts"
    state = _latest_run_state(workspace_root, run_id)
    if state is None:
        return None

    workflow_result_path = artifacts_dir / "workflow_result.json"
    if workflow_result_path.exists():
        payload = json.loads(workflow_result_path.read_text(encoding="utf-8"))
        steps = payload.get("steps", [])
        final_step = steps[-1] if steps else {}
        return {
            "oracle_state": state.model_dump(mode="json"),
            "visible_observation": final_step.get("observation", {}),
            "result": final_step.get("result", {}),
            "pending": {},
            "time_ms": int(payload.get("metadata", {}).get("time_ms", 0) or 0),
            "available_tools": None,
        }

    transcript_path = artifacts_dir / "transcript.json"
    last_observation: Dict[str, Any] = {}
    last_result: Any = {}
    if transcript_path.exists():
        transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
        if isinstance(transcript, list):
            for item in transcript:
                if isinstance(item, dict) and isinstance(item.get("observation"), dict):
                    last_observation = item["observation"]
                if isinstance(item, dict) and isinstance(item.get("result"), dict):
                    last_result = item["result"]
    return {
        "oracle_state": state.model_dump(mode="json"),
        "visible_observation": last_observation,
        "result": last_result,
        "pending": {},
        "time_ms": int(state.clock_ms),
        "available_tools": None,
    }


def _latest_run_state(root: str | Path, run_id: str) -> WorldState | None:
    workspace_root = Path(root).expanduser().resolve()
    snapshots = list_run_snapshots(workspace_root, run_id)
    if not snapshots:
        return None
    latest = snapshots[-1]
    payload = json.loads((workspace_root / latest.path).read_text(encoding="utf-8"))
    return WorldState.model_validate(payload.get("data", {}))


def _surface_vertical_name(state: WorldState, workspace: Any) -> str:
    metadata = _scenario_metadata_map(state)
    builder_environment = metadata.get("builder_environment")
    if isinstance(builder_environment, dict):
        vertical = builder_environment.get("vertical")
        if isinstance(vertical, str) and vertical:
            return vertical
    builder_graphs = metadata.get("builder_capability_graphs")
    if isinstance(builder_graphs, dict):
        graph_metadata = builder_graphs.get("metadata")
        if isinstance(graph_metadata, dict):
            vertical = graph_metadata.get("vertical")
            if isinstance(vertical, str) and vertical:
                return vertical
    if isinstance(workspace.source_ref, str) and workspace.source_ref:
        return workspace.source_ref
    return "workspace"


def _surface_current_tension(state: WorldState, orientation: Any) -> str:
    metadata = _scenario_metadata_map(state)
    builder_environment = metadata.get("builder_environment")
    if isinstance(builder_environment, dict):
        scenario_brief = builder_environment.get("scenario_brief")
        if isinstance(scenario_brief, str) and scenario_brief:
            return scenario_brief
    builder_graphs = metadata.get("builder_capability_graphs")
    if isinstance(builder_graphs, dict):
        scenario_brief = builder_graphs.get("scenario_brief")
        if isinstance(scenario_brief, str) and scenario_brief:
            return scenario_brief
    description = state.scenario.get("description")
    if isinstance(description, str) and description:
        return description
    return orientation.summary


def _scenario_metadata_map(state: WorldState) -> Dict[str, Any]:
    metadata = state.scenario.get("metadata")
    if isinstance(metadata, dict):
        return metadata
    return {}


def _dict_records(payload: Dict[str, Any], key: str) -> Dict[str, Dict[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, dict):
        return {}
    return {
        str(record_key): item
        for record_key, item in value.items()
        if isinstance(item, dict)
    }


def _dict_list(payload: Dict[str, Any], key: str) -> list[Dict[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _build_chat_panel(slack: Dict[str, Any]) -> LivingSurfacePanel | None:
    channels = slack.get("channels")
    if not isinstance(channels, dict) or not channels:
        return None

    rows: list[tuple[float, str, Dict[str, Any], int]] = []
    for channel_name, payload in channels.items():
        if not isinstance(payload, dict):
            continue
        unread = int(payload.get("unread", 0) or 0)
        for message in payload.get("messages", []):
            if isinstance(message, dict):
                rows.append(
                    (_slack_ts(message.get("ts")), channel_name, message, unread)
                )

    if not rows:
        return None

    rows.sort(key=lambda item: item[0], reverse=True)
    items = [
        LivingSurfaceItem(
            item_id=f"chat:{channel_name}:{message.get('ts', index)}",
            title=str(message.get("user", "team member")),
            subtitle=channel_name,
            body=_truncate(str(message.get("text", "")), 160),
            status=("attention" if unread else "ok"),
            badges=_compact_badges(
                [
                    channel_name,
                    "thread reply" if message.get("thread_ts") else "",
                    f"{unread} unread" if unread else "",
                ]
            ),
            highlight_ref=f"slack:{channel_name}:{message.get('ts', index)}",
        )
        for index, (_, channel_name, message, unread) in enumerate(rows[:8], start=1)
    ]
    unread_total = sum(
        int(payload.get("unread", 0) or 0)
        for payload in channels.values()
        if isinstance(payload, dict)
    )
    return _surface_panel(
        surface="slack",
        kind="chat",
        title="Team Chat",
        accent="#36c5f0",
        headline=f"{len(channels)} channels · {len(rows)} messages",
        items=items,
        fallback_status=("attention" if unread_total else "ok"),
    )


def _build_mail_panel(mail: Dict[str, Any]) -> LivingSurfacePanel | None:
    messages = mail.get("messages")
    if not isinstance(messages, dict) or not messages:
        return None

    threads: Dict[str, list[Dict[str, Any]]] = {}
    for message in messages.values():
        if not isinstance(message, dict):
            continue
        thread_id = str(message.get("thread_id") or message.get("subj") or "mail")
        threads.setdefault(thread_id, []).append(message)

    if not threads:
        return None

    rows: list[tuple[int, str, list[Dict[str, Any]]]] = []
    for thread_id, thread_messages in threads.items():
        latest_time = max(int(item.get("time_ms", 0) or 0) for item in thread_messages)
        rows.append((latest_time, thread_id, thread_messages))
    rows.sort(key=lambda item: item[0], reverse=True)

    items = []
    unread_total = 0
    for _, thread_id, thread_messages in rows[:6]:
        ordered = sorted(
            thread_messages,
            key=lambda item: int(item.get("time_ms", 0) or 0),
            reverse=True,
        )
        latest = ordered[0]
        unread_count = sum(1 for item in thread_messages if item.get("unread"))
        unread_total += unread_count
        items.append(
            LivingSurfaceItem(
                item_id=f"mail:{thread_id}",
                title=str(latest.get("subj", thread_id)),
                subtitle=str(latest.get("from", "inbox")),
                body=_truncate(str(latest.get("body_text", "")), 160),
                status=("attention" if unread_count else "ok"),
                badges=_compact_badges(
                    [
                        str(latest.get("category", "")),
                        f"{len(thread_messages)} messages",
                        f"{unread_count} unread" if unread_count else "",
                    ]
                ),
                highlight_ref=f"mail:{thread_id}",
            )
        )

    return _surface_panel(
        surface="mail",
        kind="mail",
        title="Email",
        accent="#ffb454",
        headline=f"{len(threads)} threads · {unread_total} unread",
        items=items,
        fallback_status=("attention" if unread_total else "ok"),
    )


def _build_ticket_panel(tickets: Dict[str, Any]) -> LivingSurfacePanel | None:
    payload = tickets.get("tickets")
    if not isinstance(payload, dict) or not payload:
        return None

    ordered = sorted(
        (item for item in payload.values() if isinstance(item, dict)),
        key=lambda item: (
            _ticket_sort_rank(str(item.get("status", ""))),
            str(item.get("ticket_id", "")),
        ),
    )
    items = [
        LivingSurfaceItem(
            item_id=f"ticket:{item.get('ticket_id', index)}",
            title=str(item.get("title", item.get("ticket_id", "ticket"))),
            subtitle=str(item.get("assignee", "unassigned")),
            body=_truncate(str(item.get("description", "")), 140),
            status=str(item.get("status", "")),
            badges=_compact_badges(
                [str(item.get("status", "")), str(item.get("ticket_id", ""))]
            ),
            highlight_ref=f"ticket:{item.get('ticket_id', index)}",
        )
        for index, item in enumerate(ordered[:8], start=1)
    ]
    return _surface_panel(
        surface="tickets",
        kind="queue",
        title="Work Tracker",
        accent="#ff6d5e",
        headline=f"{len(payload)} active tickets",
        items=items,
    )


def _build_docs_panel(
    docs: Dict[str, Any],
    google_admin: Dict[str, Any],
) -> LivingSurfacePanel | None:
    payload = _dict_records(docs, "docs")
    if not payload:
        return None

    metadata = _dict_records(docs, "metadata")
    shares = _dict_records(google_admin, "drive_shares")
    ordered = sorted(
        payload.values(),
        key=lambda item: int(
            metadata.get(str(item.get("doc_id")), {}).get("updated_ms", 0) or 0
        ),
        reverse=True,
    )

    items = []
    for index, item in enumerate(ordered[:6], start=1):
        doc_id = str(item.get("doc_id", index))
        share = shares.get(doc_id)
        tags = (
            [str(tag) for tag in item.get("tags", [])]
            if isinstance(item.get("tags"), list)
            else []
        )
        items.append(
            LivingSurfaceItem(
                item_id=f"doc:{doc_id}",
                title=str(item.get("title", doc_id)),
                subtitle=doc_id,
                body=_truncate(str(item.get("body", "")), 160),
                status="ok",
                badges=_compact_badges(
                    tags[:2]
                    + (
                        [str(share.get("visibility", ""))]
                        if isinstance(share, dict)
                        else []
                    )
                ),
                highlight_ref=f"doc:{doc_id}",
            )
        )

    return _surface_panel(
        surface="docs",
        kind="document",
        title="Documents",
        accent="#1aa88d",
        headline=f"{len(payload)} artifacts in circulation",
        items=items,
    )


def _build_approval_panel(servicedesk: Dict[str, Any]) -> LivingSurfacePanel | None:
    requests = _dict_records(servicedesk, "requests")
    if not requests:
        return None

    ordered = sorted(
        requests.values(),
        key=lambda item: (
            _approval_sort_rank(str(item.get("status", ""))),
            str(item.get("request_id", "")),
        ),
    )
    items = []
    for index, item in enumerate(ordered[:8], start=1):
        approvals = _dict_list(item, "approvals")
        pending_count = sum(
            1
            for approval in approvals
            if str(approval.get("status", "")).upper() == "PENDING"
        )
        items.append(
            LivingSurfaceItem(
                item_id=f"request:{item.get('request_id', index)}",
                title=str(item.get("title", item.get("request_id", "request"))),
                subtitle=str(item.get("requester", "requester")),
                body=_truncate(str(item.get("description", "")), 140),
                status=str(item.get("status", "")),
                badges=_compact_badges(
                    [
                        str(item.get("status", "")),
                        f"{pending_count} pending" if pending_count else "",
                    ]
                ),
                highlight_ref=f"request:{item.get('request_id', index)}",
            )
        )

    pending_total = sum(
        1
        for item in ordered
        if str(item.get("status", "")).lower()
        in {"pending_approval", "pending", "review"}
    )
    return _surface_panel(
        surface="approvals",
        kind="approval",
        title="Approvals",
        accent="#9b7bff",
        headline=f"{len(requests)} routed requests",
        items=items,
        fallback_status=("warning" if pending_total else "ok"),
    )


def _build_vertical_panel(
    vertical_name: str,
    components: Dict[str, Dict[str, Any]],
) -> LivingSurfacePanel | None:
    if vertical_name == "real_estate_management":
        return _build_property_panel(components.get("property_ops", {}))
    if vertical_name == "digital_marketing_agency":
        return _build_campaign_panel(components.get("campaign_ops", {}))
    if vertical_name == "storage_solutions":
        return _build_inventory_panel(components.get("inventory_ops", {}))
    return None


def _build_property_panel(property_ops: Dict[str, Any]) -> LivingSurfacePanel | None:
    if not isinstance(property_ops, dict) or not any(
        property_ops.get(key) for key in ("leases", "units", "work_orders")
    ):
        return None

    items: list[LivingSurfaceItem] = []
    leases = _dict_records(property_ops, "leases")
    units = _dict_records(property_ops, "units")
    work_orders = _dict_records(property_ops, "work_orders")
    vendors = _dict_records(property_ops, "vendors")

    for lease_id, lease in list(leases.items())[:2]:
        if not isinstance(lease, dict):
            continue
        unit = units.get(str(lease.get("unit_id")))
        items.append(
            LivingSurfaceItem(
                item_id=f"lease:{lease_id}",
                title=f"Lease {lease_id}",
                subtitle=(
                    str(unit.get("label", lease.get("unit_id", "")))
                    if isinstance(unit, dict)
                    else str(lease.get("unit_id", ""))
                ),
                body=_truncate(
                    f"Milestone {lease.get('milestone', 'unknown')} · amendment {'pending' if lease.get('amendment_pending') else 'cleared'}",
                    160,
                ),
                status=str(lease.get("status", "")),
                badges=_compact_badges(
                    [
                        str(lease.get("status", "")),
                        str(lease.get("milestone", "")),
                    ]
                ),
                highlight_ref=f"lease:{lease_id}",
            )
        )

    for work_order_id, work_order in list(work_orders.items())[:2]:
        if not isinstance(work_order, dict):
            continue
        vendor = vendors.get(str(work_order.get("vendor_id")))
        items.append(
            LivingSurfaceItem(
                item_id=f"work_order:{work_order_id}",
                title=str(work_order.get("title", work_order_id)),
                subtitle=(
                    str(vendor.get("name"))
                    if isinstance(vendor, dict)
                    else "vendor unassigned"
                ),
                body=_truncate(
                    f"Status {work_order.get('status', 'unknown')}",
                    160,
                ),
                status=str(work_order.get("status", "")),
                badges=_compact_badges(
                    [
                        str(work_order.get("status", "")),
                        str(work_order_id),
                    ]
                ),
                highlight_ref=f"work_order:{work_order_id}",
            )
        )

    for unit_id, unit in list(units.items())[:2]:
        if not isinstance(unit, dict):
            continue
        items.append(
            LivingSurfaceItem(
                item_id=f"unit:{unit_id}",
                title=f"Unit {unit.get('label', unit_id)}",
                subtitle=str(unit.get("reserved_for", "open")),
                body=_truncate(f"Status {unit.get('status', 'unknown')}", 140),
                status=str(unit.get("status", "")),
                badges=_compact_badges([str(unit.get("status", ""))]),
                highlight_ref=f"unit:{unit_id}",
            )
        )

    return _surface_panel(
        surface="vertical_heartbeat",
        kind="vertical_heartbeat",
        title="Opening Readiness",
        accent="#1e6cf2",
        headline=f"{len(leases)} leases · {len(work_orders)} work orders · {len(units)} units",
        items=items[:6],
    )


def _build_campaign_panel(campaign_ops: Dict[str, Any]) -> LivingSurfacePanel | None:
    if not isinstance(campaign_ops, dict) or not any(
        campaign_ops.get(key)
        for key in ("campaigns", "creatives", "approvals", "reports")
    ):
        return None

    items: list[LivingSurfaceItem] = []
    campaigns = _dict_records(campaign_ops, "campaigns")
    creatives = _dict_records(campaign_ops, "creatives")
    approvals = _dict_records(campaign_ops, "approvals")
    reports = _dict_records(campaign_ops, "reports")

    for campaign_id, campaign in list(campaigns.items())[:2]:
        if not isinstance(campaign, dict):
            continue
        items.append(
            LivingSurfaceItem(
                item_id=f"campaign:{campaign_id}",
                title=str(campaign.get("name", campaign_id)),
                subtitle=str(campaign.get("channel", "campaign")),
                body=_truncate(
                    f"Pacing {campaign.get('pacing_pct', 0)}% · spend ${campaign.get('spend_usd', 0):,} / ${campaign.get('budget_usd', 0):,}",
                    160,
                ),
                status=str(campaign.get("status", "")),
                badges=_compact_badges([str(campaign.get("status", ""))]),
                highlight_ref=f"campaign:{campaign_id}",
            )
        )

    for creative_id, creative in list(creatives.items())[:2]:
        if not isinstance(creative, dict):
            continue
        items.append(
            LivingSurfaceItem(
                item_id=f"creative:{creative_id}",
                title=str(creative.get("title", creative_id)),
                subtitle=str(creative.get("campaign_id", "")),
                body=_truncate(
                    f"Status {creative.get('status', 'unknown')} · approval {'required' if creative.get('approval_required') else 'not required'}",
                    160,
                ),
                status=str(creative.get("status", "")),
                badges=_compact_badges([str(creative.get("status", ""))]),
                highlight_ref=f"creative:{creative_id}",
            )
        )

    for approval_id, approval in list(approvals.items())[:1]:
        if not isinstance(approval, dict):
            continue
        items.append(
            LivingSurfaceItem(
                item_id=f"approval:{approval_id}",
                title=f"Approval {approval.get('stage', approval_id)}",
                subtitle=str(approval.get("campaign_id", "")),
                body=_truncate(f"Status {approval.get('status', 'unknown')}", 140),
                status=str(approval.get("status", "")),
                badges=_compact_badges([str(approval.get("status", ""))]),
                highlight_ref=f"approval:{approval_id}",
            )
        )

    for report_id, report in list(reports.items())[:1]:
        if not isinstance(report, dict):
            continue
        items.append(
            LivingSurfaceItem(
                item_id=f"report:{report_id}",
                title=str(report.get("title", report_id)),
                subtitle=str(report.get("campaign_id", "")),
                body=_truncate(
                    f"Report is {'stale' if report.get('stale') else 'fresh'}",
                    140,
                ),
                status=str(report.get("status", "")),
                badges=_compact_badges([str(report.get("status", ""))]),
                highlight_ref=f"report:{report_id}",
            )
        )

    return _surface_panel(
        surface="vertical_heartbeat",
        kind="vertical_heartbeat",
        title="Launch Readiness",
        accent="#1e6cf2",
        headline=f"{len(campaigns)} campaigns · {len(creatives)} creatives · {len(approvals)} approvals",
        items=items[:6],
    )


def _build_inventory_panel(inventory_ops: Dict[str, Any]) -> LivingSurfacePanel | None:
    if not isinstance(inventory_ops, dict) or not any(
        inventory_ops.get(key) for key in ("quotes", "capacity_pools", "orders")
    ):
        return None

    items: list[LivingSurfaceItem] = []
    quotes = _dict_records(inventory_ops, "quotes")
    pools = _dict_records(inventory_ops, "capacity_pools")
    orders = _dict_records(inventory_ops, "orders")
    allocations = _dict_records(inventory_ops, "allocations")

    for quote_id, quote in list(quotes.items())[:2]:
        if not isinstance(quote, dict):
            continue
        items.append(
            LivingSurfaceItem(
                item_id=f"quote:{quote_id}",
                title=str(quote.get("customer_name", quote_id)),
                subtitle=str(quote_id),
                body=_truncate(
                    f"Requested {quote.get('requested_units', 0)} · committed {quote.get('committed_units', 0)}",
                    160,
                ),
                status=str(quote.get("status", "")),
                badges=_compact_badges([str(quote.get("status", ""))]),
                highlight_ref=f"quote:{quote_id}",
            )
        )

    for pool_id, pool in list(pools.items())[:2]:
        if not isinstance(pool, dict):
            continue
        total_units = int(pool.get("total_units", 0) or 0)
        reserved_units = int(pool.get("reserved_units", 0) or 0)
        headroom = max(total_units - reserved_units, 0)
        items.append(
            LivingSurfaceItem(
                item_id=f"capacity_pool:{pool_id}",
                title=str(pool.get("name", pool_id)),
                subtitle=str(pool.get("site_id", "")),
                body=_truncate(f"Headroom {headroom} of {total_units} units", 140),
                status=(
                    "critical"
                    if headroom <= 10
                    else "warning" if headroom <= 30 else "ok"
                ),
                badges=_compact_badges([f"{reserved_units}/{total_units} reserved"]),
                highlight_ref=f"capacity_pool:{pool_id}",
            )
        )

    for order_id, order in list(orders.items())[:1]:
        if not isinstance(order, dict):
            continue
        items.append(
            LivingSurfaceItem(
                item_id=f"order:{order_id}",
                title=f"Order {order_id}",
                subtitle=str(order.get("site_id", "")),
                body=_truncate(f"Status {order.get('status', 'unknown')}", 140),
                status=str(order.get("status", "")),
                badges=_compact_badges([str(order.get("status", ""))]),
                highlight_ref=f"order:{order_id}",
            )
        )

    for allocation_id, allocation in list(allocations.items())[:1]:
        if not isinstance(allocation, dict):
            continue
        items.append(
            LivingSurfaceItem(
                item_id=f"allocation:{allocation_id}",
                title=f"Allocation {allocation_id}",
                subtitle=str(allocation.get("pool_id", "")),
                body=_truncate(f"{allocation.get('units', 0)} units reserved", 140),
                status=str(allocation.get("status", "")),
                badges=_compact_badges([str(allocation.get("status", ""))]),
                highlight_ref=f"allocation:{allocation_id}",
            )
        )

    return _surface_panel(
        surface="vertical_heartbeat",
        kind="vertical_heartbeat",
        title="Commitment Readiness",
        accent="#1e6cf2",
        headline=f"{len(quotes)} quotes · {len(pools)} pools · {len(orders)} orders",
        items=items[:6],
    )


def _surface_panel(
    *,
    surface: str,
    kind: str,
    title: str,
    accent: str,
    headline: str,
    items: list[LivingSurfaceItem],
    fallback_status: str | None = None,
) -> LivingSurfacePanel | None:
    if not items:
        return None
    return LivingSurfacePanel(
        surface=surface,
        kind=kind,
        title=title,
        accent=accent,
        status=_surface_status(items, fallback=fallback_status or "ok"),
        headline=headline,
        items=items,
        highlight_refs=[
            item.highlight_ref for item in items if item.highlight_ref is not None
        ],
    )


def _surface_status(
    items: list[LivingSurfaceItem],
    *,
    fallback: str,
) -> str:
    levels = [str(item.status or "").lower() for item in items]
    if any(
        level in {"critical", "pending_vendor", "stale", "launch_risk"}
        for level in levels
    ):
        return "critical"
    if any(
        level in {"warning", "pending", "pending_approval", "review"}
        for level in levels
    ):
        return "warning"
    if any(
        level in {"attention", "open", "in_progress", "scheduled", "draft"}
        for level in levels
    ):
        return "attention"
    return fallback


def _ticket_sort_rank(status: str) -> int:
    normalized = status.lower()
    if normalized in {"open", "pending"}:
        return 0
    if normalized in {"in_progress", "review"}:
        return 1
    if normalized in {"scheduled", "ready"}:
        return 2
    return 3


def _approval_sort_rank(status: str) -> int:
    normalized = status.lower()
    if normalized in {"pending_approval", "pending"}:
        return 0
    if normalized in {"in_progress", "review"}:
        return 1
    if normalized in {"approved", "complete"}:
        return 2
    return 3


def _compact_badges(values: list[str]) -> list[str]:
    return [value for value in values if value]


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return f"{value[: limit - 1].rstrip()}…"


def _slack_ts(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _append_artifact_events(root: Path, run_id: str, *, runner: str) -> None:
    run_dir = get_workspace_run_dir(root, run_id)
    events_path = run_dir / "events.jsonl"
    existing_keys: set[tuple[str, str, int, str | None]] = set()
    if events_path.exists():
        for event in load_run_events(events_path):
            existing_keys.add(
                (
                    event.kind,
                    event.label,
                    int(event.time_ms),
                    event.graph_action_ref or event.tool,
                )
            )
    pending_events = _build_run_timeline_from_artifacts(root, run_id)
    appendable: list[RunTimelineEvent] = []
    for event in pending_events:
        key = (
            event.kind,
            event.label,
            int(event.time_ms),
            event.graph_action_ref or event.tool,
        )
        if key in existing_keys:
            continue
        event.runner = runner
        appendable.append(event)
        existing_keys.add(key)
    if appendable:
        append_run_events(events_path, appendable)


def _infer_object_refs(tool: str, payload: Dict[str, Any]) -> list[str]:
    refs: set[str] = set()
    normalized_tool = tool.strip().lower()

    def _add(prefix: str, key: str) -> None:
        value = payload.get(key)
        if value not in (None, ""):
            refs.add(f"{prefix}:{value}")

    if "okta" in normalized_tool or "identity" in normalized_tool:
        _add("identity_user", "user_id")
        _add("identity_group", "group_id")
        _add("identity_application", "app_id")
    if "google_admin" in normalized_tool or "doc" in normalized_tool:
        if (
            "restrict_drive_share" in normalized_tool
            or "transfer_drive_ownership" in normalized_tool
        ):
            _add("drive_share", "doc_id")
        else:
            _add("document", "doc_id")
    if "jira" in normalized_tool or "ticket" in normalized_tool:
        _add("ticket", "issue_id")
        _add("ticket", "ticket_id")
        _add("service_request", "request_id")
        _add("incident", "incident_id")
    if "slack" in normalized_tool or "comm_graph" in normalized_tool:
        _add("comm_channel", "channel")
    if "crm" in normalized_tool:
        _add("crm_deal", "id")
        _add("crm_deal", "deal_id")
    if "hris" in normalized_tool:
        _add("hris_employee", "employee_id")
    return sorted(refs)


def _flatten_json(prefix: str, value: Any, out: Dict[str, Any]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            _flatten_json(next_prefix, item, out)
        return
    out[prefix] = value


def _contract_summary(
    result: ContractEvaluationResult | None, run_dir: Path
) -> RunContractSummary:
    if result is None:
        return RunContractSummary()
    issue_count = len(result.static_validation.issues) + len(
        result.dynamic_validation.issues
    )
    return RunContractSummary(
        contract_name=result.contract_name,
        ok=result.ok,
        success_assertion_count=(
            result.success_predicate_count + result.forbidden_predicate_count
        ),
        success_assertions_passed=(
            result.success_predicates_passed
            + max(
                0, result.forbidden_predicate_count - result.forbidden_predicates_failed
            )
        ),
        success_assertions_failed=(
            result.success_predicates_failed + result.forbidden_predicates_failed
        ),
        issue_count=issue_count,
        evaluation_path=str((run_dir / "workspace_contract_evaluation.json").name),
    )


def _relative_if_exists(root: Path, path: Path) -> str | None:
    if not path.exists():
        return None
    return str(path.relative_to(root))


@contextmanager
def _temporary_env(name: str, value: str | None):
    import os

    previous = os.environ.get(name)
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous


def _iso_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def normalize_runner(runner: str) -> BenchmarkRunner:
    normalized = runner.strip().lower()
    if normalized not in {"workflow", "scripted", "bc", "llm"}:
        raise ValueError("runner must be workflow, scripted, bc, or llm")
    return normalized  # type: ignore[return-value]
