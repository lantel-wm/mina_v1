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

    if tool_messages:
        message = {"role": "assistant", "content": "错误：action barrier 未生效。"}
        finish_reason = "stop"
    elif "跟随" in user_message or "follow" in user_message.lower():
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
