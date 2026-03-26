from __future__ import annotations

from pathlib import Path

from vei.context.models import ContextSnapshot
from vei.dataset import api as dataset_api
from vei.dataset.models import DatasetBuildSpec
from vei.workspace.api import create_workspace_from_template


def test_build_dataset_bundle_from_workspace_root_writes_exports(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    output_root = tmp_path / "dataset"
    create_workspace_from_template(
        root=workspace_root,
        source_kind="vertical",
        source_ref="real_estate_management",
    )

    bundle = dataset_api.build_dataset_bundle(
        DatasetBuildSpec(
            output_root=output_root,
            workspace_roots=[workspace_root],
            include_external_sample=False,
            formats=["conversations", "demonstrations"],
        )
    )

    assert bundle.environment_count == 1
    assert bundle.run_count == 2
    assert bundle.exports
    assert (output_root / dataset_api.DATASET_BUNDLE_FILE).exists()
    assert (workspace_root / dataset_api.WORKSPACE_DATASET_FILE).exists()
    loaded = dataset_api.load_workspace_dataset_bundle(workspace_root)
    assert loaded is not None
    assert loaded.run_count == 2


def test_build_dataset_bundle_can_generate_matrix_from_snapshot(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "matrix_dataset"
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(
        _sample_snapshot().model_dump_json(indent=2), encoding="utf-8"
    )

    bundle = dataset_api.build_dataset_bundle(
        DatasetBuildSpec(
            output_root=output_root,
            snapshot_path=str(snapshot_path),
            organization_name="Acme Cloud",
            organization_domain="acme.ai",
            archetypes=["b2b_saas"],
            density_levels=["small"],
            crisis_levels=["calm"],
            seeds=[42042],
            include_external_sample=False,
            formats=["conversations"],
        )
    )

    assert bundle.environment_count == 1
    assert bundle.run_count == 2
    assert bundle.matrix_path == "matrix/twin_matrix.json"
    assert (output_root / "matrix" / "twin_matrix.json").exists()


def _sample_snapshot() -> ContextSnapshot:
    return ContextSnapshot.model_validate_json(
        """
        {
          "version": "1",
          "organization_name": "Acme Cloud",
          "organization_domain": "acme.ai",
          "captured_at": "2026-03-24T16:00:00+00:00",
          "sources": [
            {
              "provider": "slack",
              "captured_at": "2026-03-24T16:00:00+00:00",
              "status": "ok",
              "record_counts": {"channels": 1, "messages": 2},
              "data": {
                "channels": [
                  {
                    "channel": "#revops-war-room",
                    "unread": 1,
                    "messages": [
                      {
                        "ts": "1710300000.000100",
                        "user": "maya.ops",
                        "text": "Renewal is exposed unless we land the onboarding fix today."
                      },
                      {
                        "ts": "1710300060.000200",
                        "user": "evan.sales",
                        "text": "Jordan wants one accountable owner and a customer-safe timeline."
                      }
                    ]
                  }
                ]
              }
            },
            {
              "provider": "jira",
              "captured_at": "2026-03-24T16:00:00+00:00",
              "status": "ok",
              "record_counts": {"issues": 1},
              "data": {
                "issues": [
                  {
                    "ticket_id": "ACME-101",
                    "title": "Renewal blocker: onboarding API still timing out",
                    "status": "open",
                    "assignee": "maya.ops",
                    "description": "Customer onboarding export is timing out on larger tenants."
                  }
                ]
              }
            },
            {
              "provider": "google",
              "captured_at": "2026-03-24T16:00:00+00:00",
              "status": "ok",
              "record_counts": {"documents": 1, "users": 1},
              "data": {
                "documents": [
                  {
                    "doc_id": "DOC-ACME-001",
                    "title": "Renewal Recovery Plan",
                    "body": "Stabilize the renewal and send a customer-safe update.",
                    "mime_type": "application/vnd.google-apps.document"
                  }
                ],
                "users": [
                  {
                    "id": "g-001",
                    "email": "maya@acme.ai",
                    "name": "Maya Ops",
                    "org_unit": "RevOps",
                    "suspended": false
                  }
                ]
              }
            }
          ]
        }
        """
    )
