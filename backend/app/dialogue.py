"""Bounded DeepSeek conversation. Model can only call two read-only tools."""
from __future__ import annotations

import json
import os
import time
from datetime import date, timedelta
from typing import Any, TypedDict

import httpx
from langgraph.graph import END, START, StateGraph

from . import services, run_store

SYSTEM = """你是生鲜缺货巡检助手。根据当前选中的个案及工具结果自然对话，回答用户问题。
历史数据工具的截止日是回放日；所有统计必须来自工具结果。涉及具体缺货天数、时长、排名、模型分数时先调用工具，不要编造数据。
数据仅有真实历史记录，不包含实时库存、采购单、供应商、真实损失或干预结果；不可断定根因、补货量或把相关性当因果。
规则分数不是概率；逻辑回归模型分数未经校准，历史数据不等于模型解释。未获取足够证据时明确说明。
销售字段是归一化数值而非真实销量件数或金额。无数据须明确；简洁回答并标明时间范围。对无关话题可礼貌回应但不要编造业务事实。"""

TOOLS = [
    {"type": "function", "function": {"name": "get_case_summary", "description": "读取当前选中个案、日期、风险排序方法、分数和近七日缺货统计。", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
    {"type": "function", "function": {"name": "get_stockout_history", "description": "查询当前个案截至回放日之前（含当日）的最近 N 天缺货记录及汇总。", "parameters": {"type": "object", "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 90}}, "required": ["days"], "additionalProperties": False}}},
]


class State(TypedDict, total=False):
    case_id: str
    message: str
    history: list[dict[str, str]]
    response: dict[str, Any]
    run_id: str | None


def tool_call(case_id: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
    case = services.get_case(case_id)
    if not case:
        raise ValueError("case unavailable")
    if name == "get_case_summary":
        if args:
            raise ValueError("invalid arguments")
        keys = ("id", "store_id", "product_id", "as_of_date", "target_date", "method", "method_key", "rank", "score", "stockout_days_7d", "stockout_hours_7d", "dataset_sha")
        return {k: case.get(k) for k in keys}
    if name != "get_stockout_history" or set(args) != {"days"} or type(args["days"]) is not int or not 1 <= args["days"] <= 90:
        raise ValueError("invalid tool or arguments")
    days = args["days"]
    rows = services.get_history(case_id, days)
    end = date.fromisoformat(case["as_of_date"])
    start = end - timedelta(days=days - 1)
    # services.get_history enforces the case snapshot; never trust model supplied dates.
    dates = {r["dt"] for r in rows}
    missing = [(start + timedelta(days=i)).isoformat() for i in range(days) if (start + timedelta(days=i)).isoformat() not in dates]
    unknown = [r["dt"] for r in rows if r["stock_hour6_22_cnt"] is None]
    stockout = [r["dt"] for r in rows if r["stock_hour6_22_cnt"] is not None and r["stock_hour6_22_cnt"] > 0]
    return {"start_date": start.isoformat(), "end_date": end.isoformat(), "observed_days": len(rows),
            "stockout_days": len(stockout), "stockout_dates": stockout, "missing_dates": missing,
            "unknown_dates": unknown, "rows": rows}


async def run_dialogue(state: State) -> dict[str, Any]:
    key = os.environ["STOCKWATCH_LLM_API_KEY"].strip()
    base = os.environ["STOCKWATCH_LLM_BASE_URL"].strip().rstrip("/")
    model = os.environ["STOCKWATCH_LLM_MODEL"].strip()
    case = services.get_case(state["case_id"])
    if not case:
        raise ValueError("case unavailable")
    # User-provided history is limited and cannot add system/tool instructions.
    messages = [{"role": "system", "content": SYSTEM + f"\n当前工单回放截止日：{case['as_of_date']}。"}]
    messages.extend(state.get("history", [])[-12:])
    messages.append({"role": "user", "content": state["message"]})
    events: list[dict[str, Any]] = []
    evidence: dict[str, Any] = {"case_id": state["case_id"], "as_of_date": case["as_of_date"]}
    async with httpx.AsyncClient(timeout=25.0) as client:
        for _ in range(4):
            payload: dict[str, Any] = {"model": model, "messages": messages, "tools": TOOLS,
                                       "tool_choice": "auto", "temperature": 0, "max_tokens": 700}
            if base.startswith("https://api.deepseek.com"):
                payload["thinking"] = {"type": "disabled"}
            run_id = state.get("run_id")
            if run_id:
                run_store.record_event(run_id, "model_call", status="running")
            started = time.monotonic()
            try:
                response = await client.post(base + "/chat/completions", headers={"Authorization": f"Bearer {key}"}, json=payload)
                response.raise_for_status()
                message = response.json()["choices"][0]["message"]
            except BaseException:
                if run_id:
                    run_store.record_event(run_id, "model_call", status="error", duration_ms=int((time.monotonic()-started)*1000), error_code="model_unavailable")
                raise
            if run_id:
                run_store.record_event(run_id, "model_call", status="success", duration_ms=int((time.monotonic()-started)*1000))
            calls = message.get("tool_calls") or []
            if not calls:
                answer = message.get("content")
                if not isinstance(answer, str) or not answer.strip():
                    raise ValueError("empty answer")
                if any(term in state["message"] for term in ("缺货", "销量", "小时", "几天", "多少", "分数", "排名")) and not any(event["status"] == "success" for event in events):
                    raise ValueError("missing tool evidence")
                events.append({"operator": "compose_answer", "status": "success", "detail": "DeepSeek 生成；请核对工具证据"})
                return {"response": {"answer": answer.strip(), "tool_calls": events, "evidence": evidence,
                                     "mode": "DeepSeek 对话 + 受控工具", "warning": "回答由模型生成，可能有误，请核对工具证据。"}}
            if len(events) + len(calls) > 6:
                raise ValueError("tool limit exceeded")
            assistant = {"role": "assistant", "content": message.get("content"), "tool_calls": calls}
            messages.append(assistant)
            for call in calls:
                name = call["function"]["name"]
                safe_name = name if name in {"get_case_summary", "get_stockout_history"} else "unknown_tool"
                if run_id:
                    run_store.record_event(run_id, "tool_call", status="running", tool_name=safe_name)
                tool_started = time.monotonic()
                try:
                    args = json.loads(call["function"].get("arguments") or "{}")
                    if not isinstance(args, dict):
                        raise ValueError("invalid arguments")
                    result = tool_call(state["case_id"], name, args)
                    evidence[name] = result
                    event = {"operator": name, "status": "success", "detail": f"回放截止 {case['as_of_date']}"}
                except (ValueError, KeyError, TypeError, OSError):
                    result = {"error": "工具参数无效或数据不可用，请检查请求"}
                    event = {"operator": name if name in {"get_case_summary", "get_stockout_history"} else "unknown_tool", "status": "error"}
                except BaseException:
                    if run_id:
                        run_store.record_event(run_id, "tool_call", status="error", tool_name=safe_name, duration_ms=int((time.monotonic()-tool_started)*1000), error_code="tool_error")
                    raise
                if run_id:
                    run_store.record_event(run_id, "tool_call", status=event["status"], tool_name=safe_name, duration_ms=int((time.monotonic()-tool_started)*1000), error_code="tool_error" if event["status"] == "error" else None)
                events.append(event)
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result, ensure_ascii=False)})
    raise ValueError("model step budget exceeded")


_graph = StateGraph(State)
_graph.add_node("dialogue", run_dialogue)
_graph.add_edge(START, "dialogue")
_graph.add_edge("dialogue", END)
_workflow = _graph.compile()


async def conversation(case_id: str, message: str, history: list[dict[str, str]], run_id: str | None = None) -> dict[str, Any]:
    state = await _workflow.ainvoke({"case_id": case_id, "message": message, "history": history, "run_id": run_id})
    return state["response"]
