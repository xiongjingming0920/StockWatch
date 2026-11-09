"""Routing tests do not contact a model provider or use real credentials."""
import asyncio

import httpx
import pytest

from app.agent import plan


class Response:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": self.content}}]}


@pytest.mark.parametrize(
    ("content", "expected_intent", "expected_mode"),
    [
        ('{"intent":"history","days":14}', "history", "大模型路由"),
        ('{"intent":"history","days":400}', "history", "规则路由"),
        ("not json", "history", "规则路由"),
        ("", "history", "规则路由"),
        ('{"intent":"unexpected","days":7}', "history", "规则路由"),
    ],
)
def test_plan_routing_and_safe_fallback(monkeypatch, content, expected_intent, expected_mode):
    monkeypatch.setenv("STOCKWATCH_LLM_API_KEY", "unit-test-only")
    monkeypatch.setenv("STOCKWATCH_LLM_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("STOCKWATCH_LLM_MODEL", "deepseek-flash")

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, **kwargs):
            assert url == "https://api.deepseek.com/chat/completions"
            assert kwargs["json"]["model"] == "deepseek-flash"
            assert kwargs["json"]["response_format"] == {"type": "json_object"}
            return Response(content)

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    result = asyncio.run(plan({"message": "最近7天缺货几天？"}))
    assert result["intent"] == expected_intent
    assert expected_mode in result["mode"]
    assert result["days"] == (14 if content.startswith('{"intent":"history","days":14') else 7)


def test_provider_timeout_falls_back_without_leaking_error(monkeypatch):
    monkeypatch.setenv("STOCKWATCH_LLM_API_KEY", "unit-test-only")
    monkeypatch.setenv("STOCKWATCH_LLM_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("STOCKWATCH_LLM_MODEL", "deepseek-flash")

    class FailingClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, **kwargs):
            raise httpx.ReadTimeout("a private provider error")

    monkeypatch.setattr(httpx, "AsyncClient", FailingClient)
    result = asyncio.run(plan({"message": "最近7天缺货几天？"}))
    assert result["intent"] == "history"
    assert "模型调用失败" in result["mode"]
    assert "private provider error" not in result["warning"]
