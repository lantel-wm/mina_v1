from __future__ import annotations

import time
from typing import Any

from fastapi import FastAPI


app = FastAPI(title="Mina Fake DeepSeek")
CALLS: list[dict[str, Any]] = []


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {"ok": True, "service": "mina-fake-deepseek", "calls": len(CALLS)}


@app.get("/calls")
def calls() -> dict[str, Any]:
    return {"ok": True, "count": len(CALLS), "calls": CALLS}


@app.post("/chat/completions")
async def chat_completions(payload: dict[str, Any]) -> dict[str, Any]:
    messages = payload.get("messages") if isinstance(payload.get("messages"), list) else []
    tool_messages = [message for message in messages if isinstance(message, dict) and message.get("role") == "tool"]
    user_message = _last_user_message(messages)
    CALLS.append(
        {
            "message_count": len(messages),
            "tool_message_count": len(tool_messages),
            "user_message": user_message,
        }
    )

    if tool_messages and _is_search_message(user_message):
        tool_content = str(tool_messages[-1].get("content") or "")
        content = "联网知识查询链路可用：Minecraft Wiki" if "Minecraft Wiki" in tool_content else "搜索结果缺失。"
        message = {"role": "assistant", "content": content}
        finish_reason = "stop"
    elif tool_messages and _is_status_message(user_message):
        tool_content = str(tool_messages[-1].get("content") or "")
        content = "当前任务：follow_player，状态：active。" if "follow_player" in tool_content else "当前没有正在执行的身体任务。"
        message = {"role": "assistant", "content": content}
        finish_reason = "stop"
    elif tool_messages and _is_stop_message(user_message):
        tool_content = str(tool_messages[-1].get("content") or "")
        content = "我已经停止当前身体任务。" if '"ok": true' in tool_content else "当前没有正在执行的身体任务。"
        message = {"role": "assistant", "content": content}
        finish_reason = "stop"
    elif tool_messages and _is_follow_message(user_message):
        tool_content = str(tool_messages[-1].get("content") or "")
        content = "我没有权限控制身体任务。" if "permission denied" in tool_content else "身体任务没有成功启动。"
        message = {"role": "assistant", "content": content}
        finish_reason = "stop"
    elif tool_messages:
        message = {"role": "assistant", "content": "错误：action barrier 未生效。"}
        finish_reason = "stop"
    elif _is_search_message(user_message):
        message = {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call-search",
                    "type": "function",
                    "function": {
                        "name": "web_search",
                        "arguments": '{"query":"Minecraft Wiki","max_results":3}',
                    },
                }
            ],
        }
        finish_reason = "tool_calls"
    elif _is_status_message(user_message):
        message = {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call-status",
                    "type": "function",
                    "function": {
                        "name": "task_status",
                        "arguments": "{}",
                    },
                }
            ],
        }
        finish_reason = "tool_calls"
    elif _is_stop_message(user_message):
        message = {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call-stop",
                    "type": "function",
                    "function": {
                        "name": "stop_body_task",
                        "arguments": "{}",
                    },
                }
            ],
        }
        finish_reason = "tool_calls"
    elif "时间" in user_message or "time" in user_message.lower():
        message = {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call-time",
                    "type": "function",
                    "function": {
                        "name": "run_read_only_command",
                        "arguments": '{"command":"time query daytime"}',
                    },
                }
            ],
        }
        finish_reason = "tool_calls"
    elif _is_follow_message(user_message):
        message = {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call-follow",
                    "type": "function",
                    "function": {
                        "name": "start_body_task",
                        "arguments": '{"task_type":"follow_player","target_hint":"me"}',
                    },
                }
            ],
        }
        finish_reason = "tool_calls"
    else:
        message = {"role": "assistant", "content": "fake DeepSeek received the request."}
        finish_reason = "stop"

    return {
        "id": f"chatcmpl-fake-{len(CALLS)}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": payload.get("model") or "mina-fake-deepseek",
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def _last_user_message(messages: list[Any]) -> str:
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("role") == "user":
            return str(message.get("content") or "")
    return ""


def _is_search_message(message: str) -> bool:
    normalized = message.lower()
    return "查资料" in message or "搜索" in message or "wiki" in normalized or "search" in normalized


def _is_status_message(message: str) -> bool:
    normalized = message.lower()
    return "状态" in message or "status" in normalized or "当前任务" in message


def _is_stop_message(message: str) -> bool:
    normalized = message.lower()
    return "停止" in message or "取消" in message or "stop" in normalized or "cancel" in normalized


def _is_follow_message(message: str) -> bool:
    return "跟随" in message or "follow" in message.lower()
