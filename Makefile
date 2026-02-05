SHELL := /bin/bash
PYTHON ?= python3.11
VENV ?= .venv
MODE ?= $(or $(AGENT_MODE),baseline)
SETUP_STAMP := $(VENV)/.setup-complete
VENV_BIN := $(VENV)/bin
DEPS := black==24.8.0 ruff==0.6.8 mypy==1.11.2 bandit==1.7.9 detect-secrets==1.5.0 pip-audit==2.7.3 pytest==9.0.2 pytest-timeout==2.4.0 pytest-cov==7.0.0 pre-commit==4.4.0

.PHONY: setup bootstrap check test llm-live deps-audit all clean

$(VENV)/bin/activate:
	$(PYTHON) -m venv $(VENV)

$(SETUP_STAMP): $(VENV)/bin/activate pyproject.toml
	. $(VENV)/bin/activate && \
		pip install --upgrade pip setuptools wheel && \
		pip install -e ".[llm,sse,test,rl]" && \
		pip install $(DEPS)
	@if [ -f .pre-commit-config.yaml ]; then \
		. $(VENV)/bin/activate && pre-commit install --install-hooks; \
	fi
	@touch $(SETUP_STAMP)

setup bootstrap: $(SETUP_STAMP)
	@echo "Virtual environment ready at $(VENV)"

check: $(SETUP_STAMP)
	. $(VENV)/bin/activate && black --check vei tests
	. $(VENV)/bin/activate && ruff check vei tests
	. $(VENV)/bin/activate && mypy --follow-imports=skip vei/router/identity.py vei/router/tool_providers.py vei/identity vei/world/api.py vei/world/replay.py vei/router/api.py
	. $(VENV)/bin/activate && bandit -q -r vei -ll
	@mkdir -p .artifacts
	. $(VENV)/bin/activate && detect-secrets scan --all-files --exclude-files '(\\.venv|_vei_out|\\.artifacts|vei\\.egg-info)' > .artifacts/detect-secrets.json
	@if [ -f .secrets.baseline ]; then \
		. $(VENV)/bin/activate && detect-secrets-hook --baseline .secrets.baseline $$(git ls-files); \
	else \
		echo "No .secrets.baseline found; detect-secrets check is advisory-only."; \
	fi

test: $(SETUP_STAMP)
	. $(VENV)/bin/activate && python -m pytest

llm-live: $(SETUP_STAMP)
	@if [ -n "$$VEI_LLM_LIVE_BYPASS" ]; then \
		echo "VEI_LLM_LIVE_BYPASS=1 set; skipping llm-live checks."; \
	elif [ -z "$$OPENAI_API_KEY" ]; then \
		echo "OPENAI_API_KEY not set; cannot run llm-live target. Set the key or export VEI_LLM_LIVE_BYPASS=1 to skip in CI."; \
		exit 4; \
	else \
		. $(VENV)/bin/activate && \
			VEI_SCENARIO=$${VEI_SCENARIO:-multi_channel} \
			vei-llm-test --provider openai --model $${VEI_LLM_MODEL:-gpt-5} --max-steps $${VEI_LLM_MAX_STEPS:-12} --task "$${VEI_LLM_TASK:-Baseline procurement workflow with identity checks.}"; \
		echo "llm-live metrics: pass=1 fail=0 cost_usd=unknown p95_latency_ms=unknown"; \
	fi

deps-audit: $(SETUP_STAMP)
	@if [ "$(MODE)" = "production" ]; then \
		. $(VENV)/bin/activate && pip-audit --skip-editable; \
	else \
		. $(VENV)/bin/activate && pip-audit --skip-editable || true; \
	fi

all: check test llm-live deps-audit

clean:
	rm -rf $(VENV) $(SETUP_STAMP)
