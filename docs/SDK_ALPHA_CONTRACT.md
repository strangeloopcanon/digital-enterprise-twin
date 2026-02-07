# VEI SDK Mini-Alpha Contract (`0.2.0a1`)

This document defines what downstream projects can rely on for the mini-alpha line.

## Scope

Stable-for-alpha surface (import from `vei.sdk`):

- `create_session`
- `EnterpriseSession`
- `SessionConfig`
- `SessionHook`
- `compile_workflow_spec`
- `validate_workflow_spec`
- `run_workflow_spec`
- `generate_enterprise_corpus`
- `filter_enterprise_corpus`
- `list_scenario_manifest`
- `get_scenario_manifest`

Anything outside `vei.sdk` is internal and may change without notice.

## Compatibility Promise

For all `0.2.0a*` releases:

1. Existing symbols listed above will not be renamed or removed.
2. Existing method signatures on `EnterpriseSession` will remain backward-compatible.
3. Existing manifest fields will not be removed (new optional fields may be added).
4. Existing scenario names in the built-in catalog will remain available.

If a breaking change is unavoidable, it will be documented in this file and the README before release.

## What Is Not Stable Yet

- Internal modules under `vei.router.*`, `vei.world.*`, `vei.scenario_*`, and CLI implementation details.
- Prompt text and evaluation scoring heuristics.
- Artifact file internals beyond documented filenames (`trace.jsonl`, `transcript.json`, `score.json`).

## Runtime Expectations

- Python 3.11+
- Default embedding mode is deterministic `sim`
- Git dependency install is validated in CI via `tools/git_dependency_smoke.sh`

## Suggested Upgrade Path for Consumers

1. Pin to an exact tag/commit in `requirements.txt` or `pyproject.toml`.
2. Integrate through `vei.sdk` only.
3. Run a small smoke scenario (`browser.read` + one write tool) in your own CI.
