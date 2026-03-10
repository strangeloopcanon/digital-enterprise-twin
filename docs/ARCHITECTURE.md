# VEI Architecture

VEI is a deterministic, MCP-native enterprise simulator built around one stable boundary: `WorldSession`.

## Runtime Shape

```text
Agent / SDK / CLI
        │
        ▼
  Router transport layer
        │
        ▼
   WorldSession kernel
        ├─ world state
        ├─ event queue
        ├─ actor state
        ├─ receipts
        ├─ snapshots / branch / restore
        └─ replay / injection
```

The router is a transport and tool-dispatch adapter. Mutable enterprise state belongs to the kernel, not to transport wrappers.

## Stable Python Surfaces

- `vei.world.api`
  - `create_world_session`
  - `observe`
  - `call_tool`
  - `snapshot`
  - `restore`
  - `branch`
  - `replay`
  - `inject`
  - `list_events`
  - `cancel_event`
- `vei.sdk`
  - `create_session`
  - scenario/benchmark manifest helpers
  - release/export helpers
  - workflow compile/run helpers

## Supported Entry Points

- `python -m vei.router`
  - stdio MCP transport
- `python -m vei.router.sse`
  - SSE MCP transport
- `vei-world`
  - snapshot/receipt inspection
- `vei-llm-test`, `vei-eval`, `vei-eval-frontier`, `vei-report`
  - evaluation and benchmarking

## Software Twins

- Collaboration: Slack, Mail
- Knowledge: Browser, Docs
- Operations: Tickets, ServiceDesk
- Identity and control plane: Okta-style identity, Google Admin, SIEM, Datadog, PagerDuty, feature flags
- Business systems: ERP, CRM, HRIS, Jira-style issues

## Design Rules

- New mutable state belongs under `vei.world`.
- Cross-module usage should go through typed `api.py` surfaces.
- All actor outputs should enter the world through typed events so snapshot/replay stays deterministic.
