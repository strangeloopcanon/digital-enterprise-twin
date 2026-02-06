from __future__ import annotations

import json
import time
from typing import Any, Callable, Dict, Mapping, Optional

from .api import AdapterTriplet, ConnectorAdapter
from .models import (
    ConnectorError,
    ConnectorRequest,
    ConnectorResult,
    ServiceName,
)

Handler = Callable[..., Any]
CanonicalBuilder = Callable[[ConnectorRequest, Any], Dict[str, Any]]


def _request_key(request: ConnectorRequest) -> str:
    payload = json.dumps(request.payload, sort_keys=True, separators=(",", ":"))
    return f"{request.service.value}:{request.operation}:{payload}"


class SimConnectorAdapter(ConnectorAdapter):
    def __init__(
        self,
        *,
        service: ServiceName,
        handlers: Mapping[str, Handler],
        canonical_builder: CanonicalBuilder,
    ) -> None:
        self.service = service
        self.handlers = dict(handlers)
        self._canonical_builder = canonical_builder

    def execute(self, request: ConnectorRequest) -> ConnectorResult:
        started = time.perf_counter()
        handler = self.handlers.get(request.operation)
        if not handler:
            return ConnectorResult(
                ok=False,
                status_code=404,
                error=ConnectorError(
                    code="unknown_operation",
                    message=f"Unsupported operation for {self.service.value}: {request.operation}",
                ),
            )
        try:
            response = handler(**request.payload)
            latency_ms = int((time.perf_counter() - started) * 1000)
            raw = self._canonical_builder(request, response)
            data = _to_legacy_shape(request, response)
            return ConnectorResult(
                ok=True,
                status_code=200,
                data=data,
                raw=raw,
                latency_ms=latency_ms,
                metadata={"adapter": "sim"},
            )
        except Exception as exc:  # noqa: BLE001
            latency_ms = int((time.perf_counter() - started) * 1000)
            error_code = getattr(exc, "code", f"{self.service.value}.operation_failed")
            error_message = getattr(exc, "message", str(exc))
            return ConnectorResult(
                ok=False,
                status_code=400,
                error=ConnectorError(
                    code=str(error_code),
                    message=str(error_message),
                ),
                latency_ms=latency_ms,
                metadata={"adapter": "sim"},
            )


class ReplayConnectorAdapter(ConnectorAdapter):
    """Deterministic replay adapter with memoized request->response behavior."""

    def __init__(self, delegate: ConnectorAdapter) -> None:
        self.delegate = delegate
        self._memo: Dict[str, ConnectorResult] = {}

    def execute(self, request: ConnectorRequest) -> ConnectorResult:
        key = _request_key(request)
        cached = self._memo.get(key)
        if cached:
            out = cached.model_copy(deep=True)
            out.metadata = {**out.metadata, "adapter": "replay", "cache_hit": True}
            return out
        result = self.delegate.execute(request)
        self._memo[key] = result.model_copy(deep=True)
        out = result.model_copy(deep=True)
        out.metadata = {**out.metadata, "adapter": "replay", "cache_hit": False}
        return out


class LiveConnectorAdapter(ConnectorAdapter):
    """Live adapter shell; delegates to sim behavior unless a real backend is added."""

    def __init__(self, delegate: ConnectorAdapter) -> None:
        self.delegate = delegate

    def execute(self, request: ConnectorRequest) -> ConnectorResult:
        result = self.delegate.execute(request)
        result.metadata = {
            **result.metadata,
            "adapter": "live",
            "live_backend": "simulated",
        }
        result.raw = {
            **result.raw,
            "live_backend": "simulated",
        }
        return result


def build_default_adapter_triplets(
    *,
    slack: Any,
    mail: Any,
    calendar: Any,
    docs: Any,
    tickets: Any,
    database: Any,
    erp: Optional[Any] = None,
    crm: Optional[Any] = None,
    okta: Optional[Any] = None,
    servicedesk: Optional[Any] = None,
) -> Dict[ServiceName, AdapterTriplet]:
    slack_sim = SimConnectorAdapter(
        service=ServiceName.SLACK,
        handlers={
            "list_channels": slack.list_channels,
            "open_channel": slack.open_channel,
            "send_message": slack.send_message,
            "react": slack.react,
            "fetch_thread": slack.fetch_thread,
        },
        canonical_builder=_slack_canonical,
    )
    mail_sim = SimConnectorAdapter(
        service=ServiceName.MAIL,
        handlers={
            "list": mail.list,
            "open": mail.open,
            "compose": mail.compose,
            "reply": mail.reply,
        },
        canonical_builder=_mail_canonical,
    )
    calendar_sim = SimConnectorAdapter(
        service=ServiceName.CALENDAR,
        handlers={
            "list_events": calendar.list_events,
            "create_event": calendar.create_event,
            "accept": calendar.accept,
            "decline": calendar.decline,
            "update_event": calendar.update_event,
            "cancel_event": calendar.cancel_event,
        },
        canonical_builder=_calendar_canonical,
    )
    docs_sim = SimConnectorAdapter(
        service=ServiceName.DOCS,
        handlers={
            "list": docs.list,
            "read": docs.read,
            "search": docs.search,
            "create": docs.create,
            "update": docs.update,
        },
        canonical_builder=_docs_canonical,
    )
    tickets_sim = SimConnectorAdapter(
        service=ServiceName.TICKETS,
        handlers={
            "list": tickets.list,
            "get": tickets.get,
            "create": tickets.create,
            "update": tickets.update,
            "transition": tickets.transition,
            "add_comment": tickets.add_comment,
        },
        canonical_builder=_tickets_canonical,
    )
    db_sim = SimConnectorAdapter(
        service=ServiceName.DB,
        handlers={
            "list_tables": database.list_tables,
            "describe_table": database.describe_table,
            "query": database.query,
            "upsert": database.upsert,
        },
        canonical_builder=_db_canonical,
    )
    erp_sim: Optional[SimConnectorAdapter] = None
    if erp is not None:
        erp_sim = SimConnectorAdapter(
            service=ServiceName.ERP,
            handlers={
                "create_po": erp.create_po,
                "get_po": erp.get_po,
                "list_pos": erp.list_pos,
                "receive_goods": erp.receive_goods,
                "submit_invoice": erp.submit_invoice,
                "get_invoice": erp.get_invoice,
                "list_invoices": erp.list_invoices,
                "match_three_way": erp.match_three_way,
                "post_payment": erp.post_payment,
            },
            canonical_builder=_erp_canonical,
        )
    crm_sim: Optional[SimConnectorAdapter] = None
    if crm is not None:
        crm_sim = SimConnectorAdapter(
            service=ServiceName.CRM,
            handlers={
                "create_contact": crm.create_contact,
                "get_contact": crm.get_contact,
                "list_contacts": crm.list_contacts,
                "create_company": crm.create_company,
                "get_company": crm.get_company,
                "list_companies": crm.list_companies,
                "associate_contact_company": crm.associate_contact_company,
                "create_deal": crm.create_deal,
                "get_deal": crm.get_deal,
                "list_deals": crm.list_deals,
                "update_deal_stage": crm.update_deal_stage,
                "log_activity": crm.log_activity,
            },
            canonical_builder=_crm_canonical,
        )
    okta_sim: Optional[SimConnectorAdapter] = None
    if okta is not None:
        okta_sim = SimConnectorAdapter(
            service=ServiceName.OKTA,
            handlers={
                "list_users": okta.list_users,
                "get_user": okta.get_user,
                "activate_user": okta.activate_user,
                "deactivate_user": okta.deactivate_user,
                "suspend_user": okta.suspend_user,
                "unsuspend_user": okta.unsuspend_user,
                "reset_password": okta.reset_password,
                "list_groups": okta.list_groups,
                "assign_group": okta.assign_group,
                "unassign_group": okta.unassign_group,
                "list_applications": okta.list_applications,
                "assign_application": okta.assign_application,
                "unassign_application": okta.unassign_application,
            },
            canonical_builder=_okta_canonical,
        )
    servicedesk_sim: Optional[SimConnectorAdapter] = None
    if servicedesk is not None:
        servicedesk_sim = SimConnectorAdapter(
            service=ServiceName.SERVICEDESK,
            handlers={
                "list_incidents": servicedesk.list_incidents,
                "get_incident": servicedesk.get_incident,
                "update_incident": servicedesk.update_incident,
                "list_requests": servicedesk.list_requests,
                "get_request": servicedesk.get_request,
                "update_request": servicedesk.update_request,
            },
            canonical_builder=_servicedesk_canonical,
        )

    def _triplet(sim: ConnectorAdapter) -> AdapterTriplet:
        return AdapterTriplet(
            sim=sim,
            replay=ReplayConnectorAdapter(sim),
            live=LiveConnectorAdapter(sim),
        )

    triplets = {
        ServiceName.SLACK: _triplet(slack_sim),
        ServiceName.MAIL: _triplet(mail_sim),
        ServiceName.CALENDAR: _triplet(calendar_sim),
        ServiceName.DOCS: _triplet(docs_sim),
        ServiceName.TICKETS: _triplet(tickets_sim),
        ServiceName.DB: _triplet(db_sim),
    }
    if erp_sim is not None:
        triplets[ServiceName.ERP] = _triplet(erp_sim)
    if crm_sim is not None:
        triplets[ServiceName.CRM] = _triplet(crm_sim)
    if okta_sim is not None:
        triplets[ServiceName.OKTA] = _triplet(okta_sim)
    if servicedesk_sim is not None:
        triplets[ServiceName.SERVICEDESK] = _triplet(servicedesk_sim)
    return triplets


def _to_legacy_shape(request: ConnectorRequest, response: Any) -> Any:
    # Preserve existing router contract for compatibility with current tests/clients.
    if request.service == ServiceName.MAIL and request.operation == "list":
        if isinstance(response, list):
            return response
    if request.service == ServiceName.DOCS and request.operation in {
        "list",
        "search",
    }:
        if isinstance(response, list):
            return response
    if request.service == ServiceName.CALENDAR and request.operation == "list_events":
        if isinstance(response, list):
            return response
    if request.service == ServiceName.TICKETS and request.operation == "list":
        if isinstance(response, list):
            return response
    if request.service == ServiceName.SLACK and request.operation == "list_channels":
        if isinstance(response, list):
            return response
    if request.service == ServiceName.DB and request.operation == "list_tables":
        if isinstance(response, list):
            return response
    if isinstance(response, dict):
        return dict(response)
    return response


def _slack_canonical(request: ConnectorRequest, response: Any) -> Dict[str, Any]:
    channel = request.payload.get("channel")
    if request.operation == "list_channels" and isinstance(response, list):
        return {
            "ok": True,
            "channels": [
                {
                    "id": channel_name,
                    "name": str(channel_name).lstrip("#"),
                    "is_channel": True,
                }
                for channel_name in response
            ],
        }
    if request.operation == "send_message" and isinstance(response, dict):
        return {
            "ok": True,
            "channel": channel,
            "ts": response.get("ts"),
            "message": {
                "text": request.payload.get("text"),
                "thread_ts": request.payload.get("thread_ts"),
            },
        }
    return {
        "ok": True,
        "channel": channel,
        "result": response,
    }


def _mail_canonical(request: ConnectorRequest, response: Any) -> Dict[str, Any]:
    if request.operation == "list" and isinstance(response, list):
        return {
            "ok": True,
            "folder": request.payload.get("folder", "INBOX"),
            "messages": response,
            "count": len(response),
        }
    if request.operation in {"compose", "reply"} and isinstance(response, dict):
        return {
            "ok": True,
            "id": response.get("id"),
            "to": request.payload.get("to"),
            "subject": request.payload.get("subj"),
            "queued": True,
        }
    return {"ok": True, "result": response}


def _calendar_canonical(request: ConnectorRequest, response: Any) -> Dict[str, Any]:
    if request.operation == "list_events" and isinstance(response, list):
        return {"ok": True, "events": response, "count": len(response)}
    if request.operation == "list_events" and isinstance(response, dict):
        return {
            "ok": True,
            "events": response.get("events", []),
            "count": response.get("count", 0),
            "total": response.get("total", response.get("count", 0)),
            "next_cursor": response.get("next_cursor"),
            "has_more": response.get("has_more", False),
        }
    return {"ok": True, "result": response}


def _docs_canonical(request: ConnectorRequest, response: Any) -> Dict[str, Any]:
    if request.operation == "list" and isinstance(response, list):
        return {"ok": True, "documents": response, "count": len(response)}
    if request.operation == "list" and isinstance(response, dict):
        return {
            "ok": True,
            "documents": response.get("documents", []),
            "count": response.get("count", 0),
            "total": response.get("total", response.get("count", 0)),
            "next_cursor": response.get("next_cursor"),
            "has_more": response.get("has_more", False),
        }
    if request.operation == "search" and isinstance(response, list):
        return {
            "ok": True,
            "query": request.payload.get("query"),
            "hits": response,
            "count": len(response),
        }
    if request.operation == "search" and isinstance(response, dict):
        return {
            "ok": True,
            "query": request.payload.get("query"),
            "hits": response.get("documents", []),
            "count": response.get("count", 0),
            "total": response.get("total", response.get("count", 0)),
            "next_cursor": response.get("next_cursor"),
            "has_more": response.get("has_more", False),
        }
    if request.operation == "read" and isinstance(response, dict):
        return {"ok": True, "document": response}
    return {"ok": True, "result": response}


def _tickets_canonical(request: ConnectorRequest, response: Any) -> Dict[str, Any]:
    if request.operation == "list" and isinstance(response, list):
        return {"ok": True, "tickets": response, "count": len(response)}
    if request.operation == "list" and isinstance(response, dict):
        return {
            "ok": True,
            "tickets": response.get("tickets", []),
            "count": response.get("count", 0),
            "total": response.get("total", response.get("count", 0)),
            "next_cursor": response.get("next_cursor"),
            "has_more": response.get("has_more", False),
        }
    if request.operation == "get" and isinstance(response, dict):
        return {"ok": True, "ticket": response}
    return {"ok": True, "result": response}


def _db_canonical(request: ConnectorRequest, response: Any) -> Dict[str, Any]:
    if request.operation == "list_tables" and isinstance(response, list):
        return {"ok": True, "tables": response, "count": len(response)}
    if request.operation == "list_tables" and isinstance(response, dict):
        return {
            "ok": True,
            "tables": response.get("tables", []),
            "count": response.get("count", 0),
            "total": response.get("total", response.get("count", 0)),
            "next_cursor": response.get("next_cursor"),
            "has_more": response.get("has_more", False),
        }
    if request.operation == "query" and isinstance(response, dict):
        return {
            "ok": True,
            "table": request.payload.get("table"),
            "rows": response.get("rows", []),
            "count": response.get("count", 0),
            "total": response.get("total", response.get("count", 0)),
            "next_cursor": response.get("next_cursor"),
            "has_more": response.get("has_more", False),
        }
    return {"ok": True, "result": response}


def _erp_canonical(request: ConnectorRequest, response: Any) -> Dict[str, Any]:
    if request.operation == "list_pos" and isinstance(response, list):
        return {"ok": True, "purchase_orders": response, "count": len(response)}
    if request.operation == "list_pos" and isinstance(response, dict):
        return {
            "ok": True,
            "purchase_orders": response.get("purchase_orders", []),
            "count": response.get("count", 0),
            "total": response.get("total", response.get("count", 0)),
            "next_cursor": response.get("next_cursor"),
            "has_more": response.get("has_more", False),
        }
    if request.operation == "list_invoices" and isinstance(response, list):
        return {"ok": True, "invoices": response, "count": len(response)}
    if request.operation == "list_invoices" and isinstance(response, dict):
        return {
            "ok": True,
            "invoices": response.get("invoices", []),
            "count": response.get("count", 0),
            "total": response.get("total", response.get("count", 0)),
            "next_cursor": response.get("next_cursor"),
            "has_more": response.get("has_more", False),
        }
    return {"ok": True, "result": response}


def _crm_canonical(request: ConnectorRequest, response: Any) -> Dict[str, Any]:
    if request.operation == "list_contacts" and isinstance(response, list):
        return {"ok": True, "contacts": response, "count": len(response)}
    if request.operation == "list_contacts" and isinstance(response, dict):
        return {
            "ok": True,
            "contacts": response.get("contacts", []),
            "count": response.get("count", 0),
            "total": response.get("total", response.get("count", 0)),
            "next_cursor": response.get("next_cursor"),
            "has_more": response.get("has_more", False),
        }
    if request.operation == "list_companies" and isinstance(response, list):
        return {"ok": True, "companies": response, "count": len(response)}
    if request.operation == "list_companies" and isinstance(response, dict):
        return {
            "ok": True,
            "companies": response.get("companies", []),
            "count": response.get("count", 0),
            "total": response.get("total", response.get("count", 0)),
            "next_cursor": response.get("next_cursor"),
            "has_more": response.get("has_more", False),
        }
    if request.operation == "list_deals" and isinstance(response, list):
        return {"ok": True, "deals": response, "count": len(response)}
    if request.operation == "list_deals" and isinstance(response, dict):
        return {
            "ok": True,
            "deals": response.get("deals", []),
            "count": response.get("count", 0),
            "total": response.get("total", response.get("count", 0)),
            "next_cursor": response.get("next_cursor"),
            "has_more": response.get("has_more", False),
        }
    return {"ok": True, "result": response}


def _okta_canonical(request: ConnectorRequest, response: Any) -> Dict[str, Any]:
    if request.operation.startswith("list_") and isinstance(response, dict):
        return {"ok": True, **response}
    if request.operation == "get_user" and isinstance(response, dict):
        return {"ok": True, "user": response}
    return {"ok": True, "result": response}


def _servicedesk_canonical(request: ConnectorRequest, response: Any) -> Dict[str, Any]:
    if request.operation in {"list_incidents", "list_requests"} and isinstance(
        response, dict
    ):
        return {"ok": True, **response}
    return {"ok": True, "result": response}
