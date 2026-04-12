"""LLM-assisted blueprint generation from natural language.

Takes a free-text prompt describing a company, its tools, and a scenario,
then uses structured LLM output to produce a draft BlueprintAsset.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from vei.project_settings import resolve_llm_defaults
from vei.blueprint.models import (
    BlueprintAsset,
    BlueprintCapabilityGraphsAsset,
    BlueprintCommGraphAsset,
    BlueprintDocGraphAsset,
    BlueprintDocumentAsset,
    BlueprintIdentityGraphAsset,
    BlueprintIdentityUserAsset,
    BlueprintMailMessageAsset,
    BlueprintMailThreadAsset,
    BlueprintSlackChannelAsset,
    BlueprintSlackMessageAsset,
    BlueprintTicketAsset,
    BlueprintWorkGraphAsset,
)

_SYSTEM_PROMPT = """\
You are a VEI (Virtual Enterprise Intelligence) blueprint author. Your job is
to generate a realistic enterprise simulation scenario as a structured JSON
object.

The JSON must have this exact shape:
{
  "company_name": "string",
  "domain": "string (e.g. acmecorp.com)",
  "industry": "string",
  "scenario_name": "string (snake_case slug)",
  "scenario_description": "string (2-3 sentences)",
  "surfaces_used": ["slack", "mail", "tickets", "docs", "identity", "crm"],
  "actors": [
    {"name": "string", "email": "string", "role": "string", "department": "string"}
  ],
  "slack_channels": [
    {"name": "#channel", "messages": [{"user": "email", "text": "string"}]}
  ],
  "mail_threads": [
    {"id": "string", "subject": "string", "messages": [
      {"from": "email", "to": "email", "subject": "string", "body": "string"}
    ]}
  ],
  "tickets": [
    {"id": "string", "title": "string", "status": "open|in_progress|resolved", "assignee": "email", "description": "string"}
  ],
  "documents": [
    {"id": "string", "title": "string", "body": "string", "tags": ["string"]}
  ],
  "causal_links": [
    {"source_tool": "surface.action", "target_tool": "surface.action", "description": "string"}
  ],
  "success_predicates": [
    {"name": "string", "description": "string"}
  ],
  "forbidden_predicates": [
    {"name": "string", "description": "string"}
  ]
}

Guidelines:
- Generate 3-6 actors with realistic names and roles
- Create 2-4 Slack channels with 2-3 messages each
- Create 1-3 mail threads with 1-2 messages each
- Create 3-6 tickets reflecting the scenario
- Create 1-3 documents (policies, runbooks, specs)
- Define 2-5 causal links showing cross-system effects
- Define 2-4 success predicates and 1-2 forbidden predicates
- Make everything internally consistent (same people, same project names)
- Use the company domain for all email addresses

Return ONLY the JSON object, no markdown fences, no commentary.
"""


def generate_blueprint_from_prompt(
    prompt: str,
    *,
    provider: str = "openai",
    model: str | None = None,
) -> BlueprintAsset:
    """Generate a BlueprintAsset from a natural language description.

    Uses the configured LLM provider to produce structured scenario data,
    then maps it into a proper BlueprintAsset.
    """
    resolved_provider, resolved_model = resolve_llm_defaults(
        provider=provider,
        model=model,
    )
    raw = _call_llm(prompt, provider=resolved_provider, model=resolved_model)
    return _raw_to_blueprint(raw)


def _call_llm(
    prompt: str,
    *,
    provider: str,
    model: str,
) -> dict[str, Any]:
    from vei.llm.providers import plan_once

    result = asyncio.run(
        plan_once(
            provider=provider,
            model=model,
            system=_SYSTEM_PROMPT,
            user=prompt,
        )
    )
    if isinstance(result, dict):
        return result
    return json.loads(str(result))


def _raw_to_blueprint(raw: dict[str, Any]) -> BlueprintAsset:
    """Convert LLM output into a proper BlueprintAsset."""
    company = raw.get("company_name", "Generated Company")
    domain = raw.get("domain", "example.com")
    scenario = raw.get("scenario_name", "generated_scenario")
    description = raw.get("scenario_description", "")
    slug = scenario.replace("-", "_").replace(" ", "_").lower()

    actors = raw.get("actors", [])
    slack_channels_raw = raw.get("slack_channels", [])
    mail_threads_raw = raw.get("mail_threads", [])
    tickets_raw = raw.get("tickets", [])
    documents_raw = raw.get("documents", [])

    # --- Comm graph ---
    slack_channels = []
    for ch in slack_channels_raw:
        name = ch.get("name", "#general")
        if not name.startswith("#"):
            name = f"#{name}"
        messages = []
        for i, msg in enumerate(ch.get("messages", [])):
            messages.append(
                BlueprintSlackMessageAsset(
                    ts=f"1700000{i:03d}.000000",
                    user=str(msg.get("user", "unknown")),
                    text=str(msg.get("text", "")),
                )
            )
        slack_channels.append(
            BlueprintSlackChannelAsset(channel=name, messages=messages)
        )

    mail_threads = []
    for mt in mail_threads_raw:
        messages = []
        for msg in mt.get("messages", []):
            messages.append(
                BlueprintMailMessageAsset(
                    from_address=str(msg.get("from", f"ops@{domain}")),
                    to_address=str(msg.get("to", f"team@{domain}")),
                    subject=str(msg.get("subject", mt.get("subject", ""))),
                    body_text=str(msg.get("body", "")),
                    unread=True,
                )
            )
        mail_threads.append(
            BlueprintMailThreadAsset(
                thread_id=str(mt.get("id", f"MT-{len(mail_threads) + 1}")),
                title=mt.get("subject", ""),
                messages=messages,
            )
        )

    comm_graph = BlueprintCommGraphAsset(
        slack_channels=slack_channels,
        mail_threads=mail_threads,
    )

    # --- Doc graph ---
    documents = []
    for doc in documents_raw:
        documents.append(
            BlueprintDocumentAsset(
                doc_id=str(doc.get("id", f"DOC-{len(documents) + 1}")),
                title=str(doc.get("title", "Untitled")),
                body=str(doc.get("body", "")),
                tags=doc.get("tags", []),
            )
        )
    doc_graph = BlueprintDocGraphAsset(documents=documents) if documents else None

    # --- Work graph ---
    tickets = []
    for tk in tickets_raw:
        tickets.append(
            BlueprintTicketAsset(
                ticket_id=str(tk.get("id", f"TK-{len(tickets) + 1}")),
                title=str(tk.get("title", "Untitled")),
                status=str(tk.get("status", "open")),
                assignee=tk.get("assignee"),
                description=tk.get("description"),
            )
        )
    work_graph = BlueprintWorkGraphAsset(tickets=tickets) if tickets else None

    # --- Identity graph ---
    users = []
    for actor in actors:
        email = actor.get("email", f"{actor.get('name', 'user')}@{domain}")
        name_parts = str(actor.get("name", "User")).split()
        first = name_parts[0] if name_parts else "User"
        last = name_parts[-1] if len(name_parts) > 1 else ""
        users.append(
            BlueprintIdentityUserAsset(
                user_id=f"USR-{len(users) + 1:03d}",
                email=email,
                first_name=first,
                last_name=last,
                display_name=str(actor.get("name", "")),
                login=email,
                department=actor.get("department", ""),
                title=actor.get("role", ""),
                groups=[],
                applications=[],
                factors=["password"],
            )
        )
    identity_graph = BlueprintIdentityGraphAsset(users=users) if users else None

    capability_graphs = BlueprintCapabilityGraphsAsset(
        organization_name=company,
        organization_domain=domain,
        comm_graph=comm_graph,
        doc_graph=doc_graph,
        work_graph=work_graph,
        identity_graph=identity_graph,
    )

    facades = list(raw.get("surfaces_used", ["slack", "mail", "tickets", "docs"]))

    causal_links = raw.get("causal_links", [])
    success_preds = raw.get("success_predicates", [])
    forbidden_preds = raw.get("forbidden_predicates", [])

    asset = BlueprintAsset(
        name=f"{slug}.generated.blueprint",
        title=company,
        description=description,
        scenario_name=slug,
        workflow_name=slug,
        requested_facades=facades,
        capability_graphs=capability_graphs,
        metadata={
            "generated_by": "llm",
            "causal_links": causal_links,
            "success_predicates": [p.get("name", "") for p in success_preds],
            "forbidden_predicates": [p.get("name", "") for p in forbidden_preds],
            "predicate_details": {
                "success": success_preds,
                "forbidden": forbidden_preds,
            },
        },
    )
    return asset
