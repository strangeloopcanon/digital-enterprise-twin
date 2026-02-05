from __future__ import annotations

import asyncio
from types import SimpleNamespace

from vei.llm import providers


class _FakeTypes:
    class GenerateContentConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs


class _FakeAioModels:
    async def generate_content(self, *, model: str, contents: str, config: object):
        assert model == "gemini-2.5-pro"
        assert "Reply strictly as JSON" in contents
        return SimpleNamespace(text='{"tool":"browser.read","args":{}}', candidates=[])


class _FakeClient:
    last_instance: "_FakeClient | None" = None

    def __init__(self, *, api_key: str):
        self.api_key = api_key
        self.closed = False
        self.aio = SimpleNamespace(models=_FakeAioModels())
        _FakeClient.last_instance = self

    def close(self) -> None:
        self.closed = True


class _FakeGenAI:
    Client = _FakeClient
    types = _FakeTypes


def test_google_provider_uses_client_api(monkeypatch) -> None:
    monkeypatch.setattr(providers, "genai", _FakeGenAI)

    result = asyncio.run(
        providers.plan_once(
            provider="google",
            model="gemini-2.5-pro",
            system="sys",
            user="user",
            google_api_key="test-key",
        )
    )

    assert result == {"tool": "browser.read", "args": {}}
    assert _FakeClient.last_instance is not None
    assert _FakeClient.last_instance.closed is True
