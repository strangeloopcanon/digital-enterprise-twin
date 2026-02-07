# Digital Enterprise Twin: Phases 0-6 Architecture

This document captures the modular architecture delivered for phases 0-6:

- Phase 0: typed module contracts and architecture boundaries
- Phase 1-2: connector SDK + sim/replay/live adapters
- Phase 3: runnable workflow DSL v2
- Phase 4: deterministic runner + validators
- Phase 5: seeded corpus generator
- Phase 6: quality filtering (dedupe + realism + runnability)

## Module Boundaries

All cross-module usage is via each module's `api.py`.

- `vei/connectors/api.py`
  - Adapter contracts (`ConnectorAdapter`, `PolicyGate`)
  - Tool routing map
  - Runtime factory for sim/replay/live execution
- `vei/scenario_engine/api.py`
  - Workflow DSL v2 loaders and compiler
- `vei/scenario_runner/api.py`
  - Static validation + deterministic workflow execution
- `vei/corpus/api.py`
  - Seeded large-scale workflow/environment generation
- `vei/quality/api.py`
  - Corpus filtering and scoring

## Connector SDK

Connector runtime introduces a typed envelope:

- request: service, operation, operation class (`read`, `write_safe`, `write_risky`)
- policy decision: allow, deny, require approval
- result: legacy-compatible data + canonical raw payload
- receipt: redacted request/response persisted as JSONL

Execution modes:

- `sim`: deterministic local simulators
- `replay`: deterministic memoized replays
- `live`: policy-gated path (currently simulated backend with live semantics)

Default connector coverage now includes:

- Slack (`slack.*`)
- Mail (`mail.*`)
- Docs (`docs.*`)
- Calendar (`calendar.*`)
- Tickets (`tickets.*`)
- Database (`db.*`)

CRM/ERP remain native twins and are reachable both directly (`crm.*`, `erp.*`) and through alias packs (for example Salesforce and HubSpot aliases mapping to CRM).

Configure via:

- `VEI_CONNECTOR_MODE=sim|replay|live`
- `VEI_LIVE_ALLOW_WRITE_SAFE=1` to permit safe writes in live mode
- `VEI_LIVE_ALLOW_WRITE_RISKY=1` to permit risky writes in live mode
- `VEI_LIVE_BLOCK_OPS=service.operation,...` to hard-block operations

## DSL v2

Workflow DSL v2 includes:

- objective and success criteria
- actors, constraints, approvals
- deterministic step graph with per-step expectations
- failure-path declarations for recovery jumps

Compiler output:

- existing `Scenario` world state (compatible with current router)
- indexed, executable workflow steps

## Runner + Validators

Static validation:

- tool availability
- failure-path integrity
- approval intent sanity checks

Dynamic validation:

- deterministic step execution against router
- assertion checks on result/observation/pending queues
- controlled failure handling (`fail`, `continue`, `jump:<step_id>`)

## Corpus + Quality Pipeline

Generation (`vei-det generate-corpus`):

- deterministic enterprise environments from seed
- deterministic runnable workflow specs per environment
- mixed workflow families that exercise Slack, mail, docs, calendar, tickets, DB, and CRM aliases (Salesforce-style by default)

Filtering (`vei-det filter-corpus`):

- structural dedupe (hash fingerprint)
- realism heuristics
- static runnability checks
- novelty pressure by structure frequency

## CLI Entry Point

Use `vei-det`:

- `sample-workflow` to create a DSL v2 starter file
- `compile-workflow` to compile DSL into runtime scenario/plan
- `run-workflow` to execute and validate deterministic runs
- `generate-corpus` for large-scale scenario generation
- `filter-corpus` for dedupe + realism + runnability filtering

## External Embedding (SDK)

For third-party embedding, use the stable SDK facade:

- `vei.sdk.create_session` / `vei.sdk.EnterpriseSession`
- `vei.sdk.compile_workflow_spec`, `vei.sdk.validate_workflow_spec`, `vei.sdk.run_workflow_spec`
- `vei.sdk.generate_enterprise_corpus`, `vei.sdk.filter_enterprise_corpus`

The session API exposes deterministic tool execution and allows custom provider
registration through `register_tool_provider(...)`.
