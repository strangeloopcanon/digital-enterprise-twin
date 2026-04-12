from __future__ import annotations

import json
from pathlib import Path

from vei.llm_live_validator import (
    EXIT_CONFIG_MISSING,
    EXIT_COST_EXCEEDED,
    EXIT_FAILURE,
    EXIT_INFRASTRUCTURE,
    EXIT_OK,
    validate_llm_live_artifacts,
)


def _write_agents_config(
    path: Path, *, latency_ms: int = 3000, cost_usd: int = 3
) -> None:
    path.write_text(
        "\n".join(
            [
                "mode: baseline",
                "llm:",
                f"  cost_ceiling_usd: {cost_usd}",
                f"  latency_p95_ms: {latency_ms}",
                "  provider: openai",
                "  model: gpt-5",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_artifacts(
    root: Path,
    *,
    success: bool | None = True,
    latency_ms: int = 250,
    cost_usd: float | None = 0.5,
    exit_code: int = 0,
    run_error_class: str | None = None,
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "summary.json").write_text(
        json.dumps(
            {
                "summary": {
                    "success": success,
                    "exit_code": exit_code,
                    "run_error_class": run_error_class,
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (root / "llm_metrics.json").write_text(
        json.dumps(
            {
                "calls": 1,
                "estimated_cost_usd": cost_usd,
                "latency_p95_ms": latency_ms,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def test_llm_live_validator_accepts_green_run(tmp_path: Path) -> None:
    agents_file = tmp_path / ".agents.yml"
    artifacts_dir = tmp_path / "artifacts"
    _write_agents_config(agents_file)
    _write_artifacts(artifacts_dir)

    result = validate_llm_live_artifacts(artifacts_dir, agents_file=agents_file)

    assert result.exit_code == EXIT_OK
    assert "within_thresholds" in result.message


def test_llm_live_validator_rejects_latency_breach(tmp_path: Path) -> None:
    agents_file = tmp_path / ".agents.yml"
    artifacts_dir = tmp_path / "artifacts"
    _write_agents_config(agents_file, latency_ms=100)
    _write_artifacts(artifacts_dir, latency_ms=250)

    result = validate_llm_live_artifacts(artifacts_dir, agents_file=agents_file)

    assert result.exit_code == EXIT_FAILURE
    assert "latency_p95_ms=250>100" in result.message


def test_llm_live_validator_rejects_cost_breach(tmp_path: Path) -> None:
    agents_file = tmp_path / ".agents.yml"
    artifacts_dir = tmp_path / "artifacts"
    _write_agents_config(agents_file, cost_usd=1)
    _write_artifacts(artifacts_dir, cost_usd=1.5)

    result = validate_llm_live_artifacts(artifacts_dir, agents_file=agents_file)

    assert result.exit_code == EXIT_COST_EXCEEDED
    assert "estimated_cost_usd=1.50000000>1.00000000" in result.message


def test_llm_live_validator_rejects_missing_metrics(tmp_path: Path) -> None:
    agents_file = tmp_path / ".agents.yml"
    artifacts_dir = tmp_path / "artifacts"
    _write_agents_config(agents_file)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "summary.json").write_text(
        json.dumps({"summary": {"success": True}}, indent=2),
        encoding="utf-8",
    )

    result = validate_llm_live_artifacts(artifacts_dir, agents_file=agents_file)

    assert result.exit_code == EXIT_CONFIG_MISSING
    assert "llm metrics missing" in result.message


def test_llm_live_validator_rejects_missing_config(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    _write_artifacts(artifacts_dir)

    result = validate_llm_live_artifacts(
        artifacts_dir,
        agents_file=tmp_path / "missing.agents.yml",
    )

    assert result.exit_code == EXIT_CONFIG_MISSING
    assert "agents config missing" in result.message


def test_llm_live_validator_surfaces_infrastructure_failures(tmp_path: Path) -> None:
    agents_file = tmp_path / ".agents.yml"
    artifacts_dir = tmp_path / "artifacts"
    _write_agents_config(agents_file)
    _write_artifacts(
        artifacts_dir,
        success=None,
        exit_code=EXIT_INFRASTRUCTURE,
        run_error_class="infrastructure",
    )

    result = validate_llm_live_artifacts(artifacts_dir, agents_file=agents_file)

    assert result.exit_code == EXIT_INFRASTRUCTURE
    assert "infrastructure_failure" in result.message
