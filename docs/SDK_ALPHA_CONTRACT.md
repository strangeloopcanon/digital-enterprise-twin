# VEI SDK Mini-Alpha Contract (`0.2.0a1`)

This document defines what downstream projects can rely on for the mini-alpha line.

## Scope

Stable-for-alpha surface (import from `vei.sdk`):

- `create_session`
- `EnterpriseSession`
- `SessionConfig`
- `SessionHook`
- `EnterpriseSession.world`
- `compile_workflow_spec`
- `validate_workflow_spec`
- `run_workflow_spec`
- `generate_enterprise_corpus`
- `filter_enterprise_corpus`
- `list_scenario_manifest`
- `get_scenario_manifest`
- `list_benchmark_family_manifest_entries`
- `get_benchmark_family_manifest_entry`
- `build_release_version`
- `export_release_dataset`
- `export_release_benchmark`
- `run_release_nightly`

Anything outside `vei.sdk` is internal and may change without notice.

## Compatibility Promise

For all `0.2.0a*` releases:

1. Existing symbols listed above will not be renamed or removed.
2. Existing method signatures on `EnterpriseSession` will remain backward-compatible.
3. Existing methods on `EnterpriseSession.world` (`observe`, `call_tool`, `snapshot`, `restore`, `branch`, `replay`, `inject`, `list_events`, `cancel_event`) will remain backward-compatible for the alpha line.
4. Existing manifest fields will not be removed (new optional fields may be added).
5. Existing scenario names and benchmark family names in the built-in catalog will remain available.

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
