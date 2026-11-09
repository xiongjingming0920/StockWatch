import json

from app import dialogue, services

CASE_ID = "a" * 20
CASE = {"id": CASE_ID, "as_of_date": "2024-05-07", "dataset_sha": "sha", "method": "rule", "score": 1, "rank": 1, "stockout_days_7d": 7, "stockout_hours_7d": 12}

def configure(monkeypatch):
    monkeypatch.setattr(services, "get_case", lambda _: CASE)
    for key, value in {"STOCKWATCH_LLM_API_KEY": "test-key", "STOCKWATCH_LLM_BASE_URL": "https://example.test", "STOCKWATCH_LLM_MODEL": "test-model"}.items():
        monkeypatch.setenv(key, value)

def get_events(client, run_id):
    r = client.get("/api/v1/runs/" + run_id)
    assert r.status_code == 200
    return r.json()

def test_repeated_model_and_tool_events(admin_client, monkeypatch):
    configure(monkeypatch)
    monkeypatch.setattr(dialogue, "tool_call", lambda *_: {"observed_days": 2})
    class Response:
        def __init__(self, data): self.data = data
        def raise_for_status(self): pass
        def json(self): return self.data
    class Client:
        def __init__(self, **kwargs): self.n = 0
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, *args, **kwargs):
            self.n += 1
            if self.n == 1:
                calls = [{"id": str(i), "type": "function", "function": {"name": "get_stockout_history", "arguments": "{\"days\":2}"}} for i in range(2)]
                msg = {"content": None, "tool_calls": calls}
            else: msg = {"content": "结果"}
            return Response({"choices": [{"message": msg}]})
    monkeypatch.setattr(dialogue.httpx, "AsyncClient", Client)
    r = admin_client.post(f"/api/v1/cases/{CASE_ID}/messages", json={"message": "缺货秘密数据"})
    assert r.status_code == 200
    run = get_events(admin_client, r.json()["run_id"])
    assert run["run"]["status"] == "succeeded"
    events = run["events"]
    assert [(e["event_type"], e["status"]) for e in events].count(("tool_call", "success")) == 2
    assert [(e["event_type"], e["status"]) for e in events].count(("model_call", "success")) == 2
    assert "秘密数据" not in json.dumps(events, ensure_ascii=False)
    assert "test-key" not in json.dumps(events)

def test_failed_model_uses_rule_and_marks_degraded(admin_client, monkeypatch):
    configure(monkeypatch)
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, *args, **kwargs): raise ValueError("secret from provider")
    monkeypatch.setattr(dialogue.httpx, "AsyncClient", Client)
    r = admin_client.post(f"/api/v1/cases/{CASE_ID}/messages", json={"message": "供应商问题"})
    assert r.status_code == 200
    run = get_events(admin_client, r.json()["run_id"])
    assert run["run"]["status"] == "degraded"
    assert r.json()["run_status"] == "degraded"
    assert any(e["event_type"] == "model_call" and e["status"] == "error" for e in run["events"])
    assert any(e["event_type"] == "fallback" and e["status"] == "success" for e in run["events"])
    assert "secret from provider" not in json.dumps(run)

def test_failed_rule_collection_is_not_success(admin_client, monkeypatch):
    configure(monkeypatch)
    monkeypatch.delenv("STOCKWATCH_LLM_API_KEY")
    def failed(*args): raise ValueError("private data")
    monkeypatch.setattr(services, "get_history", failed)
    r = admin_client.post(f"/api/v1/cases/{CASE_ID}/messages", json={"message": "最近7天缺货几天"})
    assert r.status_code == 200
    assert "private data" not in r.text
    run = get_events(admin_client, r.json()["run_id"])
    assert run["run"]["status"] == "failed"
    assert r.json()["run_status"] == "failed"
    assert any(e["event_type"] == "collect" and e["status"] == "error" for e in run["events"])
    assert "private data" not in json.dumps(run)


def test_unexpected_failure_returns_safe_run_id(admin_client, monkeypatch):
    from app import agent
    configure(monkeypatch)
    monkeypatch.delenv("STOCKWATCH_LLM_API_KEY")
    async def fail(*args, **kwargs):
        raise RuntimeError("do not reveal private detail")
    monkeypatch.setattr(agent.workflow, "ainvoke", fail)
    r = admin_client.post(f"/api/v1/cases/{CASE_ID}/messages", json={"message": "hello"})
    assert r.status_code == 500
    assert "do not reveal" not in r.text
    run = get_events(admin_client, r.json()["run_id"])
    assert run["run"]["status"] == "failed"
    assert run["events"][-1]["event_type"] == "run_finished"

def test_cancelled_request_marks_failed(monkeypatch, tmp_path):
    import asyncio
    from types import SimpleNamespace
    from app import agent, run_store
    configure(monkeypatch)
    monkeypatch.delenv("STOCKWATCH_LLM_API_KEY")
    monkeypatch.setenv("STOCKWATCH_RUN_DB", str(tmp_path / "cancel.sqlite"))
    user_id = "11111111-1111-4111-8111-111111111111"
    async def cancelled(*args, **kwargs): raise asyncio.CancelledError()
    monkeypatch.setattr(agent.workflow, "ainvoke", cancelled)
    captured = []
    start = run_store.start_run
    def track(*args):
        value = start(*args); captured.append(value); return value
    monkeypatch.setattr(run_store, "start_run", track)
    try:
        asyncio.run(agent.investigate(CASE_ID, agent.Message(message="hello"), SimpleNamespace(state=SimpleNamespace(user={"id": user_id}))))
    except asyncio.CancelledError:
        pass
    else:
        raise AssertionError("cancellation should propagate")
    assert run_store.get_run(captured[0], user_id)["run"]["status"] == "failed"


def test_invalid_tool_is_recorded_and_marks_degraded(admin_client, monkeypatch):
    configure(monkeypatch)
    class Response:
        def __init__(self, data): self.data = data
        def raise_for_status(self): pass
        def json(self): return self.data
    class Client:
        def __init__(self, **kwargs): self.n = 0
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, *args, **kwargs):
            self.n += 1
            if self.n == 1:
                msg = {"content": None, "tool_calls": [{"id": "1", "type": "function", "function": {"name": "execute_sql", "arguments": "{}"}}]}
            else: msg = {"content": "无法执行该工具。"}
            return Response({"choices": [{"message": msg}]})
    monkeypatch.setattr(dialogue.httpx, "AsyncClient", Client)
    r = admin_client.post(f"/api/v1/cases/{CASE_ID}/messages", json={"message": "请执行不支持的操作"})
    assert r.status_code == 200
    run = get_events(admin_client, r.json()["run_id"])
    assert run["run"]["status"] == "degraded"
    errors = [e for e in run["events"] if e["event_type"] == "tool_call" and e["status"] == "error"]
    assert len(errors) == 1 and errors[0]["tool_name"] == "unknown_tool"
    assert "execute_sql" not in json.dumps(run)


def test_record_event_failure_still_finishes_run(admin_client, monkeypatch):
    from app import run_store
    configure(monkeypatch)
    monkeypatch.delenv("STOCKWATCH_LLM_API_KEY")
    def fail(*args, **kwargs): raise OSError("private journal error")
    monkeypatch.setattr(run_store, "record_event", fail)
    r = admin_client.post(f"/api/v1/cases/{CASE_ID}/messages", json={"message": "hello"})
    assert r.status_code == 500 and "private" not in r.text
    run = get_events(admin_client, r.json()["run_id"])
    assert run["run"]["status"] == "failed"
    assert run["events"][-1]["event_type"] == "run_finished"

def test_unavailable_terminal_store_returns_safe_500_without_false_success(admin_client, monkeypatch):
    from app import run_store
    configure(monkeypatch)
    monkeypatch.delenv("STOCKWATCH_LLM_API_KEY")
    def fail(*args, **kwargs): raise OSError("private journal error")
    monkeypatch.setattr(run_store, "finish_run", fail)
    r = admin_client.post(f"/api/v1/cases/{CASE_ID}/messages", json={"message": "hello"})
    assert r.status_code == 500 and "private" not in r.text
    run = get_events(admin_client, r.json()["run_id"])
    assert run["run"]["status"] == "running"

def test_model_and_fallback_failure_reports_failed(admin_client, monkeypatch):
    configure(monkeypatch)
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, *args, **kwargs): raise ValueError("model down")
    monkeypatch.setattr(dialogue.httpx, "AsyncClient", Client)
    def failed(*args): raise ValueError("private data")
    monkeypatch.setattr(services, "get_history", failed)
    r = admin_client.post(f"/api/v1/cases/{CASE_ID}/messages", json={"message": "最近7天缺货几天"})
    assert r.status_code == 200 and r.json()["run_status"] == "failed"
    assert "未完成" in r.json()["warning"] and "已返回" not in r.json()["warning"]
    run = get_events(admin_client, r.json()["run_id"])
    assert run["run"]["status"] == "failed"
