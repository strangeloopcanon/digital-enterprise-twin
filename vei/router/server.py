from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List

from .core import Router, MCPError


def _tool_names(router: Router) -> List[str]:
    return sorted({spec.name for spec in router.registry.list()})


def _help_payload(router: Router) -> Dict[str, Any]:
    return router.help_payload()


def jsonrpc_loop(router: Router) -> None:
    # Extremely small JSON-RPC 2.0 handler over stdio
    for line in sys.stdin:
        try:
            req = json.loads(line)
            method = req.get("method")
            params = req.get("params", {})
            if method == "mcp.call":
                tool = params["tool"]
                args = params.get("args", {})
                try:
                    if tool == "vei.observe":
                        res = router.observe(focus_hint=args.get("focus")).model_dump()
                    elif tool == "vei.tick":
                        dt = int(args.get("dt_ms", 1000))
                        res = router.tick(dt)
                    elif tool == "vei.pending":
                        res = router.pending()
                    elif tool == "vei.act_and_observe":
                        t = args.get("tool")
                        a = args.get("args", {})
                        if not isinstance(a, dict):
                            a = {}
                        res = router.act_and_observe(tool=t, args=a)
                    elif tool == "vei.reset":
                        # Reinitialize the router deterministically
                        try:
                            seed = (
                                int(args.get("seed"))
                                if "seed" in args
                                else int(os.environ.get("VEI_SEED", "42042"))
                            )
                        except Exception:
                            seed = int(os.environ.get("VEI_SEED", "42042"))
                        old = router
                        router = Router(
                            seed=seed,
                            artifacts_dir=old.trace.out_dir,
                            scenario=old.scenario,
                        )
                        res = {"ok": True, "seed": seed, "time_ms": router.bus.clock_ms}
                    elif tool == "vei.state":
                        include_state = bool(args.get("include_state", False))
                        tool_tail = int(args.get("tool_tail", 20) or 0)
                        include_receipts = args.get("include_receipts", True)
                        res = router.state_snapshot(
                            include_state=include_state,
                            tool_tail=tool_tail,
                            include_receipts=bool(include_receipts),
                        )
                    elif tool == "vei.help":
                        res = _help_payload(router)
                    else:
                        res = router.call_and_step(tool, args)
                    resp = {"jsonrpc": "2.0", "id": req.get("id"), "result": res}
                except MCPError as e:
                    resp = {
                        "jsonrpc": "2.0",
                        "id": req.get("id"),
                        "error": {"code": e.code, "message": e.message},
                    }
            elif method == "mcp.list_tools":
                tools = _tool_names(router)
                resp = {"jsonrpc": "2.0", "id": req.get("id"), "result": tools}
            else:
                resp = {
                    "jsonrpc": "2.0",
                    "id": req.get("id"),
                    "error": {"code": -32601, "message": "Method not found"},
                }
        except Exception as e:  # noqa: BLE001
            resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32000, "message": str(e)},
            }
        sys.stdout.write(json.dumps(resp, separators=(",", ":")) + "\n")
        sys.stdout.flush()


def main() -> None:
    seed = int(os.environ.get("VEI_SEED", "42042"))
    art = os.environ.get("VEI_ARTIFACTS_DIR")
    router = Router(seed=seed, artifacts_dir=art)
    try:
        jsonrpc_loop(router)
    finally:
        router.trace.flush()


if __name__ == "__main__":
    main()
