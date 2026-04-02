from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from vei.playable import (
    activate_workspace_playable_mission,
    apply_workspace_mission_move,
    branch_workspace_mission_run,
    build_mission_run_exports,
    export_mission_run,
    finish_workspace_mission_run,
    get_service_ops_policy_bundle,
    list_workspace_playable_missions,
    load_workspace_mission_state,
    load_workspace_playable_bundle,
    replay_service_ops_with_policy_delta,
    start_workspace_mission_run,
)

from ._api_models import (
    MissionActivateRequest,
    MissionBranchRequest,
    MissionStartRequest,
    ServiceOpsPolicyReplayRequest,
)


def register_playable_routes(app: FastAPI, root: Path) -> None:
    @app.get("/api/playable")
    def api_playable() -> JSONResponse:
        payload = load_workspace_playable_bundle(root)
        return JSONResponse(payload or {})

    @app.get("/api/missions")
    def api_missions() -> JSONResponse:
        return JSONResponse(
            [
                item.model_dump(mode="json")
                for item in list_workspace_playable_missions(root)
            ]
        )

    @app.post("/api/missions/activate")
    def api_activate_mission(request: MissionActivateRequest) -> JSONResponse:
        try:
            payload = activate_workspace_playable_mission(
                root,
                request.mission_name,
                objective_variant=request.objective_variant,
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(payload)

    @app.get("/api/missions/state")
    def api_mission_state(run_id: str | None = None) -> JSONResponse:
        if run_id is None:
            bundle = load_workspace_playable_bundle(root)
            if bundle is not None and not bundle.get("run_id"):
                return JSONResponse({})
        payload = load_workspace_mission_state(root, run_id)
        return JSONResponse(payload.model_dump(mode="json") if payload else {})

    @app.post("/api/missions/start")
    def api_start_mission(request: MissionStartRequest) -> JSONResponse:
        try:
            mission_name = request.mission_name
            if mission_name is None:
                missions = list_workspace_playable_missions(root)
                if not missions:
                    raise ValueError("playable missions require a vertical workspace")
                mission_name = missions[0].mission_name
            payload = start_workspace_mission_run(
                root,
                mission_name=mission_name,
                objective_variant=request.objective_variant,
                run_id=request.run_id,
                seed=request.seed,
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(payload.model_dump(mode="json"))

    @app.post("/api/missions/{run_id}/moves/{move_id}")
    def api_apply_mission_move(run_id: str, move_id: str) -> JSONResponse:
        try:
            payload = apply_workspace_mission_move(root, run_id=run_id, move_id=move_id)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(payload.model_dump(mode="json"))

    @app.post("/api/missions/{run_id}/branch")
    def api_branch_mission_run(
        run_id: str,
        request: MissionBranchRequest,
    ) -> JSONResponse:
        try:
            payload = branch_workspace_mission_run(
                root,
                run_id=run_id,
                branch_name=request.branch_name,
                snapshot_id=request.snapshot_id,
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(payload.model_dump(mode="json"))

    @app.get("/api/runs/{run_id}/policy-knobs")
    def api_service_ops_policy_knobs(run_id: str) -> JSONResponse:
        try:
            payload = get_service_ops_policy_bundle(root, run_id=run_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(payload.model_dump(mode="json"))

    @app.post("/api/runs/{run_id}/replay-with-policy")
    def api_service_ops_policy_replay(
        run_id: str,
        request: ServiceOpsPolicyReplayRequest,
    ) -> JSONResponse:
        try:
            payload = replay_service_ops_with_policy_delta(
                root,
                run_id=run_id,
                policy_delta=request.policy_delta,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(payload.model_dump(mode="json"))

    @app.post("/api/missions/{run_id}/finish")
    def api_finish_mission_run(run_id: str) -> JSONResponse:
        try:
            payload = finish_workspace_mission_run(root, run_id=run_id)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(payload.model_dump(mode="json"))

    @app.get("/api/missions/{run_id}/exports")
    def api_mission_exports(run_id: str) -> JSONResponse:
        state = load_workspace_mission_state(root, run_id)
        if state is None:
            raise HTTPException(status_code=404, detail="mission run not found")
        payload = [
            item.model_dump(mode="json")
            for item in build_mission_run_exports(root, state)
        ]
        return JSONResponse(payload)

    @app.get("/api/missions/{run_id}/exports/{export_name}")
    def api_mission_export(run_id: str, export_name: str) -> JSONResponse:
        try:
            payload = export_mission_run(root, run_id=run_id, export_format=export_name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(payload)
