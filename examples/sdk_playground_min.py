#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from vei.sdk import SessionHook, create_session, get_scenario_manifest


class PrintHook(SessionHook):
    def before_call(self, tool: str, args: dict) -> None:
        print(f"[before] {tool} args={json.dumps(args, sort_keys=True)}")

    def after_call(self, tool: str, args: dict, result: dict) -> None:
        keys = ",".join(sorted(result.keys()))
        print(f"[after] {tool} result_keys={keys}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Minimal VEI SDK playground for embedding projects."
    )
    parser.add_argument("--seed", type=int, default=42042)
    parser.add_argument("--scenario", default="multi_channel")
    parser.add_argument(
        "--with-hook",
        action="store_true",
        help="Register a simple before/after call hook.",
    )
    args = parser.parse_args()

    manifest = get_scenario_manifest(args.scenario)
    print(
        "scenario manifest:",
        json.dumps(manifest.model_dump(), sort_keys=True),
    )

    session = create_session(seed=args.seed, scenario_name=args.scenario)
    if args.with_hook:
        session.register_hook(PrintHook())

    obs = session.observe()
    print("observe.action_menu_count:", len(obs.get("action_menu", [])))

    page = session.call_tool("browser.read", {})
    print("browser.read.url:", page.get("url"))

    sent = session.call_tool(
        "mail.compose",
        {
            "to": "sales@macrocompute.example",
            "subj": "Quote request",
            "body_text": "Please share price and ETA.",
        },
    )
    print("mail.compose.id:", sent.get("id"))


if __name__ == "__main__":
    main()
