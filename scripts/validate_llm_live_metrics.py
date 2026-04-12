from __future__ import annotations

import argparse

from vei.llm_live_validator import validate_llm_live_artifacts


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate llm-live artifacts against .agents.yml thresholds."
    )
    parser.add_argument(
        "--artifacts",
        required=True,
        help="Path to the llm-live artifacts directory.",
    )
    parser.add_argument(
        "--agents-file",
        default=None,
        help="Optional path to .agents.yml.",
    )
    args = parser.parse_args()
    result = validate_llm_live_artifacts(
        args.artifacts,
        agents_file=args.agents_file,
    )
    print(result.message)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
