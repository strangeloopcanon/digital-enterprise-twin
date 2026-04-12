from __future__ import annotations

import os
import shlex

from vei.project_settings import resolve_llm_defaults

_KEY_ENV_BY_PROVIDER = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


def main() -> None:
    provider, model = resolve_llm_defaults(
        provider=os.environ.get("VEI_LLM_PROVIDER"),
        model=os.environ.get("VEI_LLM_MODEL"),
        path=".agents.yml",
    )
    key_env = _KEY_ENV_BY_PROVIDER.get(provider, "")
    print(f"LLM_PROVIDER={shlex.quote(provider)}")
    print(f"LLM_MODEL={shlex.quote(model)}")
    print(f"LLM_KEY_ENV={shlex.quote(key_env)}")


if __name__ == "__main__":
    main()
