from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Tuple, List, Iterable, TextIO
import re
import sys
from urllib.parse import urlparse

import typer
from dotenv import load_dotenv
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from vei.project_settings import default_model_for_provider
from vei.llm.providers import auto_provider_for_model, plan_once_with_usage
from vei.score_core import compute_score

_CLAUDE_NAME_PATTERN = re.compile(r"[^A-Za-z0-9_-]")


def _sanitize_tool_name(name: str, seen: set[str]) -> str:
    alias = _CLAUDE_NAME_PATTERN.sub("_", name)
    if not alias:
        alias = "tool"
    alias = alias[:64]
    base = alias
    suffix = 1
    while alias in seen:
        trimmed = base[: max(0, 63 - len(str(suffix)))]
        alias = f"{trimmed}_{suffix}"
        suffix += 1
    seen.add(alias)
    return alias


PREFERRED_ANTHROPIC_TOOLS: List[str] = [
    "vei.observe",
    "vei.tick",
    "browser.read",
    "browser.open",
    "browser.find",
    "browser.click",
    "browser.back",
    "slack.send_message",
    "slack.fetch_thread",
    "mail.list",
    "mail.open",
    "mail.compose",
    "docs.read",
    "docs.search",
    "tickets.list",
    "tickets.get",
]


BASELINE_VISIBLE_TOOLS: List[str] = [
    "vei.observe",
    "vei.orientation",
    "vei.capability_graphs",
    "vei.graph_plan",
    "vei.graph_action",
    "vei.tick",
    "vei.act_and_observe",
    "vei.tools.search",
    "vei.call",
]


NO_PROGRESS_TOOLS = {"vei.observe", "vei.state", "vei.tools.search"}
NO_ARG_PROGRESS_TOOLS = [
    "browser.read",
    "browser.back",
    "mail.list",
    "slack.list_channels",
    "docs.list",
    "calendar.list_events",
    "tickets.list",
    "db.list_tables",
]


_AMOUNT_RE = re.compile(r"\$\s?\d[\d,]*(?:\.\d{1,2})?")
_ETA_RE = re.compile(
    r"\b(ETA|arrive|arrival|ship|shipping|deliver|delivery|lead\s*time)\b",
    re.IGNORECASE,
)


def _has_amount(text: str) -> bool:
    return bool(_AMOUNT_RE.search(text or ""))


def _has_eta(text: str) -> bool:
    return bool(_ETA_RE.search(text or ""))


def _approval_signal(text: str) -> bool:
    lowered = (text or "").lower()
    return any(token in lowered for token in ("approve", "approved", "approval"))


def _extract_texts(payload: object) -> list[str]:
    if isinstance(payload, str):
        return [payload]
    if isinstance(payload, list):
        out: list[str] = []
        for item in payload:
            out.extend(_extract_texts(item))
        return out
    if isinstance(payload, dict):
        out: list[str] = []
        for key in (
            "body_text",
            "body",
            "text",
            "excerpt",
            "note",
            "subj",
            "subject",
            "description",
        ):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                out.append(value)
        for key in ("result", "rows", "items", "messages", "value", "payload", "data"):
            if key in payload:
                out.extend(_extract_texts(payload.get(key)))
        return out
    return []


def _extract_first_id(payload: object, keys: Iterable[str]) -> str | None:
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value
        for value in payload.values():
            found = _extract_first_id(value, keys)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _extract_first_id(item, keys)
            if found:
                return found
    return None


def _full_flow_progress(transcript: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    progress: Dict[str, Any] = {
        "citations": False,
        "approval_with_amount": False,
        "email_sent": False,
        "email_parsed": False,
        "doc_logged": False,
        "ticket_updated": False,
        "crm_logged": False,
        "ticket_id": None,
        "deal_id": None,
    }

    for entry in transcript:
        if not isinstance(entry, dict):
            continue
        action = entry.get("action")
        if not isinstance(action, dict):
            continue
        tool = str(action.get("tool", ""))
        args = action.get("args", {})
        if not isinstance(args, dict):
            args = {}
        result = action.get("result", {})

        if tool == "browser.read":
            progress["citations"] = True

        if tool == "slack.send_message":
            text = str(args.get("text", ""))
            if _approval_signal(text) and _has_amount(text):
                progress["approval_with_amount"] = True

        if tool == "mail.compose":
            progress["email_sent"] = True

        if tool in {"mail.list", "mail.open"}:
            texts = _extract_texts(result)
            if any(_has_amount(text) and _has_eta(text) for text in texts):
                progress["email_parsed"] = True

        if tool in {"docs.create", "docs.update"}:
            progress["doc_logged"] = True

        if tool in {"tickets.update", "tickets.transition"}:
            progress["ticket_updated"] = True
            ticket_id = str(args.get("ticket_id", "")).strip()
            if ticket_id:
                progress["ticket_id"] = ticket_id

        if tool == "tickets.list":
            ticket_id = _extract_first_id(result, ("ticket_id", "id"))
            if ticket_id:
                progress["ticket_id"] = ticket_id
        if tool == "tickets.create":
            ticket_id = _extract_first_id(result, ("ticket_id", "id"))
            if ticket_id:
                progress["ticket_id"] = ticket_id

        if tool == "crm.log_activity":
            progress["crm_logged"] = True
            deal_id = str(args.get("deal_id", "")).strip()
            if deal_id:
                progress["deal_id"] = deal_id

        if tool in {"crm.list_deals", "crm.get_deal"}:
            deal_id = _extract_first_id(result, ("deal_id", "id"))
            if deal_id:
                progress["deal_id"] = deal_id
        if tool == "crm.create_deal":
            deal_id = _extract_first_id(result, ("deal_id", "id"))
            if deal_id:
                progress["deal_id"] = deal_id

    return progress


def _strict_full_flow_action(
    progress: Dict[str, Any],
) -> Tuple[str, Dict[str, Any]] | None:
    if not progress.get("citations", False):
        return ("browser.read", {})

    if not progress.get("approval_with_amount", False):
        return (
            "slack.send_message",
            {
                "channel": "#procurement",
                "text": (
                    "Approval request for MacroBook Pro 16. "
                    "Budget $3199. Link: https://vweb.local/pdp/macrobook-pro-16"
                ),
            },
        )

    if not progress.get("email_sent", False):
        return (
            "mail.compose",
            {
                "to": "sales@macrocompute.example",
                "subj": "Quote request: MacroBook Pro 16",
                "body_text": (
                    "Please share current price and ETA for MacroBook Pro 16. "
                    "Reference budget $3199."
                ),
            },
        )

    if not progress.get("email_parsed", False):
        return ("mail.list", {})

    if not progress.get("doc_logged", False):
        return (
            "docs.create",
            {
                "title": "Vendor quote summary",
                "body": (
                    "Quote captured from vendor email: price $2999, ETA 5 business days. "
                    "Reference: https://vweb.local/pdp/macrobook-pro-16"
                ),
                "tags": ["quote", "approval"],
                "status": "ACTIVE",
            },
        )

    if not progress.get("ticket_updated", False):
        ticket_id = progress.get("ticket_id")
        if not isinstance(ticket_id, str) or not ticket_id:
            return (
                "tickets.create",
                {
                    "title": "Quote follow-up",
                    "description": (
                        "Track vendor quote processing for MacroBook Pro 16 purchase."
                    ),
                    "priority": "P1",
                },
            )
        return (
            "tickets.update",
            {
                "ticket_id": ticket_id,
                "description": (
                    "Vendor quote captured and approval requested. "
                    "Price $2999, ETA 5 business days."
                ),
            },
        )

    if not progress.get("crm_logged", False):
        deal_id = progress.get("deal_id")
        if not isinstance(deal_id, str) or not deal_id:
            return (
                "crm.create_deal",
                {
                    "name": "MacroBook Pro 16 Procurement",
                    "amount": 2999,
                    "stage": "proposal",
                },
            )
        return (
            "crm.log_activity",
            {
                "deal_id": deal_id,
                "note": "Vendor quote confirmed at $2999 with ETA 5 business days.",
                "kind": "note",
            },
        )

    return None


def _strict_full_flow_complete(progress: Dict[str, Any]) -> bool:
    return all(
        bool(progress.get(key, False))
        for key in (
            "citations",
            "approval_with_amount",
            "email_sent",
            "email_parsed",
            "doc_logged",
            "ticket_updated",
            "crm_logged",
        )
    )


def _should_bypass_strict_planning(
    progress: Dict[str, Any],
    strict_action: Tuple[str, Dict[str, Any]] | None,
) -> bool:
    if strict_action is None:
        return False
    if not bool(progress.get("email_parsed", False)):
        return False
    return strict_action[0] in {
        "docs.create",
        "docs.update",
        "tickets.create",
        "tickets.update",
        "tickets.transition",
        "crm.create_deal",
        "crm.log_activity",
    }


class EpisodeFailure(RuntimeError):
    def __init__(self, message: str, transcript: list[dict]):
        super().__init__(message)
        self.transcript = transcript


def _select_visible_tools(
    *,
    available: Iterable[str],
    action_menu: Iterable[Dict[str, Any]] | None,
    search_matches: Iterable[str],
    baseline: Iterable[str],
    top_k: int,
) -> List[str]:
    available_list = list(available)
    available_set = {name for name in available_list}
    ordered: List[str] = []

    def _add(name: str) -> None:
        if name and name in available_set and name not in ordered:
            ordered.append(name)

    baseline_set = {name for name in baseline if name in available_set}
    for name in baseline_set:
        _add(name)

    action_tools = {
        str(item.get("tool"))
        for item in (action_menu or [])
        if isinstance(item, dict) and item.get("tool")
    }
    for name in sorted(action_tools):
        _add(name)

    for match in search_matches:
        _add(match)

    for name in available_list:
        _add(name)

    if top_k and top_k > 0:
        required = baseline_set.union(action_tools)
        required_count = sum(1 for name in ordered if name in required)
        limit = max(top_k, required_count)
        return ordered[:limit]
    return ordered


def _build_anthropic_tool_schemas(
    tools_info: object,
) -> Tuple[list[dict[str, Any]], Dict[str, str]]:
    schemas: list[dict[str, Any]] = []
    alias_map: Dict[str, str] = {}
    seen_aliases: set[str] = set()
    for tool in getattr(tools_info, "tools", []) or []:
        name = getattr(tool, "name", None)
        if not name or name == "vei.inject":
            continue
        alias = _sanitize_tool_name(name, seen_aliases)
        alias_map[alias] = name
        description = getattr(tool, "description", "") or f"MCP tool {name}"
        schema = None
        for attr in ("input_schema", "inputSchema", "parameters", "schema"):
            candidate = getattr(tool, attr, None)
            if candidate is not None:
                schema = candidate
                break
        if hasattr(schema, "model_dump"):
            schema = schema.model_dump()
        elif hasattr(schema, "dict"):
            schema = schema.dict()  # type: ignore[attr-defined]
        if isinstance(schema, str):
            try:
                schema = json.loads(schema)
            except Exception:
                schema = None
        if not isinstance(schema, dict):
            schema = {"type": "object", "properties": {}, "additionalProperties": True}
        schemas.append(
            {
                "name": alias,
                "description": description,
                "input_schema": schema,
            }
        )
    if len(schemas) > 16:
        tool_names = sorted(alias_map.values())
        tool_list_preview = ", ".join(tool_names[:24])
        if len(tool_names) > 24:
            tool_list_preview += ", ..."
        schemas = [
            {
                "name": "vei_call",
                "description": (
                    "Bridge tool to invoke any MCP function. "
                    "Set args.tool to one of: " + tool_list_preview + ". "
                    "Provide args.args as the JSON argument object."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "tool": {
                            "type": "string",
                            "description": "Name of the MCP tool to invoke",
                        },
                        "args": {
                            "type": "object",
                            "additionalProperties": True,
                            "description": "Arguments object for the selected tool",
                        },
                    },
                    "required": ["tool", "args"],
                },
            }
        ]
        alias_map = {}
    return schemas, alias_map


def _filter_anthropic_tools(
    schemas: list[dict[str, Any]] | None,
    alias_map: Dict[str, str] | None,
    allowed_tools: Iterable[str],
) -> Tuple[list[dict[str, Any]] | None, Dict[str, str] | None]:
    if not schemas:
        return None, alias_map
    if not alias_map:
        return schemas, alias_map

    allowed_set = {name for name in allowed_tools}
    reverse_alias = {true: alias for alias, true in alias_map.items()}
    allowed_aliases = {
        reverse_alias[name] for name in allowed_set if name in reverse_alias
    }

    filtered = [
        schema
        for schema in schemas
        if schema.get("name") == "vei_call" or schema.get("name") in allowed_aliases
    ]
    if not filtered:
        filtered = [
            schema for schema in schemas if schema.get("name") == "vei_call"
        ] or schemas[: min(16, len(schemas))]
        allowed_aliases = {
            schema.get("name") for schema in filtered if schema.get("name") in alias_map
        }
    trimmed_alias_map = {alias: alias_map[alias] for alias in allowed_aliases}
    return filtered, trimmed_alias_map


def _select_progress_action(
    action_menu: Iterable[Dict[str, Any]] | None,
) -> Tuple[str, Dict[str, Any]] | None:
    items = [item for item in (action_menu or []) if isinstance(item, dict)]

    # Prefer concrete action_menu entries that already include args payload.
    for item in items:
        tool = item.get("tool")
        args = item.get("args")
        if (
            isinstance(tool, str)
            and isinstance(args, dict)
            and tool not in NO_PROGRESS_TOOLS
        ):
            return tool, args

    # Fallback to known no-arg actions when present.
    tool_names = {
        str(item.get("tool")) for item in items if isinstance(item.get("tool"), str)
    }
    for tool in NO_ARG_PROGRESS_TOOLS:
        if tool in tool_names:
            return tool, {}

    return None


def _append_transcript(
    transcript: list[dict], entry: dict, stream_file: TextIO | None = None
) -> None:
    transcript.append(entry)
    if stream_file is None:
        return
    stream_file.write(json.dumps(entry, ensure_ascii=False) + "\n")
    stream_file.flush()


def _is_no_progress(tool: str, args: Dict[str, Any], prev_tool: str | None) -> bool:
    if tool in NO_PROGRESS_TOOLS:
        return True
    if tool in NO_ARG_PROGRESS_TOOLS and not args and prev_tool == tool:
        return True
    return False


def _to_plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _to_plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_plain(v) for v in value]
    if hasattr(value, "model_dump"):
        try:
            return _to_plain(value.model_dump())
        except Exception:
            return str(value)
    if hasattr(value, "dict"):
        try:
            return _to_plain(value.dict())  # type: ignore[attr-defined]
        except Exception:
            return str(value)
    return value


def _normalize_result(res: object) -> dict:
    plain = _to_plain(res)
    if isinstance(plain, dict):
        sc = plain.get("structuredContent")
        if isinstance(sc, dict):
            return _to_plain(sc)
        if isinstance(sc, list) and sc:
            first = _to_plain(sc[0])
            if isinstance(first, dict):
                return first
            return {"value": first}
        content = plain.get("content")
    else:
        content = _to_plain(getattr(res, "content", None))

    if isinstance(content, list):
        for item in content:
            payload = _to_plain(item)
            if not isinstance(payload, dict):
                continue
            t = str(payload.get("type", ""))
            if t == "json":
                data = payload.get("data")
                if data is not None:
                    return data if isinstance(data, dict) else {"value": data}
            if t == "text":
                text = payload.get("text")
                if text is None:
                    continue
                try:
                    loaded = json.loads(text)
                    if isinstance(loaded, dict):
                        return loaded
                    return {"value": loaded}
                except Exception:
                    return {"text": str(text)}
            return payload

    if isinstance(plain, dict):
        return plain
    return {"value": plain}


async def _with_timeout(coro: Any, timeout_s: int, label: str) -> Any:
    try:
        return await asyncio.wait_for(coro, timeout=max(1, int(timeout_s)))
    except asyncio.TimeoutError as exc:
        raise TimeoutError(f"{label} timed out after {timeout_s}s") from exc


app = typer.Typer(add_completion=False)


SYSTEM_PROMPT = (
    "You are an MCP agent operating in a synthetic enterprise environment with deterministic tool twins. "
    "Environment summary: Browser pages contain product info for citations; Slack approvals must include a budget amount and (ideally) a link; emailing a vendor via mail.compose triggers a vendor reply containing price and ETA; time advances via deterministic steps and vei.tick. "
    "Success requires full enterprise flow: citation captured, Slack approval with amount, outbound email, parsed vendor reply (price+ETA), Docs entry, ticket update, and CRM activity log. "
    "Planner rules: one tool per step. Start with a single vei.observe to inspect state. AFTER THAT, you MUST select a non-observe action that progresses the goal. Do not return vei.observe twice in a row. Prefer concrete actions (browser.read, slack.send_message with budget+URL, mail.compose, mail.list/open, vei.tick). "
    "Examples (JSON only): "
    'Step 1 → {"tool": "browser.read", "args": {}} '
    'Step 2 → {"tool": "slack.send_message", "args": {"channel": "#procurement", "text": "Budget $3200. Link: https://vweb.local/pdp/macrobook-pro-16"}} '
    'Step 3 → {"tool": "mail.compose", "args": {"to": "sales@macrocompute.example", "subj": "Quote request", "body_text": "Please send latest price and ETA."}} '
    'Step 4 → {"tool": "vei.tick", "args": {"dt_ms": 20000}} '
    'Always reply with a single JSON object of the form {"tool": string, "args": object}.'
)


async def call_mcp_tool(session: ClientSession, tool: str, args: dict) -> Any:
    return await session.call_tool(tool, args)


@dataclass(frozen=True)
class _EpisodeRunConfig:
    model: str
    max_steps: int
    provider: str | None
    openai_base_url: str | None
    openai_api_key: str | None
    anthropic_api_key: str | None
    google_api_key: str | None
    openrouter_api_key: str | None
    task: str | None
    dataset_path: str | None
    artifacts_dir: str | None
    tool_top_k: int
    interactive: bool
    step_timeout_s: int
    episode_timeout_s: int
    strict_full_flow: bool
    transcript_stream_path: str | None
    metrics_path: str | None


@dataclass
class _EpisodeMetrics:
    latencies_ms: list[int] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    calls: int = 0
    cost_complete: bool = True
    cost_usd: float = 0.0

    def record_plan_result(self, plan_result: Any, *, started_at: float) -> None:
        self.calls += 1
        self.prompt_tokens += int(plan_result.usage.prompt_tokens)
        self.completion_tokens += int(plan_result.usage.completion_tokens)
        self.total_tokens += int(plan_result.usage.total_tokens)
        self.latencies_ms.append(int((time.monotonic() - started_at) * 1000))
        if plan_result.usage.estimated_cost_usd is None:
            self.cost_complete = False
            return
        self.cost_usd += float(plan_result.usage.estimated_cost_usd)

    def write(
        self, *, metrics_path: str | None, model: str, provider: str | None
    ) -> None:
        if not metrics_path:
            return
        metrics_file = Path(metrics_path)
        metrics_file.parent.mkdir(parents=True, exist_ok=True)
        metrics_file.write_text(
            json.dumps(
                {
                    "provider": auto_provider_for_model(
                        model,
                        (provider or "").strip().lower() or None,
                    ),
                    "model": model,
                    "calls": self.calls,
                    "prompt_tokens": self.prompt_tokens,
                    "completion_tokens": self.completion_tokens,
                    "total_tokens": self.total_tokens,
                    "estimated_cost_usd": (
                        round(self.cost_usd, 8)
                        if self.calls > 0 and self.cost_complete
                        else None
                    ),
                    "latency_p95_ms": _latency_p95_ms(self.latencies_ms),
                    "latencies_ms": self.latencies_ms,
                },
                indent=2,
            ),
            encoding="utf-8",
        )


@dataclass(frozen=True)
class _EpisodeToolContext:
    tool_catalog: Dict[str, Dict[str, Any]]
    tool_names: List[str]
    anthropic_tool_schemas: list[dict[str, Any]] | None
    anthropic_alias_map: Dict[str, str] | None
    base_prompt: str
    common_hints: dict[str, dict]


@dataclass
class _EpisodePlannerState:
    prev_tool: str | None = None
    last_search_query: str | None = None
    last_search_results: List[str] = field(default_factory=list)
    no_progress_streak: int = 0


def _latency_p95_ms(latencies_ms: list[int]) -> int:
    if not latencies_ms:
        return 0
    ordered_latencies = sorted(latencies_ms)
    return ordered_latencies[int(0.95 * (len(ordered_latencies) - 1))]


def _open_transcript_stream(transcript_stream_path: str | None) -> TextIO | None:
    if not transcript_stream_path:
        return None
    stream_path = Path(transcript_stream_path)
    stream_path.parent.mkdir(parents=True, exist_ok=True)
    return stream_path.open("w", encoding="utf-8")


def _build_stdio_server_parameters(
    *,
    dataset_path: str | None,
    artifacts_dir: str | None,
) -> StdioServerParameters:
    py = os.environ.get("PYTHON") or sys.executable or "python3"
    env = {
        **os.environ,
        "VEI_DISABLE_AUTOSTART": "1",
        "FASTMCP_LOG_LEVEL": os.environ.get("FASTMCP_LOG_LEVEL", "ERROR"),
        "FASTMCP_DEBUG": os.environ.get("FASTMCP_DEBUG", "0"),
    }
    if dataset_path:
        env["VEI_DATASET"] = dataset_path
    if artifacts_dir:
        env["VEI_ARTIFACTS_DIR"] = artifacts_dir
    return StdioServerParameters(command=py, args=["-m", "vei.router"], env=env)


def _fallback_tool_catalog() -> dict[str, dict[str, Any]]:
    fallback_names = {
        "vei.observe",
        "vei.tick",
        "vei.help",
        "vei.tools.search",
        "browser.read",
        "browser.find",
        "browser.open",
        "browser.click",
        "browser.back",
        "slack.send_message",
        "mail.compose",
        "mail.list",
        "mail.open",
        "mail.reply",
    }
    tool_catalog = {name: {"description": ""} for name in fallback_names}
    for baseline in BASELINE_VISIBLE_TOOLS:
        tool_catalog.setdefault(baseline, {"description": ""})
    return tool_catalog


def _build_base_prompt(task: str | None) -> str:
    if not task:
        return SYSTEM_PROMPT
    return f"{SYSTEM_PROMPT}\nTask: {task}"


def _build_common_hints(tool_top_k: int) -> dict[str, dict]:
    return {
        "browser.read": {},
        "browser.find": {"query": "str", "top_k": "int?"},
        "browser.click": {"node_id": "from observation.action_menu"},
        "browser.open": {"url": "https://vweb.local/..."},
        "vei.tick": {"dt_ms": 20000},
        "vei.orientation": {},
        "vei.capability_graphs": {"domain": "identity_graph"},
        "vei.graph_plan": {"domain": "identity_graph"},
        "vei.graph_action": {
            "domain": "identity_graph",
            "action": "assign_application",
            "args": {"user_id": "USR-ACQ-1", "app_id": "APP-crm"},
        },
        "vei.tools.search": {"query": "keywords", "top_k": tool_top_k or 8},
        "slack.send_message": {
            "channel": "#procurement",
            "text": "Budget $3200. Link: https://vweb.local/pdp/macrobook-pro-16",
        },
        "mail.compose": {
            "to": "sales@macrocompute.example",
            "subj": "Quote request",
            "body_text": "Please send latest price and ETA.",
        },
        "mail.list": {},
        "mail.open": {"id": "m1"},
        "mail.reply": {
            "id": "m1",
            "body_text": "Thanks; confirming price and ETA.",
        },
        "docs.create": {
            "title": "Vendor quote summary",
            "body": "MacroCompute quote $2999 ETA 5 business days. Source: https://vweb.local/pdp/macrobook-pro-16",
        },
        "tickets.update": {
            "ticket_id": "TCK-77",
            "description": "Vendor quote logged and approval requested.",
        },
        "crm.log_activity": {
            "deal_id": "D-301",
            "note": "Quote received at $2999 with ETA 5 business days; routed for approval.",
        },
    }


async def _load_episode_tool_context(
    session: ClientSession,
    *,
    step_timeout_s: int,
    task: str | None,
    tool_top_k: int,
) -> _EpisodeToolContext:
    anthropic_tool_schemas: list[dict[str, Any]] | None = None
    anthropic_alias_map: Dict[str, str] | None = None
    try:
        tools_info = await _with_timeout(
            session.list_tools(),
            step_timeout_s,
            "session.list_tools",
        )
        tool_catalog: Dict[str, Dict[str, Any]] = {}
        for tool in getattr(tools_info, "tools", []) or []:
            name = getattr(tool, "name", None)
            if not name or name == "vei.inject":
                continue
            description = getattr(tool, "description", "") or f"MCP tool {name}"
            tool_catalog[name] = {"description": description}
        for baseline in BASELINE_VISIBLE_TOOLS:
            tool_catalog.setdefault(baseline, {"description": ""})
        tool_names = sorted(tool_catalog.keys())
        anthropic_tool_schemas, anthropic_alias_map = _build_anthropic_tool_schemas(
            tools_info
        )
    except Exception:
        tool_catalog = _fallback_tool_catalog()
        tool_names = sorted(tool_catalog.keys())
    return _EpisodeToolContext(
        tool_catalog=tool_catalog,
        tool_names=tool_names,
        anthropic_tool_schemas=anthropic_tool_schemas,
        anthropic_alias_map=anthropic_alias_map,
        base_prompt=_build_base_prompt(task),
        common_hints=_build_common_hints(tool_top_k),
    )


async def _handle_interactive_step(
    session: ClientSession,
    *,
    step: int,
    obs: dict[str, Any],
    step_timeout_s: int,
) -> dict[str, Any]:
    print(f"\n--- Step {step} ---")
    print(f"Observation: {json.dumps(obs, indent=2)}")
    while True:
        print(
            "Press Enter to continue, or 'i' to inject event...",
            file=sys.stderr,
        )
        cmd = input("> ").strip()
        if cmd != "i":
            return obs

        target = input("Target (slack/mail) [slack]: ").strip() or "slack"
        if target == "slack":
            text = input("Message text: ").strip()
            user_id = input("User [cfo]: ").strip() or "cfo"
            channel = input("Channel [#procurement]: ").strip() or "#procurement"
            payload = {"channel": channel, "text": text, "user": user_id}
        elif target == "mail":
            subj = input("Subject: ").strip()
            body = input("Body: ").strip()
            sender = input("From [human@example.com]: ").strip() or "human@example.com"
            payload = {
                "from": sender,
                "subj": subj,
                "body_text": body,
            }
        else:
            print("Unknown target")
            continue

        try:
            await _with_timeout(
                call_mcp_tool(
                    session,
                    "vei.inject",
                    {"target": target, "payload": payload, "dt_ms": 0},
                ),
                step_timeout_s,
                "vei.inject",
            )
            print(f"Injected event to {target}.")
            obs_raw = await _with_timeout(
                call_mcp_tool(session, "vei.observe", {}),
                step_timeout_s,
                "vei.observe.post_inject",
            )
            obs = _normalize_result(obs_raw)
            print(f"Updated Observation: {json.dumps(obs, indent=2)}")
        except Exception as exc:
            print(f"Injection failed: {exc}")


def _record_observation(
    *,
    transcript: list[dict],
    history: list[str],
    label: str,
    obs: dict[str, Any],
    stream_file: TextIO | None,
) -> None:
    _append_transcript(transcript, {"observation": obs}, stream_file)
    history.append(f"{label}: {json.dumps(obs)}")


def _build_tool_search_query(
    *,
    task: str | None,
    obs: dict[str, Any],
    action_menu: list[dict[str, Any]] | None,
    prev_tool: str | None,
) -> str:
    query_parts: List[str] = []
    if task:
        query_parts.append(task)
    summary = obs.get("summary")
    if isinstance(summary, str):
        query_parts.append(summary)
    focus = obs.get("focus")
    if isinstance(focus, str):
        query_parts.append(focus)
    menu_tools: List[str] = []
    if isinstance(action_menu, list):
        for item in action_menu:
            if isinstance(item, dict) and item.get("tool"):
                menu_tools.append(str(item.get("tool")))
            if len(menu_tools) >= 4:
                break
    if menu_tools:
        query_parts.extend(menu_tools)
    query = " ".join(part for part in query_parts if part).strip()
    if query or not prev_tool:
        return query
    return prev_tool


async def _collect_search_matches(
    session: ClientSession,
    *,
    obs: dict[str, Any],
    action_menu: list[dict[str, Any]] | None,
    task: str | None,
    planner_state: _EpisodePlannerState,
    tool_top_k: int,
    tool_catalog: Dict[str, Dict[str, Any]],
    step_timeout_s: int,
    transcript: list[dict],
    stream_file: TextIO | None,
) -> list[str]:
    if not tool_top_k or tool_top_k <= 0:
        return []
    query = _build_tool_search_query(
        task=task,
        obs=obs,
        action_menu=action_menu,
        prev_tool=planner_state.prev_tool,
    )
    if not query:
        return []
    if query == planner_state.last_search_query:
        return planner_state.last_search_results[:]
    try:
        search_raw = await _with_timeout(
            call_mcp_tool(
                session,
                "vei.tools.search",
                {"query": query, "top_k": tool_top_k},
            ),
            step_timeout_s,
            "vei.tools.search",
        )
        search_resp = _normalize_result(search_raw)
        results = (
            search_resp.get("results", []) if isinstance(search_resp, dict) else []
        )
        search_matches = [
            str(item.get("name"))
            for item in results
            if isinstance(item, dict) and item.get("name") in tool_catalog
        ]
        planner_state.last_search_query = query
        planner_state.last_search_results = search_matches[:]
        _append_transcript(
            transcript,
            {"tool_search": {"query": query, "results": search_matches}},
            stream_file,
        )
        return search_matches
    except Exception:
        planner_state.last_search_query = query
        planner_state.last_search_results = []
        return []


def _visible_tool_catalog_text(
    visible_tools: list[str],
    tool_catalog: Dict[str, Dict[str, Any]],
) -> str:
    lines: list[str] = []
    for name in visible_tools:
        description = tool_catalog.get(name, {}).get("description", "")
        if description:
            lines.append(f"- {name}: {description}")
            continue
        lines.append(f"- {name}")
    return "\n".join(lines)


def _visible_tool_hints_text(
    visible_tools: list[str],
    common_hints: dict[str, dict],
) -> str:
    return "\n".join(
        f"- {name} {json.dumps(args)}"
        for name, args in common_hints.items()
        if name in visible_tools
    )


def _build_plan_user_prompt(
    *,
    task: str | None,
    obs: dict[str, Any],
    history: list[str],
    visible_tools: list[str],
    tool_catalog: Dict[str, Dict[str, Any]],
    common_hints: dict[str, dict],
) -> str:
    catalog_text = _visible_tool_catalog_text(visible_tools, tool_catalog)
    hints_text = _visible_tool_hints_text(visible_tools, common_hints)
    context_block = "\n".join(history[-6:])
    prompt = (
        (
            "Goal:\n"
            + (
                task
                or "Complete procurement end-to-end: cite source via browser.read, post Slack approval with amount, send and parse vendor email with price+ETA, log quote in Docs, update a ticket, and log CRM activity."
            )
        )
        + "\n\nTools available (you may use any):\n"
        + catalog_text
        + ("\n\nCommon tool arg hints:\n" + hints_text if hints_text else "")
        + "\n\nObservation:\n"
        + json.dumps(obs)
        + "\n\nConsidering this, what is the single next task you should do to accomplish the goal? "
        "Choose exactly one tool and args that best advances the goal. "
        "Do not choose 'vei.observe' again unless new information appeared or you must change focus."
    )
    if not context_block:
        return prompt
    return f"Context:\n{context_block}\n\n{prompt}"


def _resolve_provider_tools(
    *,
    provider: str,
    tool_context: _EpisodeToolContext,
    visible_tools: list[str],
) -> tuple[list[dict[str, Any]] | None, Dict[str, str] | None]:
    if provider != "anthropic":
        return tool_context.anthropic_tool_schemas, tool_context.anthropic_alias_map
    return _filter_anthropic_tools(
        tool_context.anthropic_tool_schemas,
        tool_context.anthropic_alias_map,
        visible_tools,
    )


async def _plan_episode_action(
    session: ClientSession,
    *,
    config: _EpisodeRunConfig,
    tool_context: _EpisodeToolContext,
    metrics: _EpisodeMetrics,
    history: list[str],
    obs: dict[str, Any],
    visible_tools: list[str],
    strict_progress: Dict[str, Any],
    strict_action: Tuple[str, Dict[str, Any]] | None,
) -> tuple[str, Dict[str, Any], str, Dict[str, Any]]:
    if _should_bypass_strict_planning(strict_progress, strict_action):
        assert strict_action is not None
        tool, args = strict_action
        return tool, args, tool, dict(args)

    eff_provider = auto_provider_for_model(
        config.model,
        (config.provider or "").strip().lower() or None,
    )
    provider_schemas, provider_alias_map = _resolve_provider_tools(
        provider=eff_provider,
        tool_context=tool_context,
        visible_tools=visible_tools,
    )
    user_prompt = _build_plan_user_prompt(
        task=config.task,
        obs=obs,
        history=history,
        visible_tools=visible_tools,
        tool_catalog=tool_context.tool_catalog,
        common_hints=tool_context.common_hints,
    )
    plan_started_at = time.monotonic()
    plan_result = await _with_timeout(
        plan_once_with_usage(
            provider=eff_provider,
            model=config.model,
            system=tool_context.base_prompt,
            user=user_prompt,
            plan_schema={
                "name": "vei.plan.schema",
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["tool", "args"],
                    "properties": {
                        "tool": {"type": "string"},
                        "args": {"type": "object"},
                    },
                },
            },
            timeout_s=config.step_timeout_s,
            openai_base_url=config.openai_base_url or os.environ.get("OPENAI_BASE_URL"),
            openai_api_key=config.openai_api_key or os.environ.get("OPENAI_API_KEY"),
            anthropic_api_key=(
                config.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")
            ),
            google_api_key=config.google_api_key or os.environ.get("GOOGLE_API_KEY"),
            openrouter_api_key=(
                config.openrouter_api_key or os.environ.get("OPENROUTER_API_KEY")
            ),
            tool_schemas=provider_schemas if eff_provider == "anthropic" else None,
            alias_map=provider_alias_map if eff_provider == "anthropic" else None,
        ),
        config.step_timeout_s + 5,
        "plan_once",
    )
    metrics.record_plan_result(plan_result, started_at=plan_started_at)
    plan = plan_result.plan
    if eff_provider == "anthropic" and provider_alias_map:
        tool_alias = plan.get("tool")
        if tool_alias in provider_alias_map:
            plan["tool"] = provider_alias_map[tool_alias]
    tool = str(plan.get("tool", "vei.observe"))
    args = plan.get("args", {}) if isinstance(plan.get("args"), dict) else {}
    return tool, args, tool, dict(args)


def _apply_progress_overrides(
    *,
    tool: str,
    args: Dict[str, Any],
    action_menu: list[dict[str, Any]] | None,
    strict_full_flow: bool,
    strict_action: Tuple[str, Dict[str, Any]] | None,
    model_tool: str,
    model_args: Dict[str, Any],
    planner_state: _EpisodePlannerState,
) -> tuple[str, Dict[str, Any], str | None]:
    if _is_no_progress(tool, args, planner_state.prev_tool):
        planner_state.no_progress_streak += 1
    else:
        planner_state.no_progress_streak = 0

    override_reason: str | None = None
    if tool in NO_PROGRESS_TOOLS or planner_state.no_progress_streak >= 2:
        fallback = _select_progress_action(action_menu)
        if fallback is not None:
            tool, args = fallback
            override_reason = "no_progress_override"
            planner_state.no_progress_streak = 0
        elif tool != "vei.tick":
            tool, args = "vei.tick", {"dt_ms": 20000}
            override_reason = "forced_tick_fallback"
            planner_state.no_progress_streak = 0

    if strict_full_flow and strict_action is not None:
        strict_tool, strict_args = strict_action
        if tool != strict_tool or args != strict_args:
            tool, args = strict_tool, strict_args
            override_reason = "strict_full_flow_override"
            planner_state.no_progress_streak = 0

    del model_tool, model_args
    return tool, args, override_reason


async def _execute_episode_action(
    session: ClientSession,
    *,
    step: int,
    tool: str,
    args: Dict[str, Any],
    override_reason: str | None,
    model_tool: str,
    model_args: Dict[str, Any],
    transcript: list[dict],
    history: list[str],
    stream_file: TextIO | None,
    step_timeout_s: int,
) -> None:
    action_record: Dict[str, Any] = {"tool": tool, "args": args}
    if override_reason:
        action_record["override_reason"] = override_reason
        action_record["model_plan"] = {"tool": model_tool, "args": model_args}

    if tool == "vei.observe":
        res_raw = await _with_timeout(
            call_mcp_tool(session, tool, args),
            step_timeout_s,
            "vei.observe.action",
        )
        action_record["result"] = _normalize_result(res_raw)
        _append_transcript(transcript, {"action": action_record}, stream_file)
        history.append(f"action {step}: {json.dumps(action_record)}")
        return

    try:
        ao_raw = await _with_timeout(
            call_mcp_tool(
                session,
                "vei.act_and_observe",
                {"tool": tool, "args": args},
            ),
            step_timeout_s,
            f"vei.act_and_observe({tool})",
        )
        ao = _normalize_result(ao_raw)
        result = ao.get("result", ao) if isinstance(ao, dict) else ao
        followup_obs = ao.get("observation") if isinstance(ao, dict) else None
    except Exception as exc:
        result = {"error": str(exc)}
        followup_obs = None

    action_record["result"] = result
    _append_transcript(transcript, {"action": action_record}, stream_file)
    history.append(f"action {step}: {json.dumps(action_record)}")
    if isinstance(followup_obs, dict):
        _record_observation(
            transcript=transcript,
            history=history,
            label=f"observation {step}.1",
            obs=followup_obs,
            stream_file=stream_file,
        )
    if tool not in {"mail.compose", "slack.send_message"}:
        return
    await _auto_tick_after_message_action(
        session,
        step=step,
        transcript=transcript,
        history=history,
        stream_file=stream_file,
        step_timeout_s=step_timeout_s,
    )


async def _auto_tick_after_message_action(
    session: ClientSession,
    *,
    step: int,
    transcript: list[dict],
    history: list[str],
    stream_file: TextIO | None,
    step_timeout_s: int,
) -> None:
    try:
        await _with_timeout(
            call_mcp_tool(session, "vei.tick", {"dt_ms": 20000}),
            step_timeout_s,
            "vei.tick.auto",
        )
        obs_raw = await _with_timeout(
            call_mcp_tool(session, "vei.observe", {}),
            step_timeout_s,
            "vei.observe.post_tick",
        )
        _record_observation(
            transcript=transcript,
            history=history,
            label=f"observation {step}.tick",
            obs=_normalize_result(obs_raw),
            stream_file=stream_file,
        )
    except Exception as exc:
        _append_transcript(
            transcript,
            {"auto_tick_error": f"{type(exc).__name__}: {str(exc)}"},
            stream_file,
        )


async def _run_episode_steps(
    session: ClientSession,
    *,
    config: _EpisodeRunConfig,
    tool_context: _EpisodeToolContext,
    transcript: list[dict],
    history: list[str],
    stream_file: TextIO | None,
    metrics: _EpisodeMetrics,
    started_at: float,
) -> list[dict]:
    planner_state = _EpisodePlannerState()
    for step in range(config.max_steps):
        if time.monotonic() - started_at > config.episode_timeout_s:
            raise TimeoutError(
                f"episode timed out after {config.episode_timeout_s}s at step {step}"
            )
        strict_progress: Dict[str, Any] = {}
        strict_action: Tuple[str, Dict[str, Any]] | None = None
        if config.strict_full_flow:
            strict_progress = _full_flow_progress(transcript)
            if _strict_full_flow_complete(strict_progress):
                break
            strict_action = _strict_full_flow_action(strict_progress)

        obs_raw = await _with_timeout(
            call_mcp_tool(session, "vei.observe", {}),
            config.step_timeout_s,
            "vei.observe",
        )
        obs = _normalize_result(obs_raw)
        if config.interactive:
            obs = await _handle_interactive_step(
                session,
                step=step,
                obs=obs,
                step_timeout_s=config.step_timeout_s,
            )

        _record_observation(
            transcript=transcript,
            history=history,
            label=f"observation {step}",
            obs=obs,
            stream_file=stream_file,
        )
        action_menu = obs.get("action_menu") if isinstance(obs, dict) else None
        typed_action_menu = action_menu if isinstance(action_menu, list) else None
        search_matches = await _collect_search_matches(
            session,
            obs=obs,
            action_menu=typed_action_menu,
            task=config.task,
            planner_state=planner_state,
            tool_top_k=config.tool_top_k,
            tool_catalog=tool_context.tool_catalog,
            step_timeout_s=config.step_timeout_s,
            transcript=transcript,
            stream_file=stream_file,
        )
        visible_tools = _select_visible_tools(
            available=tool_context.tool_names,
            action_menu=typed_action_menu,
            search_matches=search_matches,
            baseline=BASELINE_VISIBLE_TOOLS,
            top_k=config.tool_top_k,
        )
        tool, args, model_tool, model_args = await _plan_episode_action(
            session,
            config=config,
            tool_context=tool_context,
            metrics=metrics,
            history=history,
            obs=obs,
            visible_tools=visible_tools,
            strict_progress=strict_progress,
            strict_action=strict_action,
        )
        tool, args, override_reason = _apply_progress_overrides(
            tool=tool,
            args=args,
            action_menu=typed_action_menu,
            strict_full_flow=config.strict_full_flow,
            strict_action=strict_action,
            model_tool=model_tool,
            model_args=model_args,
            planner_state=planner_state,
        )
        await _execute_episode_action(
            session,
            step=step,
            tool=tool,
            args=args,
            override_reason=override_reason,
            model_tool=model_tool,
            model_args=model_args,
            transcript=transcript,
            history=history,
            stream_file=stream_file,
            step_timeout_s=config.step_timeout_s,
        )
        planner_state.prev_tool = tool
    return transcript


async def run_episode(
    model: str,
    sse_url: str,  # kept for signature compatibility; ignored in stdio mode
    max_steps: int = 12,
    provider: str | None = None,
    engine: str | None = None,  # reserved for future (simonw/llm) path
    openai_base_url: str | None = None,
    openai_api_key: str | None = None,
    anthropic_api_key: str | None = None,
    google_api_key: str | None = None,
    openrouter_api_key: str | None = None,
    task: str | None = None,
    dataset_path: str | None = None,
    artifacts_dir: str | None = None,
    tool_top_k: int = 0,
    interactive: bool = False,
    step_timeout_s: int = 180,
    episode_timeout_s: int = 900,
    strict_full_flow: bool = False,
    transcript_stream_path: str | None = None,
    metrics_path: str | None = None,
) -> list[dict]:
    config = _EpisodeRunConfig(
        model=model,
        max_steps=max_steps,
        provider=provider,
        openai_base_url=openai_base_url,
        openai_api_key=openai_api_key,
        anthropic_api_key=anthropic_api_key,
        google_api_key=google_api_key,
        openrouter_api_key=openrouter_api_key,
        task=task,
        dataset_path=dataset_path,
        artifacts_dir=artifacts_dir,
        tool_top_k=tool_top_k,
        interactive=interactive,
        step_timeout_s=step_timeout_s,
        episode_timeout_s=episode_timeout_s,
        strict_full_flow=strict_full_flow,
        transcript_stream_path=transcript_stream_path,
        metrics_path=metrics_path,
    )
    transcript: list[dict] = []
    history: list[str] = []
    stream_file = _open_transcript_stream(config.transcript_stream_path)
    started_at = time.monotonic()
    metrics = _EpisodeMetrics()
    try:
        params = _build_stdio_server_parameters(
            dataset_path=config.dataset_path,
            artifacts_dir=config.artifacts_dir,
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await _with_timeout(
                    session.initialize(),
                    config.step_timeout_s,
                    "session.initialize",
                )
                tool_context = await _load_episode_tool_context(
                    session,
                    step_timeout_s=config.step_timeout_s,
                    task=config.task,
                    tool_top_k=config.tool_top_k,
                )
                return await _run_episode_steps(
                    session,
                    config=config,
                    tool_context=tool_context,
                    transcript=transcript,
                    history=history,
                    stream_file=stream_file,
                    metrics=metrics,
                    started_at=started_at,
                )
    except Exception as exc:
        _append_transcript(
            transcript,
            {"episode_error": f"{type(exc).__name__}: {str(exc)}"},
            stream_file,
        )
        raise EpisodeFailure(
            f"Episode failed after {len(transcript)} transcript entries: {type(exc).__name__}: {str(exc)}",
            transcript,
        ) from exc
    finally:
        if stream_file is not None:
            stream_file.close()
        metrics.write(
            metrics_path=config.metrics_path,
            model=config.model,
            provider=config.provider,
        )


def _ensure_sse_available(sse_url: str, autostart: bool) -> None:
    def _port_open(host: str, port: int) -> bool:
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            try:
                return s.connect_ex((host, port)) == 0
            except Exception:
                return False

    parsed = urlparse(sse_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 3001
    if _port_open(host, port):
        return
    if not autostart:
        return
    env = os.environ.copy()
    env.setdefault("VEI_HOST", host)
    env.setdefault("VEI_PORT", str(port))
    import sys as _sys

    subprocess.Popen([_sys.executable or "python3", "-m", "vei.router.sse"], env=env)
    for _ in range(20):
        if _port_open(host, port):
            break
        time.sleep(0.1)


_INFRASTRUCTURE_FAILURE_MARKERS = (
    "429",
    "500",
    "502",
    "503",
    "504",
    "connection reset",
    "connection refused",
    "connection aborted",
    "temporarily unavailable",
    "service unavailable",
    "rate limit",
    "timed out",
    "timeout",
    "overloaded",
)


def _is_infrastructure_failure_message(message: str) -> bool:
    lowered = message.lower()
    return any(marker in lowered for marker in _INFRASTRUCTURE_FAILURE_MARKERS)


def _episode_failure_exit_code(exc: EpisodeFailure) -> int:
    cause = exc.__cause__
    if cause is not None and _is_infrastructure_failure_message(str(cause)):
        return 3
    if _is_infrastructure_failure_message(str(exc)):
        return 3
    return 1


@app.command()
def run(
    model: str = typer.Option(
        default_model_for_provider("openai"),
        help="Model id",
    ),
    provider: str = typer.Option(
        "openai", help="Provider: openai|anthropic|google|openrouter|auto"
    ),
    engine: str = typer.Option(
        "sdk", help="Backend engine: sdk (default). 'llm' reserved."
    ),
    openai_base_url: str | None = typer.Option(
        None, help="Override OPENAI_BASE_URL for SDK (OpenAI-compatible)"
    ),
    openai_api_key: str | None = typer.Option(
        None, help="Override OPENAI_API_KEY for SDK"
    ),
    anthropic_api_key: str | None = typer.Option(
        None, help="Override ANTHROPIC_API_KEY for SDK"
    ),
    google_api_key: str | None = typer.Option(
        None, help="Override GOOGLE_API_KEY for SDK"
    ),
    openrouter_api_key: str | None = typer.Option(
        None, help="Override OPENROUTER_API_KEY for SDK"
    ),
    max_steps: int = typer.Option(12, help="Max tool steps"),
    task: str | None = typer.Option(
        None, help="High-level goal for the LLM (prefixed as 'Task: ...')"
    ),
    dataset: Path | None = typer.Option(
        None, help="Optional dataset JSON to prime replay"
    ),
    artifacts: Path | None = typer.Option(
        None, help="Optional artifacts directory for traces"
    ),
    tool_top_k: int = typer.Option(
        0,
        help="If >0, limit prompt-visible tools to top-K retrieved via vei.tools.search (baseline tools always included).",
    ),
    interactive: bool = typer.Option(
        False, help="Run in interactive mode to allow manual event injection."
    ),
    step_timeout_s: int = typer.Option(
        180, help="Per-step timeout for model/tool operations (seconds)."
    ),
    episode_timeout_s: int = typer.Option(
        900, help="Total wall-clock timeout for the episode (seconds)."
    ),
    score_success_mode: str = typer.Option(
        "full",
        help="Score success criteria if --artifacts is set: email|full.",
        show_default=True,
    ),
    require_success: bool = typer.Option(
        False,
        "--require-success/--no-require-success",
        help="Exit non-zero when computed score.success is false.",
    ),
    print_transcript: bool = typer.Option(
        True,
        "--print-transcript/--no-print-transcript",
        help="Print full transcript JSON to stdout.",
    ),
) -> None:
    load_dotenv(override=True)
    eff_provider = auto_provider_for_model(model, provider)
    if eff_provider == "openai" and not (openai_api_key or os.getenv("OPENAI_API_KEY")):
        raise typer.BadParameter(
            "OPENAI_API_KEY not set (provide --openai-api-key or put it in .env)"
        )
    if eff_provider == "anthropic" and not (
        anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")
    ):
        raise typer.BadParameter(
            "ANTHROPIC_API_KEY not set (provide --anthropic-api-key or put it in .env)"
        )
    if eff_provider == "google" and not (
        google_api_key or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    ):
        raise typer.BadParameter(
            "Google API key not set (provide --google-api-key or set GOOGLE_API_KEY/GEMINI_API_KEY in .env)"
        )
    if eff_provider == "openrouter" and not (
        openrouter_api_key or os.getenv("OPENROUTER_API_KEY")
    ):
        raise typer.BadParameter(
            "OPENROUTER_API_KEY not set (provide --openrouter-api-key or put it in .env)"
        )

    mode = score_success_mode.lower().strip()
    if mode not in {"email", "full"}:
        raise typer.BadParameter("score_success_mode must be 'email' or 'full'")

    artifacts_dir: Path | None = None
    transcript_stream_path: Path | None = None
    transcript_json_path: Path | None = None
    score_json_path: Path | None = None
    metrics_json_path: Path | None = None
    summary_json_path: Path | None = None
    if artifacts:
        artifacts_dir = artifacts
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        transcript_stream_path = artifacts_dir / "llm_transcript.jsonl"
        transcript_json_path = artifacts_dir / "transcript.json"
        score_json_path = artifacts_dir / "score.json"
        metrics_json_path = artifacts_dir / "llm_metrics.json"
        summary_json_path = artifacts_dir / "summary.json"

    transcript: list[dict] = []
    run_error: str | None = None
    run_exit_code = 1
    run_error_class: str | None = None
    started_at = time.monotonic()
    try:
        transcript = asyncio.run(
            run_episode(
                model=model,
                sse_url="",  # unused in stdio mode
                max_steps=max_steps,
                provider=provider,
                engine=engine,
                openai_base_url=openai_base_url,
                openai_api_key=openai_api_key,
                anthropic_api_key=anthropic_api_key,
                google_api_key=google_api_key,
                openrouter_api_key=openrouter_api_key,
                task=task,
                dataset_path=str(dataset) if dataset else None,
                artifacts_dir=str(artifacts_dir) if artifacts_dir else None,
                tool_top_k=tool_top_k,
                interactive=interactive,
                step_timeout_s=step_timeout_s,
                episode_timeout_s=episode_timeout_s,
                strict_full_flow=(mode == "full"),
                transcript_stream_path=(
                    str(transcript_stream_path) if transcript_stream_path else None
                ),
                metrics_path=(str(metrics_json_path) if metrics_json_path else None),
            )
        )
    except EpisodeFailure as exc:
        transcript = exc.transcript
        run_error = str(exc)
        run_exit_code = _episode_failure_exit_code(exc)
        run_error_class = (
            "infrastructure" if run_exit_code == 3 else "deterministic_failure"
        )

    elapsed_ms = int((time.monotonic() - started_at) * 1000)
    if transcript_json_path:
        transcript_json_path.write_text(
            json.dumps(transcript, indent=2), encoding="utf-8"
        )

    score_obj: dict[str, Any] | None = None
    if artifacts_dir is not None:
        trace_path = artifacts_dir / "trace.jsonl"
        if trace_path.exists():
            try:
                score_obj = compute_score(artifacts_dir, success_mode=mode)
                if score_json_path:
                    score_json_path.write_text(
                        json.dumps(score_obj, indent=2), encoding="utf-8"
                    )
            except Exception as exc:
                if require_success:
                    run_error = run_error or f"Score computation failed: {str(exc)}"

    summary = {
        "steps": sum(1 for item in transcript if "action" in item),
        "elapsed_ms": elapsed_ms,
        "success": score_obj.get("success") if score_obj else None,
        "run_error": run_error,
        "run_error_class": run_error_class,
        "exit_code": 0 if run_error is None else run_exit_code,
    }
    if metrics_json_path and metrics_json_path.exists():
        metrics_payload = json.loads(metrics_json_path.read_text(encoding="utf-8"))
        summary.update(
            {
                "llm_calls": metrics_payload.get("calls", 0),
                "prompt_tokens": metrics_payload.get("prompt_tokens", 0),
                "completion_tokens": metrics_payload.get("completion_tokens", 0),
                "total_tokens": metrics_payload.get("total_tokens", 0),
                "estimated_cost_usd": metrics_payload.get("estimated_cost_usd"),
                "llm_latency_p95_ms": metrics_payload.get("latency_p95_ms", 0),
            }
        )
    if summary_json_path:
        summary_json_path.write_text(
            json.dumps({"summary": summary}, indent=2),
            encoding="utf-8",
        )

    if run_error:
        typer.echo(run_error, err=True)
        typer.echo(json.dumps({"summary": summary}, indent=2), err=True)
        if print_transcript:
            typer.echo(json.dumps(transcript, indent=2))
        raise typer.Exit(code=run_exit_code)

    if require_success:
        if score_obj is None:
            typer.echo(
                "--require-success was set but no score could be computed from artifacts.",
                err=True,
            )
            typer.echo(json.dumps({"summary": summary}, indent=2), err=True)
            raise typer.Exit(code=1)
        if not bool(score_obj.get("success")):
            typer.echo(
                "Run completed but score.success=false under --require-success.",
                err=True,
            )
            typer.echo(json.dumps({"summary": summary}, indent=2), err=True)
            typer.echo(json.dumps(score_obj, indent=2), err=True)
            raise typer.Exit(code=1)

    typer.echo(json.dumps({"summary": summary}, indent=2), err=True)
    if print_transcript:
        typer.echo(json.dumps(transcript, indent=2))


if __name__ == "__main__":
    app()
