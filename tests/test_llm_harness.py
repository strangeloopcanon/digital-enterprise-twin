from __future__ import annotations

from vei.cli.vei_llm_test import (
    _full_flow_progress,
    _normalize_result,
    _select_progress_action,
    _strict_full_flow_action,
    _strict_full_flow_complete,
)


class _FakeResult:
    def model_dump(self) -> dict:
        return {
            "structuredContent": None,
            "content": [
                {"type": "text", "text": '{"result": {"id": "D-1"}, "ok": true}'}
            ],
            "isError": False,
        }


def test_normalize_result_parses_text_json_payload() -> None:
    normalized = _normalize_result(_FakeResult())
    assert normalized == {"result": {"id": "D-1"}, "ok": True}


def test_select_progress_action_prefers_non_observe_with_args() -> None:
    action_menu = [
        {"tool": "vei.observe", "args": {}},
        {"tool": "browser.click", "args": {"node_id": "CLICK:open_pdp#0"}},
        {"tool": "mail.list", "args": {}},
    ]
    tool, args = _select_progress_action(action_menu) or ("", {})
    assert tool == "browser.click"
    assert args == {"node_id": "CLICK:open_pdp#0"}


def test_strict_full_flow_action_advances_missing_enterprise_steps() -> None:
    transcript = [
        {"action": {"tool": "browser.read", "args": {}, "result": {"url": "u"}}},
        {
            "action": {
                "tool": "slack.send_message",
                "args": {"text": "Budget $2999 approved"},
                "result": {"ts": "1"},
            }
        },
        {
            "action": {
                "tool": "mail.compose",
                "args": {"to": "sales@macrocompute.example"},
                "result": {"id": "m1"},
            }
        },
        {
            "action": {
                "tool": "mail.open",
                "args": {"id": "m2"},
                "result": {
                    "body_text": "Quote is $2999 and ETA is 5 business days.",
                },
            }
        },
    ]
    progress = _full_flow_progress(transcript)
    action = _strict_full_flow_action(progress)
    assert action is not None
    assert action[0] == "docs.create"


def test_strict_full_flow_action_uses_discovered_ids_for_ticket_and_crm() -> None:
    transcript = [
        {"action": {"tool": "browser.read", "args": {}, "result": {"url": "u"}}},
        {
            "action": {
                "tool": "slack.send_message",
                "args": {"text": "Budget $2999 approved"},
                "result": {"ts": "1"},
            }
        },
        {
            "action": {
                "tool": "mail.compose",
                "args": {"to": "sales@macrocompute.example"},
                "result": {"id": "m1"},
            }
        },
        {
            "action": {
                "tool": "mail.open",
                "args": {"id": "m2"},
                "result": {"body_text": "Price $2999 ETA 5 days"},
            }
        },
        {"action": {"tool": "docs.create", "args": {}, "result": {"doc_id": "D-1"}}},
        {
            "action": {
                "tool": "tickets.list",
                "args": {},
                "result": {"tickets": [{"ticket_id": "TCK-77"}]},
            }
        },
    ]
    progress = _full_flow_progress(transcript)
    ticket_action = _strict_full_flow_action(progress)
    assert ticket_action is not None
    assert ticket_action[0] == "tickets.update"
    assert ticket_action[1]["ticket_id"] == "TCK-77"

    transcript.append(
        {
            "action": {
                "tool": "tickets.update",
                "args": {"ticket_id": "TCK-77"},
                "result": {"ok": True},
            }
        }
    )
    transcript.append(
        {
            "action": {
                "tool": "crm.list_deals",
                "args": {},
                "result": {"deals": [{"id": "D-301"}]},
            }
        }
    )
    progress = _full_flow_progress(transcript)
    crm_action = _strict_full_flow_action(progress)
    assert crm_action is not None
    assert crm_action[0] == "crm.log_activity"
    assert crm_action[1]["deal_id"] == "D-301"


def test_strict_full_flow_action_uses_default_ids_when_missing() -> None:
    transcript = [
        {"action": {"tool": "browser.read", "args": {}, "result": {"url": "u"}}},
        {
            "action": {
                "tool": "slack.send_message",
                "args": {"text": "Budget $2999 approved"},
                "result": {"ts": "1"},
            }
        },
        {
            "action": {
                "tool": "mail.compose",
                "args": {"to": "sales@macrocompute.example"},
                "result": {"id": "m1"},
            }
        },
        {
            "action": {
                "tool": "mail.open",
                "args": {"id": "m2"},
                "result": {"body_text": "Price $2999 ETA 5 days"},
            }
        },
        {"action": {"tool": "docs.create", "args": {}, "result": {"doc_id": "D-1"}}},
    ]
    progress = _full_flow_progress(transcript)
    ticket_action = _strict_full_flow_action(progress)
    assert ticket_action is not None
    assert ticket_action[0] == "tickets.create"

    transcript.append(
        {
            "action": {
                "tool": "tickets.create",
                "args": {"title": "Quote follow-up"},
                "result": {"ticket_id": "TCK-88"},
            }
        }
    )
    progress = _full_flow_progress(transcript)
    ticket_update_action = _strict_full_flow_action(progress)
    assert ticket_update_action is not None
    assert ticket_update_action[0] == "tickets.update"
    assert ticket_update_action[1]["ticket_id"] == "TCK-88"

    progress = _full_flow_progress(transcript)
    crm_action = _strict_full_flow_action(progress)
    assert crm_action is not None
    assert crm_action[0] == "tickets.update"

    transcript.append(
        {
            "action": {
                "tool": "tickets.update",
                "args": {"ticket_id": "TCK-88"},
                "result": {"ok": True},
            }
        }
    )
    progress = _full_flow_progress(transcript)
    crm_create_action = _strict_full_flow_action(progress)
    assert crm_create_action is not None
    assert crm_create_action[0] == "crm.create_deal"

    transcript.append(
        {
            "action": {
                "tool": "crm.create_deal",
                "args": {"name": "Deal"},
                "result": {"id": "D-902"},
            }
        }
    )
    progress = _full_flow_progress(transcript)
    crm_log_action = _strict_full_flow_action(progress)
    assert crm_log_action is not None
    assert crm_log_action[0] == "crm.log_activity"
    assert crm_log_action[1]["deal_id"] == "D-902"


def test_strict_full_flow_complete_requires_all_full_subgoals() -> None:
    progress = {
        "citations": True,
        "approval_with_amount": True,
        "email_sent": True,
        "email_parsed": True,
        "doc_logged": True,
        "ticket_updated": True,
        "crm_logged": True,
    }
    assert _strict_full_flow_complete(progress) is True
    progress["crm_logged"] = False
    assert _strict_full_flow_complete(progress) is False
