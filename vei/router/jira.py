from __future__ import annotations

from typing import Any, Dict, List

from .errors import MCPError
from .tickets import TicketsSim
from .tool_providers import PrefixToolProvider
from .tool_registry import ToolSpec


class JiraToolProvider(PrefixToolProvider):
    """Thin Jira-style facade over the tickets twin."""

    def __init__(self, tickets: TicketsSim):
        super().__init__("jira", prefixes=("jira.",))
        self.tickets = tickets
        self._specs: List[ToolSpec] = [
            ToolSpec(
                name="jira.list_issues",
                description="List Jira-style issues.",
                permissions=("jira:read",),
                default_latency_ms=250,
                latency_jitter_ms=70,
            ),
            ToolSpec(
                name="jira.get_issue",
                description="Fetch a Jira-style issue by id.",
                permissions=("jira:read",),
                default_latency_ms=220,
                latency_jitter_ms=60,
            ),
            ToolSpec(
                name="jira.create_issue",
                description="Create a Jira-style issue.",
                permissions=("jira:write",),
                side_effects=("jira_mutation",),
                default_latency_ms=320,
                latency_jitter_ms=100,
            ),
            ToolSpec(
                name="jira.update_issue",
                description="Update a Jira-style issue.",
                permissions=("jira:write",),
                side_effects=("jira_mutation",),
                default_latency_ms=320,
                latency_jitter_ms=100,
            ),
            ToolSpec(
                name="jira.transition_issue",
                description="Transition a Jira-style issue to a new status.",
                permissions=("jira:write",),
                side_effects=("jira_mutation",),
                default_latency_ms=320,
                latency_jitter_ms=100,
            ),
            ToolSpec(
                name="jira.add_comment",
                description="Add a comment to a Jira-style issue.",
                permissions=("jira:write",),
                side_effects=("jira_mutation",),
                default_latency_ms=310,
                latency_jitter_ms=90,
            ),
        ]

    def specs(self) -> List[ToolSpec]:
        return list(self._specs)

    def call(self, tool: str, args: Dict[str, Any]) -> Any:
        if tool == "jira.list_issues":
            payload = self.tickets.list(**args)
            if isinstance(payload, list):
                return [_ticket_to_issue(item) for item in payload]
            rows = payload.get("tickets", [])
            return {
                "issues": [_ticket_to_issue(item) for item in rows],
                "count": payload.get("count", len(rows)),
                "total": payload.get("total", len(rows)),
                "next_cursor": payload.get("next_cursor"),
                "has_more": payload.get("has_more", False),
            }
        if tool == "jira.get_issue":
            issue_id = _required_issue_id(args)
            return _ticket_to_issue(self.tickets.get(ticket_id=issue_id))
        if tool == "jira.create_issue":
            return _rename_issue_id(self.tickets.create(**args))
        if tool == "jira.update_issue":
            payload = dict(args or {})
            issue_id = _required_issue_id(payload)
            payload["ticket_id"] = issue_id
            payload.pop("issue_id", None)
            return _rename_issue_id(self.tickets.update(**payload))
        if tool == "jira.transition_issue":
            payload = dict(args or {})
            issue_id = _required_issue_id(payload)
            status = payload.get("status")
            if not isinstance(status, str):
                raise MCPError("invalid_args", "transition_issue requires status")
            return _rename_issue_id(
                self.tickets.transition(ticket_id=issue_id, status=status)
            )
        if tool == "jira.add_comment":
            payload = dict(args or {})
            issue_id = _required_issue_id(payload)
            body = payload.get("body")
            author = payload.get("author")
            if not isinstance(body, str):
                raise MCPError("invalid_args", "add_comment requires body")
            return _rename_issue_id(
                self.tickets.add_comment(ticket_id=issue_id, body=body, author=author)
            )
        raise MCPError("unknown_tool", f"No such tool: {tool}")


def _required_issue_id(args: Dict[str, Any]) -> str:
    issue_id = args.get("issue_id") or args.get("ticket_id")
    if not isinstance(issue_id, str) or not issue_id:
        raise MCPError("invalid_args", "issue_id is required")
    return issue_id


def _rename_issue_id(payload: Dict[str, Any]) -> Dict[str, Any]:
    issue = dict(payload)
    if "ticket_id" in issue and "issue_id" not in issue:
        issue["issue_id"] = issue.pop("ticket_id")
    return issue


def _ticket_to_issue(payload: Dict[str, Any]) -> Dict[str, Any]:
    issue = dict(payload)
    if "ticket_id" in issue and "issue_id" not in issue:
        issue["issue_id"] = issue.pop("ticket_id")
    return issue
