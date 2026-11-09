import asyncio
import json

from app import dialogue


def test_tool_scope_and_followup(monkeypatch):
    monkeypatch.setenv("STOCKWATCH_LLM_API_KEY", "test-not-a-real-key")
    monkeypatch.setenv("STOCKWATCH_LLM_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("STOCKWATCH_LLM_MODEL", "deepseek-flash")
    monkeypatch.setattr(dialogue.services, "get_case", lambda _: {"as_of_date": "2024-05-07", "dataset_sha": "sha"})
    seen = []
    def history(case_id, days):
        seen.append((case_id, days))
        return [{"dt": "2024-05-07", "stock_hour6_22_cnt": 1, "sale_amount": 0.1}]
    monkeypatch.setattr(dialogue.services, "get_history", history)
    requests = []
    class Response:
        def __init__(self, payload): self.payload = payload
        def raise_for_status(self): pass
        def json(self): return self.payload
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, headers, json):
            requests.append(json)
            if len(requests) == 1:
                msg = {"content": None, "tool_calls": [{"id":"tool-1", "type":"function", "function":{"name":"get_stockout_history", "arguments":"{\"days\": 3}"}}]}
            else:
                msg = {"content":"过去三天中，已观察到一天缺货，另两天没有记录。"}
            return Response({"choices":[{"message":msg}]})
    monkeypatch.setattr(dialogue.httpx, "AsyncClient", Client)
    history_turns = [{"role":"user", "content":"这个商品怎么样？"}, {"role":"assistant", "content":"请说明时间范围。"}]
    result = asyncio.run(dialogue.conversation("case-1", "那最近三天呢？", history_turns))
    assert seen == [("case-1", 3)]
    assert result["evidence"]["get_stockout_history"]["end_date"] == "2024-05-07"
    assert len(result["evidence"]["get_stockout_history"]["missing_dates"]) == 2
    assert requests[0]["messages"][1:3] == history_turns
    assert requests[1]["messages"][-1]["role"] == "tool"
    assert result["mode"] == "DeepSeek 对话 + 受控工具"


def test_tool_rejects_arbitrary_dates_and_other_case(monkeypatch):
    monkeypatch.setattr(dialogue.services, "get_case", lambda _: {"as_of_date":"2024-05-07"})
    for name, args in [("get_stockout_history", {"days": 2, "end_date":"2024-05-08"}),
                       ("get_stockout_history", {"days": 100}), ("execute_sql", {"sql":"select 1"})]:
        try:
            dialogue.tool_call("case-1", name, args)
        except ValueError:
            pass
        else:
            raise AssertionError("tool should reject untrusted input")
