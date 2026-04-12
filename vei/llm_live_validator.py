from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vei.project_settings import find_agents_file, get_llm_defaults

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_COST_EXCEEDED = 2
EXIT_INFRASTRUCTURE = 3
EXIT_CONFIG_MISSING = 4


@dataclass(frozen=True)
class LLMValidationResult:
    exit_code: int
    success: bool | None
    latency_p95_ms: int | None
    latency_limit_ms: int | None
    estimated_cost_usd: float | None
    cost_limit_usd: float | None
    message: str


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_llm_live_artifacts(
    artifacts_dir: str | Path,
    *,
    agents_file: str | Path | None = None,
) -> LLMValidationResult:
    resolved_agents = find_agents_file(agents_file)
    if not resolved_agents.exists():
        return LLMValidationResult(
            exit_code=EXIT_CONFIG_MISSING,
            success=None,
            latency_p95_ms=None,
            latency_limit_ms=None,
            estimated_cost_usd=None,
            cost_limit_usd=None,
            message=f"agents config missing: {resolved_agents}",
        )

    root = Path(artifacts_dir).expanduser().resolve()
    metrics_path = root / "llm_metrics.json"
    summary_path = root / "summary.json"
    if not metrics_path.exists():
        return LLMValidationResult(
            exit_code=EXIT_CONFIG_MISSING,
            success=None,
            latency_p95_ms=None,
            latency_limit_ms=None,
            estimated_cost_usd=None,
            cost_limit_usd=None,
            message=f"llm metrics missing: {metrics_path}",
        )
    if not summary_path.exists():
        return LLMValidationResult(
            exit_code=EXIT_CONFIG_MISSING,
            success=None,
            latency_p95_ms=None,
            latency_limit_ms=None,
            estimated_cost_usd=None,
            cost_limit_usd=None,
            message=f"summary missing: {summary_path}",
        )

    summary_payload = _load_json(summary_path)
    metrics_payload = _load_json(metrics_path)
    summary = summary_payload.get("summary", {})
    if not isinstance(summary, dict):
        summary = {}

    llm = get_llm_defaults(resolved_agents)
    latency_limit = int(llm.get("latency_p95_ms", 0) or 0)
    cost_limit_raw = llm.get("cost_ceiling_usd")
    cost_limit = float(cost_limit_raw) if cost_limit_raw is not None else None

    success = summary.get("success")
    summary_exit_code = summary.get("exit_code")
    run_error_class = summary.get("run_error_class")
    latency = metrics_payload.get("latency_p95_ms")
    latency_value = int(latency) if latency is not None else None
    estimated_cost = metrics_payload.get("estimated_cost_usd")
    estimated_cost_value = float(estimated_cost) if estimated_cost is not None else None

    exit_code = EXIT_OK
    reasons: list[str] = []
    if summary_exit_code == EXIT_INFRASTRUCTURE or run_error_class == "infrastructure":
        exit_code = EXIT_INFRASTRUCTURE
        reasons.append("infrastructure_failure")
    if success is not True:
        exit_code = EXIT_FAILURE if exit_code == EXIT_OK else exit_code
        reasons.append(f"success={success}")
    if latency_value is not None and latency_limit and latency_value > latency_limit:
        exit_code = EXIT_FAILURE
        reasons.append(f"latency_p95_ms={latency_value}>{latency_limit}")
    if (
        estimated_cost_value is not None
        and cost_limit is not None
        and estimated_cost_value > cost_limit
    ):
        exit_code = EXIT_COST_EXCEEDED
        reasons.append(
            f"estimated_cost_usd={estimated_cost_value:.8f}>{cost_limit:.8f}"
        )
    if not reasons:
        reasons.append("within_thresholds")

    message = (
        "llm-live metrics: "
        f"success={success} "
        f"latency_p95_ms={latency_value} "
        f"latency_limit_ms={latency_limit} "
        f"estimated_cost_usd={estimated_cost_value} "
        f"cost_limit_usd={cost_limit} "
        f"result={' ; '.join(reasons)}"
    )
    return LLMValidationResult(
        exit_code=exit_code,
        success=success if isinstance(success, bool) else None,
        latency_p95_ms=latency_value,
        latency_limit_ms=latency_limit,
        estimated_cost_usd=estimated_cost_value,
        cost_limit_usd=cost_limit,
        message=message,
    )


__all__ = [
    "EXIT_CONFIG_MISSING",
    "EXIT_COST_EXCEEDED",
    "EXIT_FAILURE",
    "EXIT_INFRASTRUCTURE",
    "EXIT_OK",
    "LLMValidationResult",
    "validate_llm_live_artifacts",
]
