# Changelog

## 0.2.0a1 - 2026-02-06

Mini-alpha stabilization for external embedding.

- Added SDK runtime hooks via `SessionHook` and `EnterpriseSession.register_hook`.
- Added typed scenario manifest APIs (`list_scenario_manifest`, `get_scenario_manifest`).
- Added CLI manifest output in `vei-scenarios manifest`.
- Added external-consumer example: `examples/sdk_playground_min.py`.
- Added git dependency smoke script for CI: `tools/git_dependency_smoke.sh`.
- Added SDK compatibility contract docs: `docs/SDK_ALPHA_CONTRACT.md`.
- Added contributor guidance for `bd` repo-id mismatch: `CONTRIBUTING.md`.
