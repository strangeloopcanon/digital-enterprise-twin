## Digital Enterprise Twin (VEI)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/strangeloopcanon/digital-enterprise-twin)

![VEI Virtual Office](docs/assets/virtual_office.gif)
<p align="center"><sub>Conceptual office view</sub></p>

Digital Enterprise Twin is a deterministic, MCP-native virtual enterprise. It emulates enterprise software surfaces (Slack, Mail, Browser, Docs, Tickets, DB, ERP/CRM aliases, Okta-style identity, ServiceDesk) so agents can run realistic office workflows without touching live SaaS.

## Quick Start

### 1. Install
```bash
pip install -e ".[llm,sse]"
```

### 2. Configure `.env`
```env
OPENAI_API_KEY=sk-your-key
VEI_SEED=42042
VEI_ARTIFACTS_DIR=./_vei_out
```

### 3. Verify and smoke
```bash
python test_vei_setup.py
vei-smoke --transport stdio --timeout-s 30
```

### 4. Run a live LLM episode
```bash
vei-llm-test --model gpt-5 \
  --task "Research price, get Slack approval under budget, and email vendor for quote."
```

## What You Get

- Deterministic simulator and replayable traces
- Realistic multi-tool workflows (procurement, compliance, identity/access, incident ops)
- Typed SDK for embedding in other Python projects
- Scenario DSL + corpus generation/filtering pipeline
- CLI and CI gates for quality and live checks

## Architecture
```text
Agent ──MCP──► VEI Router
                  ├─ slack.* / mail.* / browser.* / docs.* / tickets.* / db.*
                  ├─ okta.* (identity twin)
                  ├─ servicedesk.* (incident/request twin)
                  └─ vei.* (observe/state/control)
                           ▲
                     Seeded Event Bus
```

## Use It As A Library (Git Dependency)

Install directly from GitHub:
```bash
pip install "git+https://github.com/strangeloopcanon/digital-enterprise-twin.git@main"
```

Minimal embedding:
```python
from vei.sdk import create_session

session = create_session(seed=42042, scenario_name="multi_channel", connector_mode="sim")
obs = session.observe()
page = session.call_tool("browser.read", {})
```

Hookable embedding (before/after tool calls):
```python
from vei.sdk import SessionHook, create_session

class TraceHook(SessionHook):
    def before_call(self, tool: str, args: dict) -> None:
        print("before", tool, args)

    def after_call(self, tool: str, args: dict, result: dict) -> None:
        print("after", tool, sorted(result.keys()))

session = create_session(seed=42042, scenario_name="multi_channel")
session.register_hook(TraceHook())
session.call_tool("browser.read", {})
```

Scenario manifest helpers:
- `list_scenario_manifest()`
- `get_scenario_manifest(name)`

Reference docs and examples:
- `examples/sdk_playground_min.py`
- `docs/SDK_ALPHA_CONTRACT.md`
- `docs/det_phases_0_6_architecture.md`

## Primary Commands

```bash
make setup        # bootstrap env + tooling
make check        # format/lint/types/security checks
make test         # pytest suite
make llm-live     # strict full-flow live check (needs OPENAI_API_KEY)
make deps-audit   # pip-audit
make all          # check -> test -> llm-live -> deps-audit
```

If you run without LLM credentials:
```bash
VEI_LLM_LIVE_BYPASS=1 make llm-live
```

## Core CLI Surface

- Runtime: `vei-chat`, `vei-llm-test`, `vei-smoke`, `vei-demo`, `vei-state`
- Scenarios: `vei-scenarios list`, `vei-scenarios manifest`, `vei-scenarios dump`
- DSL/corpus: `vei-det sample-workflow|compile-workflow|run-workflow|generate-corpus|filter-corpus`
- Policy/eval: `vei-rollout`, `vei-train`, `vei-eval`, `vei-score`
- Visualization: `vei-visualize replay|flow|dashboard|export`

## Built-in Software Twins

- Collaboration: Slack, Mail
- Knowledge/Docs: Browser, Docs
- Operations: Tickets, ServiceDesk (incidents/requests)
- Identity: Okta-style users/groups/apps
- Data systems: DB + ERP/CRM twins (with alias packs)

## Contributor Notes

If `bd` shows a repo-id mismatch after path/remote changes:
```bash
bd --no-daemon migrate --update-repo-id
bd --no-daemon sync --flush-only
bd daemon restart
```

---

<details>
<summary><strong>Advanced: Evaluation and Benchmarking</strong></summary>

### Baseline Task
```bash
export VEI_ARTIFACTS_DIR=_vei_out/gpt5_llmtest
VEI_SEED=42042 vei-llm-test --model gpt-5 --max-steps 32 \
  --task "Open product page, cite specs, post approval under $3200, email sales@macrocompute.example for a quote, wait for reply."
vei-score --artifacts-dir _vei_out/gpt5_llmtest --success-mode full
```

### Historical Multi-Provider Snapshot (Oct 2025)
This table is intentionally pinned historical context, not live status.

| Model | Success | Actions | Subgoals (cit/appr/appr_amt/email_sent/email_parsed/doc/ticket/crm) | Policy (warn/err) |
| --- | --- | ---: | --- | --- |
| openai/gpt-5 | ✗ | 39 | 1/1/0/1/0/0/0/0 | 2/0 |
| openai/gpt-5-codex | ✗ | 37 | 1/1/1/1/0/0/0/0 | 2/0 |
| anthropic/claude-sonnet-4-5 | ✗ | 26 | 1/1/0/0/0/0/0/1 | 5/0 |
| openrouter/x-ai/grok-4 | ✗ | 10 | 1/1/0/1/0/0/0/0 | 2/0 |
| google/models/gemini-2.5-pro | ✗ | 4 | 1/1/0/1/0/0/0/0 | 2/0 |

Regenerate fresh benchmark data:
```bash
./run_multi_provider_eval.sh
python tools/render_multi_provider_dashboard.py --latest-only _vei_out/gpt5_llmtest
```

### Frontier suites
```bash
VEI_MODELS='gpt-5:openai,claude-sonnet-4-5:anthropic' \
VEI_SCENARIOS='multi_channel,multi_channel_compliance' ./run_multi_provider_eval.sh
```

</details>

<details>
<summary><strong>Advanced: DET Workflow DSL and Corpus Pipeline</strong></summary>

```bash
# Create + run sample workflow
vei-det sample-workflow --output ./_vei_out/workflow_sample.json
vei-det compile-workflow --spec ./_vei_out/workflow_sample.json --output ./_vei_out/workflow_compiled.json
vei-det run-workflow --spec ./_vei_out/workflow_sample.json --connector-mode sim --artifacts ./_vei_out/workflow_run

# Generate + filter larger corpora
vei-det generate-corpus --seed 42042 --environments 50 --scenarios-per-environment 30 --output ./_vei_out/corpus/generated.json
vei-det filter-corpus --corpus ./_vei_out/corpus/generated.json --output ./_vei_out/corpus/filter_report.json
```

</details>

<details>
<summary><strong>Advanced: Dataset, RL, and Policy Evaluation</strong></summary>

```bash
vei-rollout procurement --episodes 5 --seed 42042 --output ./_vei_out/rollout.json
vei-train bc --dataset ./_vei_out/rollout.json --output ./_vei_out/bc_policy.json
vei-eval scripted --seed 42042 --artifacts ./_vei_out/eval_scripted
vei-eval bc --model ./_vei_out/bc_policy.json --seed 42042 --artifacts ./_vei_out/eval_bc
```

To benchmark LLMs on same rollout context:
```bash
vei-llm-test --model gpt-5 --dataset ./_vei_out/rollout.json --task "Research vendor quote" --artifacts ./_vei_out/llm_eval
```

</details>

<details>
<summary><strong>Advanced: Visualizations</strong></summary>

```bash
vei-visualize replay _vei_out/<run_id>/transcript.json
vei-visualize flow _vei_out/<run_id>/transcript.json --out _vei_out/<run_id>/flow.html
vei-visualize dashboard _vei_out/gpt5_llmtest/<run_dir>/multi_channel --step-ms 400 --out _vei_out/<run_dir>/flow_dashboard.html
vei-visualize export _vei_out/<run_id>/transcript.json docs/assets/<name>.gif --step-ms 400 --stride 2
```

| openai/gpt-5 | anthropic/claude-sonnet-4-5 |
| --- | --- |
| ![openai/gpt-5 multi-channel flow](docs/assets/gpt5_flow.gif) | ![claude-sonnet-4-5 multi-channel flow](docs/assets/claude_flow.gif) |

</details>

<details>
<summary><strong>Name History</strong></summary>

This project was originally called **Pliny the Elder**. The repository was renamed to **Digital Enterprise Twin** for clarity, while retaining **VEI** as the runtime/package identity.

</details>
