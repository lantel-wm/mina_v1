from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from .body_agent import (
    BodySubagent,
    is_body_chop_tree_request,
    is_body_follow_request,
    is_body_instructional_request,
    is_body_stop_request,
    is_body_task_status_request,
)
from .config import Settings
from .context import build_messages, is_memory_recall_request
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
        self.body_subagent = BodySubagent(tools)
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

        local_observation = _local_observation_response(turn, has_active_body_task=self._has_active_body_task(turn))
        if local_observation is not None:
            for message_item in local_observation.messages:
                content = str(message_item.get("content") or "").strip()
                if content:
                    self.memory.add_conversation(request_id, player_id, "assistant", content)
            self._debug("turn local_observation request_id=%s intent=%s", request_id, local_observation.debug.get("intent"))
            return local_observation.to_dict()

        body_response = self.body_subagent.handle(turn)
        if body_response is not None:
            result_actions = []
            if body_response.tool_result.action:
                result_actions.append(body_response.tool_result.action)
            result_actions.extend(body_response.tool_result.actions)
            self._record_tool_call(turn, body_response.tool_name, body_response.args, body_response.tool_result, result_actions)
            for message_item in body_response.response.messages:
                content = str(message_item.get("content") or "").strip()
                if content:
                    self.memory.add_conversation(request_id, player_id, "assistant", content)
            self._debug(
                "turn body_subagent request_id=%s intent=%s actions=%s",
                request_id,
                body_response.response.debug.get("intent"),
                len(body_response.response.actions),
            )
            return body_response.response.to_dict()

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
                        error=f"HTTP {exc.status}: {_truncate(exc.message, 1200)}",
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
                    _truncate(str(assistant_message.get("content") or ""), 500),
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

        if is_body_task_status_request(normalized):
            args: dict[str, Any] = {}
            result = self.tools.run("task_status", args, turn)
            self._record_tool_call(turn, "task_status", args, result, [])
            status = _json_object(result.content)
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

        if _offline_stop_intent(normalized) and not is_body_instructional_request(normalized):
            return self._offline_tool_response("stop_body_task", {}, turn, "我已经停止当前身体任务。")

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

        if _offline_memory_search_intent(normalized):
            args = {"query": _offline_memory_query(message), "limit": 5}
            result = self.tools.run("memory_search", args, turn)
            self._record_tool_call(turn, "memory_search", args, result, [])
            payload = _json_object(result.content)
            lines = []
            if payload.get("ok") is True:
                for item in payload.get("results") or []:
                    if not isinstance(item, dict):
                        continue
                    content = str(item.get("content") or "").strip()
                    if content:
                        lines.append(_truncate(content, 160))
            if lines:
                return TurnResponse(
                    messages=[{"target": "requester", "content": "我找到了这些相关记忆：\n" + "\n".join(lines)}],
                    debug={"offline_fallback": True},
                )
            return TurnResponse(messages=[{"target": "requester", "content": "我没有找到相关记忆。"}])

        if _offline_memory_write_intent(normalized):
            return self._offline_tool_response(
                "memory_write",
                {"event_type": "player_fact", "content": _offline_memory_content(message), "importance": 3},
                turn,
                "我记住了。",
            )

        command = _offline_read_only_command(normalized)
        if command:
            return self._offline_tool_response(
                "run_read_only_command",
                {"command": command},
                turn,
                "我会执行这个只读查询。",
            )

        if _contains_any(normalized, {"查资料", "查一下", "查找", "联网", "搜索", "search", "wiki"}):
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
        elif not messages:
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
        alert_kind = ""
        content = ""
        if health <= 6:
            alert_kind = "health"
            content = "你现在血量很低，先拉开距离并补血。"
        elif hunger <= 5:
            alert_kind = "hunger"
            content = "饥饿值偏低，记得先吃点东西。"
        elif hostile_close:
            alert_kind = "hostile"
            nearest = hostile_close[0]
            content = f"附近有 {nearest.get('type', 'hostile mob')}，距离大约 {nearest.get('distance')} 格。"
        if not content:
            return None
        cooldown_key = f"{player_id}:{alert_kind}"
        last = self._last_companion_message.get(cooldown_key, 0)
        cooldown = self.settings.emergency_cooldown_seconds if alert_kind else self.settings.companion_cooldown_seconds
        if now - last < cooldown:
            return None
        self._last_companion_message[cooldown_key] = now
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

    def _has_active_body_task(self, turn: dict[str, Any]) -> bool:
        try:
            status = self.tools.skills.task_status(None, turn)
        except Exception:  # noqa: BLE001 - observation routing should never break a turn.
            return False
        return status.get("ok") is not False and status.get("status") == "active"

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
        "content_preview": _truncate(content, 500),
        "tool_call_count": len(tool_calls),
        "tool_names": tool_names,
    }


def _action_ack(tool_name: str) -> str:
    if tool_name == "run_read_only_command":
        return "我会执行这个只读查询。"
    if tool_name == "start_body_task":
        return "我开始执行，会根据真实游戏反馈继续调整。"
    if tool_name == "stop_body_task":
        return "我已经停止当前身体任务。"
    return "我开始执行。"


def _local_observation_response(turn: dict[str, Any], *, has_active_body_task: bool = False) -> TurnResponse | None:
    if turn.get("trigger") != "command":
        return None
    message = str(turn.get("message") or "").strip()
    normalized = message.lower()
    if not normalized:
        return None
    snapshot = turn.get("snapshot") if isinstance(turn.get("snapshot"), dict) else {}
    task_status_request = is_body_task_status_request(normalized)
    if task_status_request and (has_active_body_task or not _ambiguous_player_status_intent(normalized)):
        return None
    if _body_observation_intent(normalized):
        return TurnResponse(
            messages=[{"target": "requester", "content": _body_observation_message(snapshot)}],
            debug={"local_observation": True, "intent": "body_observation"},
        )
    if _player_observation_intent(normalized) or (task_status_request and _ambiguous_player_status_intent(normalized)):
        return TurnResponse(
            messages=[{"target": "requester", "content": _player_observation_message(snapshot)}],
            debug={"local_observation": True, "intent": "player_observation"},
        )
    return None


def _ambiguous_player_status_intent(message: str) -> bool:
    return message.strip(" ?？。.!！") in {"状态", "status"}


def _player_observation_intent(message: str) -> bool:
    if any(token in message for token in ("身体", "假人", "mina body", "body")):
        return False
    return any(
        token in message
        for token in (
            "我的状态",
            "我状态",
            "我现在状态",
            "当前状态",
            "现在状态",
            "状态怎么样",
            "我在哪",
            "我在什么位置",
            "我的位置",
            "我的坐标",
            "当前位置",
            "坐标是多少",
            "血量",
            "生命值",
            "生命",
            "饥饿",
            "饱食",
            "饱食度",
            "where am i",
            "my coordinates",
            "my position",
            "my health",
            "my hunger",
        )
    )


def _body_observation_intent(message: str) -> bool:
    has_body_subject = any(token in message for token in ("mina", "身体", "假人", "body", "你"))
    has_observation = any(token in message for token in ("在哪", "位置", "坐标", "离我", "距离", "状态", "where", "position", "coordinates"))
    return has_body_subject and has_observation


def _player_observation_message(snapshot: dict[str, Any]) -> str:
    player = snapshot.get("player_state") if isinstance(snapshot.get("player_state"), dict) else {}
    if not player:
        return "我还没有拿到你的当前状态快照。"
    parts: list[str] = []
    position = _position_phrase(player)
    if position:
        parts.append(f"你的位置：{position}")
    health = _number_phrase(player.get("health"))
    max_health = _number_phrase(player.get("max_health"))
    if health:
        if max_health:
            parts.append(f"生命 {health}/{max_health}")
        else:
            parts.append(f"生命 {health}")
    food = _number_phrase(player.get("food"))
    if food:
        parts.append(f"饥饿 {food}")
    mode = player.get("game_mode")
    if mode:
        parts.append(f"模式 {mode}")
    return "；".join(parts) + "。" if parts else "我还没有拿到你的当前状态快照。"


def _body_observation_message(snapshot: dict[str, Any]) -> str:
    body = snapshot.get("body_state") if isinstance(snapshot.get("body_state"), dict) else {}
    if not body or not body.get("online"):
        return "Mina body 当前不在线。"
    parts = ["Mina body 当前在线"]
    position = _position_phrase(body)
    if position:
        parts.append(f"位置：{position}")
    distance = _number_phrase(body.get("distance_to_requester"))
    if distance:
        parts.append(f"距离你 {distance} 格")
    health = _number_phrase(body.get("health"))
    if health:
        parts.append(f"生命 {health}")
    return "；".join(parts) + "。"


def _position_phrase(state: dict[str, Any]) -> str:
    x = _number_phrase(state.get("x"))
    y = _number_phrase(state.get("y"))
    z = _number_phrase(state.get("z"))
    if not all((x, y, z)):
        return ""
    dimension = str(state.get("dimension") or "").removeprefix("minecraft:")
    if dimension:
        return f"{dimension} 坐标 ({x}, {y}, {z})"
    return f"坐标 ({x}, {y}, {z})"


def _number_phrase(value: Any) -> str:
    if value is None:
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.2f}".rstrip("0").rstrip(".")


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
    return is_body_follow_request(message)


def _offline_stop_intent(message: str) -> bool:
    return is_body_stop_request(message)


def _offline_chop_tree_intent(message: str) -> bool:
    return is_body_chop_tree_request(message)


def _offline_memory_write_intent(message: str) -> bool:
    return _contains_any(message, {"记住", "帮我记", "保存", "记录"}) and not _offline_memory_search_intent(message)


def _offline_memory_search_intent(message: str) -> bool:
    return is_memory_recall_request(message)


def _offline_memory_content(message: str) -> str:
    content = message.strip()
    for prefix in ("请", "帮我", "麻烦你"):
        if content.startswith(prefix):
            content = content[len(prefix) :].strip()
    for marker in ("记住", "保存", "记录"):
        if marker in content:
            content = content.split(marker, 1)[1].strip(" ：:，,。")
            break
    return content or message.strip()


def _offline_memory_query(message: str) -> str:
    query = message.strip()
    for marker in ("你还记得", "还记得", "记得我", "记不记得"):
        if marker in query:
            query = query.split(marker, 1)[1].strip(" ：:，,。?？")
            break
    for suffix in ("吗", "么", "呢"):
        if query.endswith(suffix):
            query = query[: -len(suffix)].strip(" ：:，,。?？")
            break
    return query or message.strip()


def _deepseek_error_message(exc: DeepSeekError) -> str:
    if exc.status in {401, 402}:
        return f"Mina 的 DeepSeek API 当前不可用：HTTP {exc.status}。请检查 API key 或余额。"
    if exc.status in {429, 500, 503}:
        return f"Mina 暂时被 DeepSeek 限流或服务繁忙：HTTP {exc.status}。稍后再试。"
    return f"Mina 调用 DeepSeek 时遇到错误：HTTP {exc.status}。"
