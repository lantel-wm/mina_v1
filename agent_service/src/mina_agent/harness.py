from __future__ import annotations

import json
import logging
import time
from typing import Any

from .config import Settings
from .context import build_messages
from .deepseek import DeepSeekClient, DeepSeekError
from .memory import MemoryStore
from .schemas import TurnResponse
from .tools import ToolRunner, tool_specs

LOGGER = logging.getLogger("mina_agent.harness")


class AgentHarness:
    def __init__(self, settings: Settings, memory: MemoryStore, deepseek: DeepSeekClient, tools: ToolRunner):
        self.settings = settings
        self.memory = memory
        self.deepseek = deepseek
        self.tools = tools
        self._last_companion_message: dict[str, float] = {}

    def run_turn(self, turn: dict[str, Any]) -> dict[str, Any]:
        request_id = str(turn.get("request_id") or "")
        player = turn.get("player") or {}
        player_id = str(player.get("uuid") or "unknown")
        self._debug(
            "turn start request_id=%s trigger=%s player=%s message=%s",
            request_id,
            turn.get("trigger"),
            player.get("name") or player_id,
            _truncate(str(turn.get("message") or ""), 300),
        )
        self.memory.upsert_player(player)

        if turn.get("trigger") == "companion_tick":
            companion = self._companion_tick(turn)
            if companion is not None:
                return companion.to_dict()
            return TurnResponse().to_dict()

        message = str(turn.get("message") or "")
        if message:
            self.memory.add_conversation(request_id, player_id, "user", message)

        if not self.deepseek.configured():
            offline = self._offline_fallback(turn)
            if offline is not None:
                for message_item in offline.messages:
                    content = str(message_item.get("content") or "").strip()
                    if content:
                        self.memory.add_conversation(request_id, player_id, "assistant", content)
                self._debug("turn fallback request_id=%s reason=missing_api_key handled=offline_rule", request_id)
                return offline.to_dict()
            fallback = "Mina sidecar is running, but MINA_API_KEY is not configured."
            self._debug("turn fallback request_id=%s reason=missing_api_key", request_id)
            self.memory.add_conversation(request_id, player_id, "assistant", fallback)
            return TurnResponse(messages=[{"target": "requester", "content": fallback}]).to_dict()

        turn = self._with_current_task(turn)
        messages = build_messages(turn, self.memory)
        actions: list[dict[str, Any]] = []
        usage: dict[str, Any] = {}
        invalid_tool_results = 0
        try:
            for subturn in range(1, self.settings.max_tool_turns + 1):
                self._debug("model call request_id=%s subturn=%s messages=%s", request_id, subturn, len(messages))
                response = self.deepseek.chat(messages, tools=tool_specs())
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
                    _truncate(str(assistant_message.get("content") or ""), 500),
                    usage,
                )
                if response.finish_reason != "tool_calls" or not tool_calls:
                    content = str(assistant_message.get("content") or "").strip()
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
                    self._debug("turn final request_id=%s messages=0 actions=0", request_id)
                    return TurnResponse(debug={"usage": usage, "tool_subturns": subturn}).to_dict()

                for call in tool_calls:
                    function = call.get("function") or {}
                    name = str(function.get("name") or "")
                    args = _parse_args(function.get("arguments"))
                    self._debug(
                        "tool call request_id=%s subturn=%s tool_call_id=%s name=%s args=%s",
                        request_id,
                        subturn,
                        call.get("id"),
                        name,
                        _truncate(json.dumps(args, ensure_ascii=False), 1200),
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
                        "tool result request_id=%s subturn=%s name=%s action=%s content=%s",
                        request_id,
                        subturn,
                        name,
                        result_actions,
                        _truncate(result.content, 1200),
                    )
                    self.memory.record_tool_call(
                        request_id,
                        name,
                        args,
                        {"content": result.content, "actions": result_actions},
                        "ok" if result_actions or "error" not in result.content else "error",
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
            self._debug("turn deepseek_error request_id=%s status=%s message=%s", request_id, exc.status, _truncate(exc.message, 1200))
            return TurnResponse(messages=[{"target": "requester", "content": content}], actions=actions).to_dict()

        content = "工具调用轮次达到上限，我先停下，避免误操作。"
        if actions:
            content = "我已经请求执行前面的动作，但后续工具调用轮次达到上限，先停在这里。"
        self._debug("turn max_tool_turns request_id=%s actions=%s", request_id, len(actions))
        return TurnResponse(messages=[{"target": "requester", "content": content}], actions=actions, debug={"usage": usage}).to_dict()

    def _offline_fallback(self, turn: dict[str, Any]) -> TurnResponse | None:
        message = str(turn.get("message") or "").strip()
        normalized = message.lower()
        if not normalized:
            return None

        if _contains_any(normalized, {"状态", "status", "进度"}):
            status = self.tools.skills.task_status(None, turn)
            if status.get("ok") is False:
                return TurnResponse(messages=[{"target": "requester", "content": "当前没有正在执行的身体任务。"}])
            return TurnResponse(
                messages=[
                    {
                        "target": "requester",
                        "content": f"当前任务：{status.get('type')}，状态：{status.get('status')}，阶段：{status.get('stage')}。",
                    }
                ],
                debug={"offline_fallback": True, "task_status": status},
            )

        if _contains_any(normalized, {"停止", "stop", "取消"}):
            response = self.tools.skills.stop_task(None, turn)
            response.debug["offline_fallback"] = True
            return response

        if _offline_follow_intent(normalized):
            return self._offline_tool_response(
                "start_body_task",
                {"task_type": "follow_player", "target_hint": message},
                turn,
                "我开始跟随你，会根据距离变化继续调整。",
            )

        if _offline_chop_tree_intent(normalized):
            return self._offline_tool_response(
                "start_body_task",
                {"task_type": "chop_tree", "target_hint": message},
                turn,
                "我开始砍树，会根据实际执行结果继续调整。",
            )

        command = _offline_read_only_command(normalized)
        if command:
            return self._offline_tool_response(
                "run_read_only_command",
                {"command": command},
                turn,
                "我会执行这个只读查询。",
            )

        if _contains_any(normalized, {"查资料", "搜索", "search", "wiki"}):
            args = {"query": message, "max_results": 3}
            result = self.tools.run("web_search", args, turn)
            self._record_tool_call(turn, "web_search", args, result, [])
            payload = _json_object(result.content)
            if payload.get("ok") is True:
                lines = []
                for item in payload.get("results") or []:
                    if not isinstance(item, dict):
                        continue
                    title = str(item.get("title") or "result")
                    url = str(item.get("url") or "")
                    content = str(item.get("content") or "").strip()
                    detail = f"{title} {url}".strip()
                    if content:
                        detail += f" - {_truncate(content, 120)}"
                    lines.append(detail)
                if lines:
                    return TurnResponse(
                        messages=[{"target": "requester", "content": "搜索结果：\n" + "\n".join(lines)}],
                        debug={"offline_fallback": True},
                    )
            error = str(payload.get("error") or "web_search unavailable")
            return TurnResponse(messages=[{"target": "requester", "content": f"联网搜索暂不可用：{error}"}])

        return None

    def _offline_tool_response(self, name: str, args: dict[str, Any], turn: dict[str, Any], fallback_message: str) -> TurnResponse:
        result = self.tools.run(name, args, turn)
        payload = _json_object(result.content)
        actions = []
        if result.action:
            actions.append(result.action)
        actions.extend(result.actions)
        messages = payload.get("messages") if isinstance(payload.get("messages"), list) else []
        if payload.get("ok") is False:
            error = str(payload.get("error") or "tool unavailable")
            if not messages:
                messages = [{"target": "requester", "content": f"离线模式无法完成请求：{error}"}]
        elif not messages and actions:
            messages = [{"target": "requester", "content": fallback_message}]
        self._record_tool_call(turn, name, args, result, actions)
        return TurnResponse(messages=messages, actions=actions, debug={"offline_fallback": True})

    def _record_tool_call(
        self,
        turn: dict[str, Any],
        name: str,
        args: dict[str, Any],
        result: Any,
        result_actions: list[dict[str, Any]],
    ) -> None:
        request_id = str(turn.get("request_id") or "")
        status = "ok" if result_actions or not _is_tool_error(result.content) else "error"
        self.memory.record_tool_call(
            request_id,
            name,
            args,
            {"content": result.content, "actions": result_actions},
            status,
        )

    def _companion_tick(self, turn: dict[str, Any]) -> TurnResponse | None:
        player = turn.get("player") or {}
        player_id = str(player.get("uuid") or "unknown")
        snapshot = turn.get("snapshot") or {}
        player_state = snapshot.get("player_state") or {}
        health = float(player_state.get("health") or 20)
        hunger = int(player_state.get("food") or 20)
        nearby = snapshot.get("nearby_entities") or []
        hostile_close = [
            entity for entity in nearby
            if entity.get("category") == "hostile" and float(entity.get("distance") or 999) <= 12
        ]
        now = time.time()
        last = self._last_companion_message.get(player_id, 0)
        urgent = health <= 6 or hunger <= 5 or bool(hostile_close)
        cooldown = self.settings.emergency_cooldown_seconds if urgent else self.settings.companion_cooldown_seconds
        if now - last < cooldown:
            return None
        content = ""
        if health <= 6:
            content = "你现在血量很低，先拉开距离并补血。"
        elif hunger <= 5:
            content = "饥饿值偏低，记得先吃点东西。"
        elif hostile_close:
            nearest = hostile_close[0]
            content = f"附近有 {nearest.get('type', 'hostile mob')}，距离大约 {nearest.get('distance')} 格。"
        if not content:
            return None
        self._last_companion_message[player_id] = now
        self.memory.add_event(player_id, "companion_alert", {"content": content}, importance=2)
        self._debug("companion message player=%s content=%s", player.get("name") or player_id, content)
        return TurnResponse(messages=[{"target": "requester", "content": content}])

    def _with_current_task(self, turn: dict[str, Any]) -> dict[str, Any]:
        try:
            status = self.tools.skills.task_status(None, turn)
        except Exception:  # noqa: BLE001 - context enrichment should never break a turn.
            return turn
        if status.get("ok") is False:
            return turn
        enriched = dict(turn)
        snapshot = dict(enriched.get("snapshot") or {})
        snapshot["active_task"] = status
        enriched["snapshot"] = snapshot
        return enriched

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


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "...<truncated>"


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


def _action_ack(tool_name: str) -> str:
    if tool_name == "run_read_only_command":
        return "我会执行这个只读查询。"
    if tool_name == "start_body_task":
        return "我开始执行，会根据真实游戏反馈继续调整。"
    if tool_name == "stop_body_task":
        return "我已经停止当前身体任务。"
    return "我开始执行。"


def _contains_any(value: str, needles: set[str]) -> bool:
    return any(needle in value for needle in needles)


def _offline_read_only_command(message: str) -> str:
    if "时间" in message or "time" in message:
        return "time query daytime"
    if "种子" in message or "seed" in message:
        return "seed"
    if "天气" in message or "weather" in message:
        return "weather query"
    if "在线" in message or "玩家列表" in message or message == "list" or "player list" in message:
        return "list"
    return ""


def _offline_follow_intent(message: str) -> bool:
    return _contains_any(message, {"跟随我", "跟着我", "follow me", "follow player"})


def _offline_chop_tree_intent(message: str) -> bool:
    return _contains_any(
        message,
        {
            "砍树",
            "砍木头",
            "伐木",
            "chop tree",
            "chop a tree",
            "cut tree",
            "cut down tree",
            "cut down a tree",
            "chop wood",
        },
    )


def _deepseek_error_message(exc: DeepSeekError) -> str:
    if exc.status in {401, 402}:
        return f"Mina 的 DeepSeek API 当前不可用：HTTP {exc.status}。请检查 API key 或余额。"
    if exc.status in {429, 500, 503}:
        return f"Mina 暂时被 DeepSeek 限流或服务繁忙：HTTP {exc.status}。稍后再试。"
    return f"Mina 调用 DeepSeek 时遇到错误：HTTP {exc.status}。"
