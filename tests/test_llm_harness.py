from __future__ import annotations

from vei.cli.vei_llm_test import _normalize_result, _select_progress_action


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
