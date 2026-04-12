from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

_DEFAULT_SETTINGS: dict[str, Any] = {
    "mode": "baseline",
    "coverage": {
        "global": 0.80,
        "changed_lines": 0.90,
    },
    "llm": {
        "cost_ceiling_usd": 3,
        "latency_p95_ms": 3000,
        "provider": "openai",
        "model": "gpt-5-mini",
        "temperature": 0,
        "top_p": 1,
        "retry_attempts": 3,
        "max_calls_per_job": 9,
    },
    "security": {"sast_block_high": False},
    "deps": {"audit_block": False},
    "mutation_tests": {"schedule": "weekly"},
}

_PROVIDER_MODEL_FALLBACKS = {
    "openai": "gpt-5-mini",
    "anthropic": "claude-sonnet-4-5",
    "google": "gemini-2.5-pro",
    "openrouter": "grok-4",
}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def find_agents_file(start: str | Path | None = None) -> Path:
    candidates: list[Path] = []
    if start is not None:
        explicit = Path(start).expanduser().resolve()
        if explicit.suffix in {".yml", ".yaml"}:
            return explicit
        candidates.append(explicit)
    candidates.append(Path.cwd().resolve())
    candidates.append(repo_root())
    for origin in candidates:
        for parent in (origin, *origin.parents):
            candidate = parent / ".agents.yml"
            if candidate.exists():
                return candidate
    return repo_root() / ".agents.yml"


def _parse_scalar(raw: str) -> Any:
    value = raw.strip()
    if not value:
        return ""
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "none"}:
        return None
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    for raw_line in text.splitlines():
        if not raw_line.strip():
            continue
        stripped = raw_line.lstrip()
        if stripped.startswith("#"):
            continue
        indent = len(raw_line) - len(stripped)
        if ":" not in stripped:
            continue
        key, _, raw_value = stripped.partition(":")
        key = key.strip()
        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        current = stack[-1][1]
        value = raw_value.strip()
        if not value:
            nested: dict[str, Any] = {}
            current[key] = nested
            stack.append((indent, nested))
            continue
        current[key] = _parse_scalar(value)
    return root


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if (
            isinstance(value, dict)
            and isinstance(merged.get(key), dict)
            and merged.get(key) is not None
        ):
            merged[key] = _deep_merge(merged[key], value)
            continue
        merged[key] = value
    return merged


@lru_cache(maxsize=8)
def load_agents_settings(path: str | Path | None = None) -> dict[str, Any]:
    agents_path = find_agents_file(path)
    if not agents_path.exists():
        return dict(_DEFAULT_SETTINGS)
    payload = _parse_simple_yaml(agents_path.read_text(encoding="utf-8"))
    return _deep_merge(_DEFAULT_SETTINGS, payload)


def get_llm_defaults(path: str | Path | None = None) -> dict[str, Any]:
    settings = load_agents_settings(path)
    llm = settings.get("llm")
    if not isinstance(llm, dict):
        return dict(_DEFAULT_SETTINGS["llm"])
    return dict(llm)


def get_default_llm_provider(path: str | Path | None = None) -> str:
    llm = get_llm_defaults(path)
    provider = llm.get("provider")
    if isinstance(provider, str) and provider.strip():
        return provider.strip().lower()
    return str(_DEFAULT_SETTINGS["llm"]["provider"])


def default_model_for_provider(provider: str, *, path: str | Path | None = None) -> str:
    normalized_provider = provider.strip().lower()
    llm = get_llm_defaults(path)
    configured_provider = get_default_llm_provider(path)
    configured_model = llm.get("model")
    if (
        normalized_provider == configured_provider
        and isinstance(configured_model, str)
        and configured_model.strip()
    ):
        return configured_model.strip()
    return _PROVIDER_MODEL_FALLBACKS.get(
        normalized_provider,
        str(_DEFAULT_SETTINGS["llm"]["model"]),
    )


def resolve_llm_defaults(
    *,
    provider: str | None = None,
    model: str | None = None,
    path: str | Path | None = None,
) -> tuple[str, str]:
    resolved_provider = (
        provider.strip().lower()
        if isinstance(provider, str) and provider.strip()
        else None
    )
    if not resolved_provider:
        resolved_provider = get_default_llm_provider(path)
    resolved_model = model.strip() if isinstance(model, str) and model.strip() else None
    if not resolved_model:
        resolved_model = default_model_for_provider(resolved_provider, path=path)
    return resolved_provider, resolved_model


def get_llm_threshold(name: str, *, path: str | Path | None = None) -> Any:
    return get_llm_defaults(path).get(name)


__all__ = [
    "default_model_for_provider",
    "find_agents_file",
    "get_default_llm_provider",
    "get_llm_defaults",
    "get_llm_threshold",
    "load_agents_settings",
    "repo_root",
    "resolve_llm_defaults",
]
