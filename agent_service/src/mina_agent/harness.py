from __future__ import annotations

import json
import logging
import re
from typing import Any

from .config import Settings
from .context import build_messages, is_memory_recall_request
from .deepseek import DeepSeekClient, DeepSeekError
from .memory import MemoryStore
from .schemas import TurnResponse
from .tools import (
    ToolRunner,
    tool_specs,
)

LOGGER = logging.getLogger("mina_agent.harness")


class AgentHarness:
    def __init__(self, settings: Settings, memory: MemoryStore, deepseek: DeepSeekClient, tools: ToolRunner):
        self.settings = settings
        self.memory = memory
        self.deepseek = deepseek
        self.tools = tools

    def run_turn(self, turn: dict[str, Any]) -> dict[str, Any]:
        request_id = str(turn.get("request_id") or "")
        player = turn.get("player") or {}
        player_id = str(player.get("uuid") or "unknown")
        self._debug(
            "turn start request_id=%s trigger=%s player=%s message=%s",
            request_id,
            turn.get("trigger"),
            player.get("name") or player_id,
            _log_preview(str(turn.get("message") or ""), 300),
        )
        self.memory.upsert_player(player)

        message = str(turn.get("message") or "")
        if message:
            self.memory.add_conversation(request_id, player_id, "user", message)

        if not self.deepseek.configured():
            fallback = "Mina sidecar is running, but MINA_API_KEY is not configured."
            self._debug("turn fallback request_id=%s reason=missing_api_key", request_id)
            self.memory.add_conversation(request_id, player_id, "assistant", fallback)
            return TurnResponse(messages=[{"target": "requester", "content": fallback}]).to_dict()

        messages = build_messages(turn, self.memory)
        actions: list[dict[str, Any]] = []
        usage: dict[str, Any] = {}
        invalid_tool_results = 0
        requires_memory_search = is_memory_recall_request(message)
        memory_search_seen = False
        try:
            for subturn in range(1, self.settings.max_tool_turns + 1):
                self._debug("model call request_id=%s subturn=%s messages=%s", request_id, subturn, len(messages))
                specs = tool_specs()
                try:
                    response = self.deepseek.chat(messages, tools=specs)
                    self.memory.record_model_call(
                        request_id=request_id,
                        subturn=subturn,
                        model=self.settings.model,
                        messages_count=len(messages),
                        tools=_tool_spec_names(specs),
                        status="ok",
                        finish_reason=response.finish_reason,
                        usage=response.usage,
                        response=_model_response_summary(response.message),
                    )
                except DeepSeekError as exc:
                    self.memory.record_model_call(
                        request_id=request_id,
                        subturn=subturn,
                        model=self.settings.model,
                        messages_count=len(messages),
                        tools=_tool_spec_names(specs),
                        status="error",
                        error=f"HTTP {exc.status}: {_log_preview(exc.message, 1200)}",
                    )
                    raise
                usage = response.usage
                assistant_message = response.message
                messages.append(assistant_message)
                tool_calls = assistant_message.get("tool_calls") or []
                self._debug(
                    "model response request_id=%s subturn=%s finish_reason=%s tool_calls=%s content=%s usage=%s",
                    request_id,
                    subturn,
                    response.finish_reason,
                    len(tool_calls),
                    _log_preview(str(assistant_message.get("content") or ""), 500),
                    usage,
                )
                if response.finish_reason != "tool_calls" or not tool_calls:
                    content = _minecraft_chat_text(str(assistant_message.get("content") or ""))
                    if content and requires_memory_search and not memory_search_seen:
                        messages.append(
                            {
                                "role": "system",
                                "content": (
                                    "Policy reminder: this is a memory recall request. The direct answer was not sent. "
                                    "Call memory_search with the relevant key terms before giving a final answer."
                                ),
                            }
                        )
                        self._debug("turn repair request_id=%s reason=missing_memory_search", request_id)
                        continue
                    if content:
                        self.memory.add_conversation(request_id, player_id, "assistant", content)
                        self._debug("turn final request_id=%s messages=1 actions=%s", request_id, len(actions))
                        return TurnResponse(
                            messages=[{"target": "requester", "content": content}],
                            actions=actions,
                            debug={"usage": usage, "tool_subturns": subturn},
                        ).to_dict()
                    if actions:
                        content = "我开始执行。"
                        self.memory.add_conversation(request_id, player_id, "assistant", content)
                        self._debug("turn final request_id=%s messages=1 actions=%s content=execution_ack", request_id, len(actions))
                        return TurnResponse(
                            messages=[{"target": "requester", "content": content}],
                            actions=actions,
                            debug={"usage": usage, "tool_subturns": subturn},
                        ).to_dict()
                    content = "我没有生成可执行回应，请换个说法或补充目标。"
                    self.memory.add_conversation(request_id, player_id, "assistant", content)
                    self._debug("turn final request_id=%s messages=1 actions=0 content=empty_model_fallback", request_id)
                    return TurnResponse(
                        messages=[{"target": "requester", "content": content}],
                        debug={"usage": usage, "tool_subturns": subturn, "empty_model_fallback": True},
                    ).to_dict()

                for call in tool_calls:
                    function = call.get("function") or {}
                    name = str(function.get("name") or "")
                    args = _parse_args(function.get("arguments"))
                    if name == "memory_search":
                        memory_search_seen = True
                    self._debug(
                        "tool call request_id=%s subturn=%s tool_call_id=%s name=%s args=%s",
                        request_id,
                        subturn,
                        call.get("id"),
                        name,
                        _log_preview(json.dumps(args, ensure_ascii=False), 1200),
                    )
                    result = self.tools.run(name, args, turn)
                    result_actions = []
                    if result.action:
                        result_actions.append(result.action)
                    result_actions.extend(result.actions)
                    if result_actions:
                        actions.extend(result_actions)
                        invalid_tool_results = 0
                    elif _is_tool_error(result.content):
                        invalid_tool_results += 1
                    else:
                        invalid_tool_results = 0
                    self._debug(
                        "tool result request_id=%s subturn=%s name=%s action=%s content_length=%s content_preview=%s",
                        request_id,
                        subturn,
                        name,
                        result_actions,
                        len(result.content),
                        _log_preview(result.content, 1200),
                    )
                    self.memory.record_tool_call(
                        request_id,
                        name,
                        args,
                        {"content": result.content, "actions": result_actions},
                        "ok" if result_actions or not _is_tool_error(result.content) else "error",
                    )
                    if result_actions:
                        response_messages = _tool_payload_messages(result.content)
                        if not response_messages:
                            response_messages = [{"target": "requester", "content": _action_ack(name)}]
                        for message_item in response_messages:
                            content = str(message_item.get("content") or "").strip()
                            if content:
                                self.memory.add_conversation(request_id, player_id, "assistant", content)
                        self._debug(
                            "turn action_barrier request_id=%s subturn=%s name=%s actions=%s",
                            request_id,
                            subturn,
                            name,
                            len(actions),
                        )
                        return TurnResponse(
                            messages=response_messages,
                            actions=actions,
                            debug={"usage": usage, "tool_subturns": subturn, "action_barrier": True},
                        ).to_dict()
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.get("id"),
                            "content": result.content,
                        }
                    )
                    if invalid_tool_results >= 3:
                        content = "我还没有完成这步操作，因为连续几次工具调用缺少必要目标参数。我会先停下，避免误操作。"
                        if actions:
                            content = "我只请求了前面的准备动作；后续操作连续缺少必要目标参数，所以先停下，避免误操作。"
                        self.memory.add_conversation(request_id, player_id, "assistant", content)
                        self._debug("turn stopped_invalid_tools request_id=%s actions=%s", request_id, len(actions))
                        return TurnResponse(messages=[{"target": "requester", "content": content}], actions=actions).to_dict()
        except DeepSeekError as exc:
            content = _deepseek_error_message(exc)
            self._debug("turn deepseek_error request_id=%s status=%s message=%s", request_id, exc.status, _log_preview(exc.message, 1200))
            return TurnResponse(messages=[{"target": "requester", "content": content}], actions=actions).to_dict()

        content = "工具调用轮次达到上限，我先停下，避免误操作。"
        if actions:
            content = "我已经请求执行前面的动作，但后续工具调用轮次达到上限，先停在这里。"
        self._debug("turn max_tool_turns request_id=%s actions=%s", request_id, len(actions))
        return TurnResponse(messages=[{"target": "requester", "content": content}], actions=actions, debug={"usage": usage}).to_dict()

    def _debug(self, message: str, *args: Any) -> None:
        if self.settings.debug_tool_calls:
            LOGGER.info(message, *args)


def _parse_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(str(raw))
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _log_preview(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "...[log preview only; full tool content preserved]"


def _minecraft_chat_text(content: str) -> str:
    text = content.strip()
    if not text:
        return ""
    text = re.sub(r"\*\*([^*\n]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_\n]+)__", r"\1", text)
    text = text.replace("`", "")
    text = _EMOJI_RE.sub("", text)
    text = re.sub(r"(?m)^\s*[-*•]\s+", "", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


_EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")


def _is_tool_error(content: str) -> bool:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return False
    return isinstance(payload, dict) and payload.get("ok") is False


def _json_object(content: str) -> dict[str, Any]:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _tool_payload_messages(content: str) -> list[dict[str, Any]]:
    payload = _json_object(content)
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return []
    return [message for message in messages if isinstance(message, dict)]


def _tool_spec_names(specs: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for spec in specs:
        function = spec.get("function") if isinstance(spec, dict) else {}
        if isinstance(function, dict):
            name = str(function.get("name") or "")
            if name:
                names.append(name)
    return names


def _model_response_summary(message: dict[str, Any]) -> dict[str, Any]:
    tool_calls = message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else []
    tool_names: list[str] = []
    for call in tool_calls:
        function = call.get("function") if isinstance(call, dict) else {}
        if isinstance(function, dict):
            name = str(function.get("name") or "")
            if name:
                tool_names.append(name)
    content = str(message.get("content") or "")
    return {
        "content_preview": _log_preview(content, 500),
        "tool_call_count": len(tool_calls),
        "tool_names": tool_names,
    }


def _action_ack(tool_name: str) -> str:
    if tool_name == "run_read_only_command":
        return "我会执行这个只读查询。"
    return "我开始执行。"


def _deepseek_error_message(exc: DeepSeekError) -> str:
    if exc.status in {401, 402}:
        return f"Mina 的 DeepSeek API 当前不可用：HTTP {exc.status}。请检查 API key 或余额。"
    if exc.status in {429, 500, 503}:
        return f"Mina 暂时被 DeepSeek 限流或服务繁忙：HTTP {exc.status}。稍后再试。"
    return f"Mina 调用 DeepSeek 时遇到错误：HTTP {exc.status}。"
