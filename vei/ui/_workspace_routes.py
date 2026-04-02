from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from vei.verticals import (
    load_workspace_exports_preview,
    load_workspace_presentation,
    load_workspace_story_manifest,
)
from vei.workspace.api import show_workspace

from ._api_models import (
    ExerciseActivateRequest,
    MirrorAgentUpdateRequest,
    MirrorApprovalResolveRequest,
    gateway_json_request,
    load_workspace_mirror_payload,
)


def register_workspace_routes(app: FastAPI, root: Path, *, deps: Any) -> None:
    @app.get("/api/workspace")
    def api_workspace() -> JSONResponse:
        return JSONResponse(show_workspace(root).model_dump(mode="json"))

    @app.get("/api/workspace/mirror")
    def api_workspace_mirror() -> JSONResponse:
        return JSONResponse(load_workspace_mirror_payload(root))

    @app.post("/api/workspace/mirror/agents")
    def api_workspace_mirror_register_agent(
        request: MirrorAgentUpdateRequest,
    ) -> JSONResponse:
        payload = gateway_json_request(
            root,
            path="/api/mirror/agents",
            method="POST",
            payload=request.model_dump(exclude_none=True),
        )
        return JSONResponse(payload, status_code=201)

    @app.patch("/api/workspace/mirror/agents/{agent_id}")
    def api_workspace_mirror_update_agent(
        agent_id: str,
        request: MirrorAgentUpdateRequest,
    ) -> JSONResponse:
        payload = gateway_json_request(
            root,
            path=f"/api/mirror/agents/{agent_id}",
            method="PATCH",
            payload=request.model_dump(exclude_none=True),
        )
        return JSONResponse(payload)

    @app.delete("/api/workspace/mirror/agents/{agent_id}")
    def api_workspace_mirror_remove_agent(agent_id: str) -> JSONResponse:
        payload = gateway_json_request(
            root,
            path=f"/api/mirror/agents/{agent_id}",
            method="DELETE",
        )
        return JSONResponse(payload)

    @app.get("/api/workspace/mirror/approvals")
    def api_workspace_mirror_approvals() -> JSONResponse:
        payload = gateway_json_request(root, path="/api/mirror/approvals")
        return JSONResponse(payload)

    @app.post("/api/workspace/mirror/approvals/{approval_id}/approve")
    def api_workspace_mirror_approve(
        approval_id: str,
        request: MirrorApprovalResolveRequest,
    ) -> JSONResponse:
        payload = gateway_json_request(
            root,
            path=f"/api/mirror/approvals/{approval_id}/approve",
            method="POST",
            payload=request.model_dump(),
        )
        return JSONResponse(payload)

    @app.post("/api/workspace/mirror/approvals/{approval_id}/reject")
    def api_workspace_mirror_reject(
        approval_id: str,
        request: MirrorApprovalResolveRequest,
    ) -> JSONResponse:
        payload = gateway_json_request(
            root,
            path=f"/api/mirror/approvals/{approval_id}/reject",
            method="POST",
            payload=request.model_dump(),
        )
        return JSONResponse(payload)

    @app.get("/api/story")
    def api_story() -> JSONResponse:
        payload = load_workspace_story_manifest(root)
        return JSONResponse(payload.model_dump(mode="json") if payload else {})

    @app.get("/api/exports-preview")
    def api_exports_preview() -> JSONResponse:
        return JSONResponse(
            [
                item.model_dump(mode="json")
                for item in load_workspace_exports_preview(root)
            ]
        )

    @app.get("/api/presentation")
    def api_presentation() -> JSONResponse:
        payload = load_workspace_presentation(root)
        return JSONResponse(payload.model_dump(mode="json") if payload else {})

    @app.get("/api/pilot")
    def api_pilot() -> JSONResponse:
        try:
            payload = deps.build_pilot_status(root)
        except FileNotFoundError:
            return JSONResponse({})
        return JSONResponse(payload.model_dump(mode="json"))

    @app.get("/api/exercise")
    def api_exercise() -> JSONResponse:
        try:
            payload = deps.build_exercise_status(root)
        except FileNotFoundError:
            return JSONResponse({})
        return JSONResponse(payload.model_dump(mode="json"))

    @app.post("/api/exercise/activate")
    def api_exercise_activate(request: ExerciseActivateRequest) -> JSONResponse:
        try:
            payload = deps.activate_exercise(
                root,
                scenario_variant=request.scenario_variant,
                contract_variant=request.contract_variant,
            )
        except (FileNotFoundError, KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(payload.model_dump(mode="json"))

    @app.get("/api/dataset")
    def api_dataset() -> JSONResponse:
        payload = deps.load_workspace_dataset_bundle(root)
        if payload is None:
            return JSONResponse({})
        return JSONResponse(payload.model_dump(mode="json"))

    @app.post("/api/pilot/finalize")
    def api_pilot_finalize() -> JSONResponse:
        try:
            payload = deps.finalize_pilot_run(root)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="pilot stack is not configured")
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(payload.model_dump(mode="json"))

    @app.post("/api/pilot/reset")
    def api_pilot_reset() -> JSONResponse:
        try:
            payload = deps.reset_pilot_gateway(root)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="pilot stack is not configured")
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(payload.model_dump(mode="json"))

    @app.get("/api/fidelity")
    def api_fidelity() -> JSONResponse:
        try:
            payload = deps.get_or_build_workspace_fidelity_report(root)
        except ValueError:
            return JSONResponse({})
        return JSONResponse(payload.model_dump(mode="json"))
