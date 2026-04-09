from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from .demo import (
    VerticalCompareRunner,
    VerticalDemoSpec,
    VerticalStoryBundle,
    prepare_vertical_story,
)


class BusinessWorldDemoCommand(BaseModel):
    label: str
    command: str


class BusinessWorldDemoSection(BaseModel):
    section_id: str
    title: str
    duration_seconds: int = 0
    summary: str = ""
    talk_track: list[str] = Field(default_factory=list)
    commands: list[BusinessWorldDemoCommand] = Field(default_factory=list)
    evidence_paths: list[Path] = Field(default_factory=list)


class BusinessWorldStorySummary(BaseModel):
    vertical_name: str
    company_name: str
    workspace_root: Path
    scenario_variant: str
    contract_variant: str
    workflow_run_id: str
    comparison_run_id: str
    story_manifest_path: Path
    story_overview_path: Path
    exports_preview_path: Path
    presentation_guide_path: Path | None = None
    ui_command: str
    workflow_contract_ok: bool | None = None
    comparison_contract_ok: bool | None = None


class BusinessWorldDemoSpec(BaseModel):
    root: Path
    run_id: str = "business_world_demo"
    live_world_name: str = "service_ops"
    scenario_variant: str = "service_day_collision"
    contract_variant: str = "protect_sla"
    compare_runner: VerticalCompareRunner = "scripted"
    overwrite: bool = True
    seed: int = 42042
    max_steps: int = 18
    compare_model: str | None = None
    compare_provider: str | None = None
    compare_bc_model_path: Path | None = None


class BusinessWorldDemoBundle(BaseModel):
    run_id: str
    root: Path
    manifest_path: Path
    guide_path: Path
    live_world_name: str
    story: BusinessWorldStorySummary
    sections: list[BusinessWorldDemoSection] = Field(default_factory=list)
    kernel_thesis: str = ""


def prepare_business_world_demo(
    spec: BusinessWorldDemoSpec,
) -> BusinessWorldDemoBundle:
    bundle_root = spec.root.expanduser().resolve() / spec.run_id
    bundle_root.mkdir(parents=True, exist_ok=True)

    story_bundle = prepare_vertical_story(
        VerticalDemoSpec(
            vertical_name=spec.live_world_name,
            workspace_root=bundle_root / f"{spec.live_world_name}_story",
            scenario_variant=spec.scenario_variant,
            contract_variant=spec.contract_variant,
            compare_runner=spec.compare_runner,
            overwrite=spec.overwrite,
            seed=spec.seed,
            max_steps=spec.max_steps,
            compare_model=spec.compare_model,
            compare_provider=spec.compare_provider,
            compare_bc_model_path=spec.compare_bc_model_path,
        )
    )
    story_summary = _story_summary_from_bundle(story_bundle)

    bundle = BusinessWorldDemoBundle(
        run_id=spec.run_id,
        root=bundle_root,
        manifest_path=bundle_root / "business_world_demo_manifest.json",
        guide_path=bundle_root / "business_world_demo_guide.md",
        live_world_name=spec.live_world_name,
        story=story_summary,
        sections=_build_demo_sections(story_bundle, story_summary),
        kernel_thesis=story_bundle.kernel_thesis,
    )
    bundle.manifest_path.write_text(
        json.dumps(bundle.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    bundle.guide_path.write_text(
        render_business_world_demo_guide(bundle),
        encoding="utf-8",
    )
    return bundle


def load_business_world_demo_bundle(root: str | Path) -> BusinessWorldDemoBundle:
    resolved = Path(root).expanduser().resolve()
    manifest_path = (
        resolved
        if resolved.name == "business_world_demo_manifest.json"
        else resolved / "business_world_demo_manifest.json"
    )
    return BusinessWorldDemoBundle.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )


def render_business_world_demo_guide(bundle: BusinessWorldDemoBundle) -> str:
    lines = [
        "# VEI Business World Demo",
        "",
        "This guide is generated from the existing showcase system.",
        "",
        f"- Bundle root: `{bundle.root}`",
        f"- Manifest: `{bundle.manifest_path}`",
        f"- Story workspace: `{bundle.story.workspace_root}`",
        f"- Story overview: `{bundle.story.story_overview_path}`",
        f"- Story manifest: `{bundle.story.story_manifest_path}`",
        f"- Story exports preview: `{bundle.story.exports_preview_path}`",
    ]
    if bundle.story.presentation_guide_path is not None:
        lines.append(
            f"- Story presentation guide: `{bundle.story.presentation_guide_path}`"
        )
    lines.extend(
        [
            "",
            "## Kernel Thesis",
            "",
            bundle.kernel_thesis,
            "",
        ]
    )
    for section in bundle.sections:
        lines.extend(
            [
                f"## {section.title}",
                "",
                section.summary,
                "",
                f"- Suggested time: `{section.duration_seconds}` seconds",
            ]
        )
        if section.commands:
            lines.extend(["", "Commands:"])
            for command in section.commands:
                lines.append(f"- {command.label}: `{command.command}`")
        if section.talk_track:
            lines.extend(["", "Talk track:"])
            for item in section.talk_track:
                lines.append(f"- {item}")
        if section.evidence_paths:
            lines.extend(["", "Evidence:"])
            for path in section.evidence_paths:
                lines.append(f"- `{path}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _story_summary_from_bundle(story: VerticalStoryBundle) -> BusinessWorldStorySummary:
    return BusinessWorldStorySummary(
        vertical_name=story.manifest.name,
        company_name=story.manifest.company_name,
        workspace_root=story.workspace_root,
        scenario_variant=story.scenario_variant,
        contract_variant=story.contract_variant,
        workflow_run_id=story.workflow_run_id,
        comparison_run_id=story.comparison_run_id,
        story_manifest_path=story.story_manifest_path,
        story_overview_path=story.overview_path,
        exports_preview_path=story.exports_preview_path,
        presentation_guide_path=story.presentation_guide_path,
        ui_command=story.ui_command,
        workflow_contract_ok=story.workflow_contract_ok,
        comparison_contract_ok=story.comparison_contract_ok,
    )


def _build_demo_sections(
    story: VerticalStoryBundle,
    story_summary: BusinessWorldStorySummary,
) -> list[BusinessWorldDemoSection]:
    live_world_section = BusinessWorldDemoSection(
        section_id="live_world",
        title="Live Business World",
        duration_seconds=180,
        summary=(
            "Lead with the live service operations world. Keep the generated story workspace as the typed backup artifact for the same company world."
        ),
        talk_track=[
            "This is a world model of a business in the practical sense. One company world holds people, systems, agents, rules, and consequences in the same runtime.",
            "Stay on the Company view long enough to show dispatch, billing, approvals, and operator state moving together.",
            "Use the generated story workspace if you want a static backup that still lives inside the same showcase system.",
        ],
        commands=[
            BusinessWorldDemoCommand(
                label="Start the live world",
                command="python -m vei.cli.vei quickstart run --world service_ops --governor-demo",
            ),
            BusinessWorldDemoCommand(
                label="Open the generated story workspace",
                command=story_summary.ui_command,
            ),
        ],
        evidence_paths=[
            story_summary.story_overview_path,
            story_summary.story_manifest_path,
        ],
    )

    exports_summaries = [item.summary for item in story.exports_preview]
    eval_section = BusinessWorldDemoSection(
        section_id="evals",
        title="Eval System",
        duration_seconds=90,
        summary=(
            "Use the same world and run spine to explain evaluation at the business level instead of the single-task level."
        ),
        talk_track=[
            "Once you have a stable business world, evals stop being toy tasks. You can evaluate behavior against the business.",
            "Use three buckets: task completion, policy and risk, and business outcome.",
            *exports_summaries,
        ],
        commands=[
            BusinessWorldDemoCommand(
                label="Open the story workspace in Studio",
                command=story_summary.ui_command,
            )
        ],
        evidence_paths=[
            story_summary.exports_preview_path,
            story_summary.story_manifest_path,
        ]
        + (
            [story_summary.presentation_guide_path]
            if story_summary.presentation_guide_path is not None
            else []
        ),
    )
    return [live_world_section, eval_section]


__all__ = [
    "BusinessWorldDemoBundle",
    "BusinessWorldDemoCommand",
    "BusinessWorldDemoSection",
    "BusinessWorldDemoSpec",
    "BusinessWorldStorySummary",
    "load_business_world_demo_bundle",
    "prepare_business_world_demo",
    "render_business_world_demo_guide",
]
