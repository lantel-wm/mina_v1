from __future__ import annotations

import json
import logging
import re
from typing import Any

from .config import Settings
from .context import build_messages, is_explicit_memory_write_request
from .deepseek import DeepSeekClient, DeepSeekError
from .memory import MemoryStore
from .policy import ResponsePolicyRuntime, is_tool_error, normalize_health_unit_claims
from .schemas import TurnResponse
from .tools import (
    ToolRunner,
    extract_requested_read_only_command,
    normalize_read_only_command,
    tool_specs,
)
from .turn_runtime import TurnRuntimeState

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

        literal_command = normalize_read_only_command(message)
        if literal_command:
            result = self.tools.run("run_read_only_command", {"command": literal_command}, turn)
            result_actions = _result_actions(result)
            status = "ok" if result_actions or not is_tool_error(result.content) else "error"
            self.memory.record_tool_call(
                request_id,
                "run_read_only_command",
                {"command": literal_command},
                {"content": result.content, "actions": result_actions},
                status,
            )
            if result_actions:
                content = _action_ack("run_read_only_command")
                self.memory.add_conversation(request_id, player_id, "assistant", content)
                self._debug(
                    "turn literal_read_only_command request_id=%s command=%s actions=%s",
                    request_id,
                    literal_command,
                    len(result_actions),
                )
                return TurnResponse(
                    messages=[{"target": "requester", "content": content}],
                    actions=result_actions,
                    debug={"literal_read_only_command": True},
                ).to_dict()
            self._debug("turn literal_read_only_command rejected request_id=%s command=%s", request_id, literal_command)
            return TurnResponse(
                messages=[{"target": "requester", "content": "这个命令不在 Mina 的只读命令白名单内。"}],
                debug={"literal_read_only_command": True, "literal_read_only_error": True},
            ).to_dict()

        requested_read_only_command = extract_requested_read_only_command(message)
        requested_memory_write = is_explicit_memory_write_request(message)
        snapshot_observation_request = _is_snapshot_observation_request(message, turn)
        if not self.deepseek.configured():
            fallback = "Mina sidecar is running, but MINA_API_KEY is not configured."
            self._debug("turn fallback request_id=%s reason=missing_api_key", request_id)
            self.memory.add_conversation(request_id, player_id, "assistant", fallback)
            return TurnResponse(messages=[{"target": "requester", "content": fallback}]).to_dict()

        state = TurnRuntimeState(request_id=request_id, player_id=player_id, messages=build_messages(turn, self.memory))
        policy = ResponsePolicyRuntime()
        try:
            for subturn in range(1, self.settings.max_tool_turns + 1):
                self._debug("model call request_id=%s subturn=%s messages=%s", request_id, subturn, len(state.messages))
                specs = tool_specs()
                try:
                    response = self.deepseek.chat(state.messages, tools=specs)
                    self.memory.record_model_call(
                        request_id=request_id,
                        subturn=subturn,
                        model=self.settings.model,
                        messages_count=len(state.messages),
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
                        messages_count=len(state.messages),
                        tools=_tool_spec_names(specs),
                        status="error",
                        error=f"HTTP {exc.status}: {_log_preview(exc.message, 1200)}",
                    )
                    raise
                state.usage = response.usage
                assistant_message = response.message
                state.append_model_message(assistant_message)
                tool_calls = assistant_message.get("tool_calls") or []
                self._debug(
                    "model response request_id=%s subturn=%s finish_reason=%s tool_calls=%s content=%s usage=%s",
                    request_id,
                    subturn,
                    response.finish_reason,
                    len(tool_calls),
                    _log_preview(str(assistant_message.get("content") or ""), 500),
                    state.usage,
                )
                if response.finish_reason != "tool_calls" or not tool_calls:
                    if requested_memory_write and not policy.memory_write_seen and subturn < self.settings.max_tool_turns:
                        state.messages.append({"role": "system", "content": _memory_write_repair_message()})
                        self._debug("turn repair request_id=%s reason=missing_memory_write_tool", request_id)
                        continue
                    if requested_read_only_command and not state.actions:
                        if subturn < self.settings.max_tool_turns:
                            state.messages.append(
                                {
                                    "role": "system",
                                    "content": _read_only_command_repair_message(requested_read_only_command),
                                }
                            )
                            self._debug(
                                "turn repair request_id=%s reason=missing_read_only_command_tool command=%s",
                                request_id,
                                requested_read_only_command,
                            )
                            continue
                        result = self.tools.run(
                            "run_read_only_command",
                            {"command": requested_read_only_command},
                            turn,
                        )
                        result_actions = state.collect_result_actions(result)
                        self.memory.record_tool_call(
                            request_id,
                            "run_read_only_command",
                            {"command": requested_read_only_command},
                            {"content": result.content, "actions": result_actions},
                            "ok" if result_actions or not is_tool_error(result.content) else "error",
                        )
                        if result_actions:
                            content = _action_ack("run_read_only_command")
                            self.memory.add_conversation(request_id, player_id, "assistant", content)
                            self._debug(
                                "turn command_contract_fallback request_id=%s command=%s actions=%s",
                                request_id,
                                requested_read_only_command,
                                len(result_actions),
                            )
                            return TurnResponse(
                                messages=[{"target": "requester", "content": content}],
                                actions=state.actions,
                                debug={
                                    "usage": state.usage,
                                    "tool_subturns": subturn,
                                    "read_only_command_contract_fallback": True,
                                },
                            ).to_dict()
                    review = policy.review_final_content(
                        str(assistant_message.get("content") or ""),
                        can_repair=subturn < self.settings.max_tool_turns,
                    )
                    if review.needs_repair:
                        state.messages.append({"role": "system", "content": review.repair_message})
                        self._debug("turn repair request_id=%s reason=%s", request_id, review.repair_reason)
                        continue
                    content = normalize_health_unit_claims(review.content, turn.get("snapshot"))
                    if content:
                        self.memory.add_conversation(request_id, player_id, "assistant", content)
                        self._debug("turn final request_id=%s messages=1 actions=%s", request_id, len(state.actions))
                        return TurnResponse(
                            messages=[{"target": "requester", "content": content}],
                            actions=state.actions,
                            debug={"usage": state.usage, "tool_subturns": subturn},
                        ).to_dict()
                    if state.actions:
                        content = "我开始执行。"
                        self.memory.add_conversation(request_id, player_id, "assistant", content)
                        self._debug("turn final request_id=%s messages=1 actions=%s content=execution_ack", request_id, len(state.actions))
                        return TurnResponse(
                            messages=[{"target": "requester", "content": content}],
                            actions=state.actions,
                            debug={"usage": state.usage, "tool_subturns": subturn},
                        ).to_dict()
                    companion_empty = _companion_empty_message(turn)
                    if companion_empty is not None:
                        if companion_empty:
                            self.memory.add_conversation(request_id, player_id, "assistant", companion_empty)
                            self._debug(
                                "turn final request_id=%s messages=1 actions=0 content=empty_companion_safety_fallback",
                                request_id,
                            )
                            return TurnResponse(
                                messages=[{"target": "requester", "content": companion_empty}],
                                debug={
                                    "usage": state.usage,
                                    "tool_subturns": subturn,
                                    "empty_companion_safety_fallback": True,
                                },
                            ).to_dict()
                        self._debug("turn final request_id=%s messages=0 actions=0 content=empty_companion_noop", request_id)
                        return TurnResponse(
                            messages=[],
                            debug={"usage": state.usage, "tool_subturns": subturn, "empty_companion_noop": True},
                        ).to_dict()

                    content = "我没有生成可执行回应，请换个说法或补充目标。"
                    self.memory.add_conversation(request_id, player_id, "assistant", content)
                    self._debug("turn final request_id=%s messages=1 actions=0 content=empty_model_fallback", request_id)
                    return TurnResponse(
                        messages=[{"target": "requester", "content": content}],
                        debug={"usage": state.usage, "tool_subturns": subturn, "empty_model_fallback": True},
                    ).to_dict()

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
                        _log_preview(json.dumps(args, ensure_ascii=False), 1200),
                    )
                    if requested_memory_write and name == "run_read_only_command" and not policy.memory_write_seen:
                        result_content = json.dumps(
                            {
                                "ok": False,
                                "error": (
                                    "This turn is an explicit memory-save request. Do not run Minecraft commands "
                                    "to verify or enrich it unless the player explicitly asked for verification. "
                                    "Call memory_write with the player's stable fact, or explain why it should not be saved."
                                ),
                            },
                            ensure_ascii=False,
                        )
                        state.invalid_tool_results += 1
                        self._debug(
                            "tool blocked request_id=%s subturn=%s name=%s reason=memory_write_contract",
                            request_id,
                            subturn,
                            name,
                        )
                        state.append_tool_observation(call.get("id"), result_content)
                        continue
                    if snapshot_observation_request and name == "run_read_only_command" and not requested_read_only_command:
                        result_content = json.dumps(
                            {
                                "ok": False,
                                "error": (
                                    "The current player/world status is already available in this turn's Minecraft snapshot. "
                                    "Do not run read-only commands for local status questions unless the player explicitly asks "
                                    "to execute a specific command. Answer directly from the current Minecraft context summary."
                                ),
                            },
                            ensure_ascii=False,
                        )
                        state.invalid_tool_results += 1
                        self._debug(
                            "tool blocked request_id=%s subturn=%s name=%s reason=snapshot_observation_contract",
                            request_id,
                            subturn,
                            name,
                        )
                        state.append_tool_observation(call.get("id"), result_content)
                        continue
                    result = self.tools.run(name, args, turn)
                    result_actions = state.collect_result_actions(result)
                    if result_actions:
                        state.invalid_tool_results = 0
                    elif is_tool_error(result.content):
                        state.invalid_tool_results += 1
                    else:
                        state.invalid_tool_results = 0
                        policy.note_successful_tool_result(name, result.content)
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
                        "ok" if result_actions or not is_tool_error(result.content) else "error",
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
                            len(state.actions),
                        )
                        return TurnResponse(
                            messages=response_messages,
                            actions=state.actions,
                            debug={"usage": state.usage, "tool_subturns": subturn, "action_barrier": True},
                        ).to_dict()
                    state.append_tool_observation(call.get("id"), result.content)
                    if state.invalid_tool_results >= 3:
                        content = "我还没有完成这步操作，因为连续几次工具调用缺少必要目标参数。我会先停下，避免误操作。"
                        if state.actions:
                            content = "我只请求了前面的准备动作；后续操作连续缺少必要目标参数，所以先停下，避免误操作。"
                        self.memory.add_conversation(request_id, player_id, "assistant", content)
                        self._debug("turn stopped_invalid_tools request_id=%s actions=%s", request_id, len(state.actions))
                        return TurnResponse(messages=[{"target": "requester", "content": content}], actions=state.actions).to_dict()
        except DeepSeekError as exc:
            content = _deepseek_error_message(exc)
            self._debug("turn deepseek_error request_id=%s status=%s message=%s", request_id, exc.status, _log_preview(exc.message, 1200))
            return TurnResponse(messages=[{"target": "requester", "content": content}], actions=state.actions).to_dict()

        content = "工具调用轮次达到上限，我先停下，避免误操作。"
        if state.actions:
            content = "我已经请求执行前面的动作，但后续工具调用轮次达到上限，先停在这里。"
        self._debug("turn max_tool_turns request_id=%s actions=%s", request_id, len(state.actions))
        return TurnResponse(messages=[{"target": "requester", "content": content}], actions=state.actions, debug={"usage": state.usage}).to_dict()

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


def _result_actions(result: Any) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if isinstance(getattr(result, "action", None), dict):
        actions.append(result.action)
    result_actions = getattr(result, "actions", None)
    if isinstance(result_actions, list):
        actions.extend(action for action in result_actions if isinstance(action, dict))
    return actions


def _companion_empty_message(turn: dict[str, Any]) -> str | None:
    if str(turn.get("trigger") or "") != "companion_tick":
        return None
    snapshot = turn.get("snapshot") if isinstance(turn.get("snapshot"), dict) else {}
    player_state = snapshot.get("player_state") if isinstance(snapshot.get("player_state"), dict) else {}
    health = _float_value(player_state.get("health"))
    max_health = _float_value(player_state.get("max_health")) or 20.0
    if health is not None and health <= max(6.0, max_health * 0.5):
        return (
            "你的生命值偏低（"
            f"{_format_number(health)}/{_format_number(max_health)}点，"
            f"约{_format_number(health / 2.0)}/{_format_number(max_health / 2.0)}颗心），"
            "先注意安全并尽快恢复。"
        )
    nearby_entities = snapshot.get("nearby_entities") if isinstance(snapshot.get("nearby_entities"), list) else []
    for entity in nearby_entities:
        if not isinstance(entity, dict) or entity.get("category") != "hostile":
            continue
        entity_type = str(entity.get("type") or "敌对生物")
        distance = _float_value(entity.get("distance"))
        if distance is not None:
            return f"附近有 {entity_type}，距离约 {_format_number(distance)} 格，注意安全。"
        return f"附近有 {entity_type}，注意安全。"
    return ""


def _float_value(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _log_preview(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "...[log preview only; full tool content preserved]"


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


def _is_snapshot_observation_request(message: str, turn: dict[str, Any]) -> bool:
    normalized = " ".join(str(message or "").lower().split())
    if not normalized:
        return False
    snapshot = turn.get("snapshot") if isinstance(turn.get("snapshot"), dict) else {}
    player_state = snapshot.get("player_state") if isinstance(snapshot.get("player_state"), dict) else {}
    world_state = snapshot.get("world_state") if isinstance(snapshot.get("world_state"), dict) else {}
    nearby_entities = snapshot.get("nearby_entities") if isinstance(snapshot.get("nearby_entities"), list) else []
    if not player_state and not world_state and not nearby_entities:
        return False
    explicit_execution_markers = (
        "执行",
        "运行",
        "调用",
        "用命令",
        "命令输出",
        "execute",
        "run ",
        "call ",
        "command output",
    )
    if any(marker in normalized for marker in explicit_execution_markers):
        return False
    cjk_status_markers = (
        "我的坐标",
        "我坐标",
        "当前坐标",
        "我的位置",
        "当前位置",
        "我在哪",
        "我在哪里",
        "状态",
        "生命",
        "血量",
        "饥饿",
        "天气",
        "时间",
        "第几天",
        "几点",
        "安全吗",
        "怪物",
        "敌对",
        "附近安全吗",
    )
    if any(marker in normalized for marker in cjk_status_markers):
        return True
    english_status_markers = (
        "where am i",
        "my coordinates",
        "current coordinates",
        "my position",
        "current position",
        "status",
        "health",
        "hunger",
        "weather",
        "time",
        "day",
        "nearby danger",
        "hostile",
        "monster",
    )
    return any(re.search(rf"\b{re.escape(marker)}\b", normalized) for marker in english_status_markers)


def _read_only_command_repair_message(command: str) -> str:
    return (
        "The current user message explicitly asks Mina to execute this allowlisted read-only Minecraft command now: "
        f"{command}. Do not answer from snapshot context, recent messages, or prior command results. "
        "Call run_read_only_command with exactly this command."
    )


def _memory_write_repair_message() -> str:
    return (
        "The player explicitly asked Mina to remember stable information for future turns, "
        "but no memory_write tool has succeeded in this turn. Call memory_write now with the player's fact. "
        "Do not call run_read_only_command, web_search, or mcp_call just to verify or enrich it unless the player explicitly asked for verification."
    )


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
