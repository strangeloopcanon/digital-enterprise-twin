SHELL := /bin/bash
MODE ?= $(or $(AGENT_MODE),baseline)

.PHONY: setup bootstrap check test llm-live deps-audit all clean clean-workspace

setup bootstrap:
	uv sync --extra llm --extra sse --extra ui --extra test --extra rl --extra dev
	@if [ -f .pre-commit-config.yaml ]; then \
		uv run pre-commit install --install-hooks || \
			echo "Skipping pre-commit install; hooks are managed elsewhere."; \
	fi
	@echo "Environment ready."

check:
	uv run black --check vei tests
	uv run ruff check vei tests
	uv run mypy --follow-imports=skip vei/router/identity.py vei/router/tool_providers.py vei/identity vei/world/api.py vei/world/replay.py vei/router/api.py vei/workspace/api.py vei/run/api.py vei/twin vei/ui/api.py vei/context vei/synthesis vei/pilot vei/exercise vei/dataset vei/cli/vei.py vei/cli/vei_project.py vei/cli/vei_run.py vei/cli/vei_contract.py vei/cli/vei_scenario.py vei/cli/vei_inspect.py vei/cli/vei_ui.py vei/cli/vei_context.py vei/cli/vei_synthesize.py vei/cli/vei_pilot.py vei/cli/vei_exercise.py vei/cli/vei_dataset.py
	uv run bandit -q -r vei -ll
	@mkdir -p .artifacts
	uv run detect-secrets scan $$(git ls-files) > .artifacts/detect-secrets.json
	@echo "--- import boundary check (advisory) ---"
	uv run python scripts/check_import_boundaries.py || true
	@if [ -f .secrets.baseline ]; then \
		uv run detect-secrets-hook --baseline .secrets.baseline $$(git ls-files); \
	else \
		echo "No .secrets.baseline found; detect-secrets check is advisory-only."; \
	fi

test:
	uv run python -m pytest

llm-live:
	@if [ -f .env ]; then \
		set -a; . ./.env; set +a; \
	fi; \
	if [ -n "$$VEI_LLM_LIVE_BYPASS" ]; then \
		echo "VEI_LLM_LIVE_BYPASS=1 set; skipping llm-live checks."; \
	elif [ -z "$$OPENAI_API_KEY" ]; then \
		echo "OPENAI_API_KEY not set; cannot run llm-live target. Set the key or export VEI_LLM_LIVE_BYPASS=1 to skip in CI."; \
		exit 4; \
	else \
		ART="$${VEI_LLM_ARTIFACTS_DIR:-_vei_out/llm_live/latest}"; \
		mkdir -p "$$ART"; \
		rm -f "$$ART/trace.jsonl" "$$ART/score.json" "$$ART/transcript.json" "$$ART/llm_transcript.jsonl" "$$ART/connector_receipts.jsonl"; \
		uv run vei llm-test run --provider openai --model $${VEI_LLM_MODEL:-gpt-5} --max-steps $${VEI_LLM_MAX_STEPS:-18} --step-timeout-s $${VEI_LLM_STEP_TIMEOUT_S:-180} --episode-timeout-s $${VEI_LLM_EPISODE_TIMEOUT_S:-900} --score-success-mode $${VEI_LLM_SUCCESS_MODE:-full} --require-success --no-print-transcript --artifacts "$$ART" --task "$${VEI_LLM_TASK:-Run full procurement workflow: cite source, post Slack approval with budget amount, email vendor and parse price+ETA reply, log quote in Docs, update ticket, and log CRM activity.}" && \
			uv run python -c 'import json,sys;from pathlib import Path;art=Path(sys.argv[1]);score=json.loads((art/"score.json").read_text(encoding="utf-8"));trace=art/"trace.jsonl";records=[json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines() if line.strip()] if trace.exists() else [];times=[int(r.get("time_ms",0)) for r in records if r.get("type")=="call"];lat=[max(0,b-a) for a,b in zip(times,times[1:])];p95=sorted(lat)[int(0.95*(len(lat)-1))] if lat else 0;passed=1 if bool(score.get("success")) else 0;failed=0 if passed else 1;actions=int(score.get("costs",{}).get("actions",len(times)));print(f"llm-live metrics: pass={passed} fail={failed} cost_usd=unknown p95_latency_ms={p95} actions={actions}")' "$$ART"; \
	fi

deps-audit:
	@if [ "$(MODE)" = "production" ]; then \
		uv run pip-audit --skip-editable; \
	else \
		uv run pip-audit --skip-editable || true; \
	fi

all: check test llm-live deps-audit

clean-workspace:
	rm -rf .artifacts .coverage .coverage.* .mypy_cache .pytest_cache ".pytest_cache 2" .ruff_cache vei.egg-info
	find . -name '.DS_Store' -delete
	@mkdir -p _vei_out/demo _vei_out/llm_live _vei_out/datasets
	find _vei_out -mindepth 1 -maxdepth 1 ! -name demo ! -name llm_live ! -name datasets -exec rm -rf {} +
	find _vei_out/demo -mindepth 1 -maxdepth 1 ! -name security_blueprint_demo -exec rm -rf {} +
	find _vei_out/llm_live -mindepth 1 -maxdepth 1 ! -name latest -exec rm -rf {} +

clean:
	rm -rf .venv
