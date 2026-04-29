from __future__ import annotations

import json
from typing import Any

from .memory import MemoryStore


SYSTEM_PROMPT = """You are Mina, an in-game Minecraft companion agent.
You speak naturally and concisely in the player's language.
Minecraft chat is plain text: do not use Markdown formatting, code fences, emoji, decorative bullets, or long lists. Default to one or two short sentences unless the player explicitly asks for detail.
Do not narrate internal process such as "I will check", "let me look", or "我来看看"; answer with the useful result directly.
Minecraft snapshot health and max_health are health points, not UI hearts: 20 health points = 10 hearts, and 4 health points = 2 hearts. If you mention hearts, convert from health points correctly; otherwise say health points.
You are the decision maker for each player-facing turn. Use the provided Minecraft context directly for local player/world observation, and call tools only when the request needs external knowledge, persistent memory, configured MCP, or approved command output.
You can use tools to search the web, remember important player context, and run constrained read-only Minecraft commands.
Use web_search for requests to search, look up, verify current or external knowledge, or use wiki/web/internet/联网/搜索/查一下 wording. Do not use web_search for casual chat or local Minecraft state from the current context.
When answering from web_search results, preserve exact source values such as markers, version numbers, coordinates, URLs, and item names. Do not replace an exact value with a generic label.
Memory is for your future decisions, like Codex AGENTS.md or Claude Code CLAUDE.md style context. Use loaded agent memory directly when it is relevant, but treat it as internal context, not a topic list. Do not volunteer stored player facts, base locations, coordinates, preferences, or old plans unless the player asks about them or they directly change the answer. Use memory_write to save stable player preferences, world facts, plans, promises, or lessons that should help future turns, even when the player did not use the word remember. Do not save transient chat filler. Use memory_search when loaded memory is insufficient or when you need older, specific stored context.
Recent player messages are conversational continuity only. They are not stable memory, verified command output, or fresh external knowledge. If the player asks to search, verify, or look up current/external information, use web_search even if a similar answer appears in recent context.
Recent verified Minecraft command/action results are only for answering follow-up questions about prior outputs. If the player asks you to execute, run, call, or query an allowed read-only Minecraft command now, call run_read_only_command even when the same command appears in recent results.
You do not control a separate Minecraft character and cannot move, attack, mine, place blocks, or run write-capable server commands. For questions such as "你在哪里", "你在做什么", or "where are you", answer as a text agent and use the current player/world context if useful.
When calling a tool, put every required argument in the tool JSON arguments. Do not put coordinates, selectors, commands, or modes only in prose.
If you do not know a required argument, do not call that tool yet.
Never call private Fabric executor primitives, low-level movement/attack tools, write-capable server command tools, or any tool that is not listed in the tool schema. For Minecraft command output, use run_read_only_command only, with one exact allowed form: seed; time query daytime|gametime|day; weather query; list; list uuids; locate structure <identifier>; locate biome <identifier>.
If the player explicitly asks you to call a private or low-level tool by name, refuse that tool request.
Respect permissions: if a tool says permission denied, explain briefly and offer a safe alternative.
Do not request banned server governance commands such as op, deop, stop, ban, whitelist, or save control unless the server config explicitly allows them.
When refusing a write-capable or banned command, do not provide an executable command line, command recipe, or "you can run this yourself" workaround.
For companion ticks, inspect the current Minecraft context and speak only for timely, useful alerts. Return an empty string when there is nothing worth interrupting for.
"""


def build_messages(turn: dict[str, Any], memory: MemoryStore) -> list[dict[str, Any]]:
    player = turn.get("player") or {}
    player_id = str(player.get("uuid") or "unknown")
    snapshot = turn.get("snapshot") or {}
    user_content = str(turn.get("message") or "").strip()
    recent = memory.recent_conversation(player_id, limit=12)
    agent_memory = memory.agent_context(player_id, world_id=_world_id(snapshot), limit=10, max_chars=1600)
    recent_action_results = memory.recent_action_results_for_player(player_id, limit=4)

    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if agent_memory:
        messages.append({"role": "system", "content": "Agent memory loaded for this turn:\n" + _render_agent_memory(agent_memory)})
    recent_player_messages = _recent_player_messages(recent)
    if recent_player_messages:
        messages.append(
            {
                "role": "system",
                "content": "Recent player messages for continuity only:\n" + "\n".join(recent_player_messages),
            }
        )
    action_result_context = _render_recent_action_results(recent_action_results)
    if action_result_context:
        messages.append(
            {
                "role": "system",
                "content": "Recent verified Minecraft command/action results:\n" + action_result_context,
            }
        )
    command_execution_hint = _command_execution_request_hint(user_content)
    if command_execution_hint:
        messages.append({"role": "system", "content": command_execution_hint})
    memory_write_hint = _memory_write_request_hint(user_content)
    if memory_write_hint:
        messages.append({"role": "system", "content": memory_write_hint})
    messages.append({"role": "system", "content": "Current Minecraft context summary:\n" + build_context_summary(turn)})
    target_summary = build_target_summary(snapshot)
    if target_summary:
        messages.append({"role": "system", "content": target_summary})
    if not user_content:
        user_content = _companion_tick_prompt(turn)
    messages.append({"role": "user", "content": user_content})
    return messages


def _render_agent_memory(memories: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in memories:
        scope = item.get("scope")
        label = item.get("label")
        content = " ".join(str(item.get("content") or "").split())
        if content:
            lines.append(f"- {scope}/{label}: {content}")
    return "\n".join(lines)


def _recent_player_messages(recent: list[dict[str, Any]], limit: int = 6) -> list[str]:
    messages: list[str] = []
    for row in recent:
        if row.get("role") != "user":
            continue
        content = " ".join(str(row.get("content") or "").split())
        if content:
            messages.append("user: " + content[:260])
    return messages[-limit:]


def _render_recent_action_results(action_results: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for row in action_results[-4:]:
        payload = _json_object(row.get("payload_json"))
        action_name = str(row.get("action_name") or payload.get("name") or payload.get("action_name") or "action")
        status = str(payload.get("status") or "unknown")
        command_results = payload.get("command_results")
        output_parts: list[str] = []
        if isinstance(command_results, list):
            for command_result in command_results[:3]:
                if not isinstance(command_result, dict):
                    continue
                command = str(command_result.get("command") or "").strip()
                outputs = command_result.get("outputs")
                rendered_outputs = _string_items(outputs, limit=3)
                if command or rendered_outputs:
                    output_parts.append(
                        "command="
                        + (command or "<unknown>")
                        + " output="
                        + " | ".join(rendered_outputs)
                    )
        error = str(payload.get("error") or "").strip()
        if error:
            output_parts.append("error=" + error)
        if not output_parts:
            continue
        summary = "; ".join(output_parts)
        lines.append(
            f"- request={row.get('request_id')} action={action_name} status={status} "
            f"success={payload.get('command_success')} {summary[:700]}"
        )
    return "\n".join(lines)


def _command_execution_request_hint(user_content: str) -> str:
    normalized = " ".join(user_content.lower().replace("/", " / ").split())
    if not normalized:
        return ""
    execution_markers = ("执行", "运行", "调用", "用命令", "run ", "execute ", "call ")
    command_markers = (
        " seed",
        " time query",
        " weather query",
        " list",
        " locate ",
        " setblock",
        " fill",
        " tp",
        " teleport",
        " gamemode",
        " give",
        " summon",
        " kill",
        " /",
    )
    padded = " " + normalized + " "
    if not any(marker in normalized for marker in execution_markers):
        return ""
    if not any(marker in padded for marker in command_markers):
        return ""
    return (
        "Current user message is an explicit Minecraft command execution request. "
        "Do not answer it from the current snapshot, recent conversation, or prior action results. "
        "Either call run_read_only_command with the exact allowlisted command requested, "
        "or refuse if the requested command is not read-only and allowlisted."
    )


def _memory_write_request_hint(user_content: str) -> str:
    normalized = " ".join(user_content.lower().split())
    if not normalized:
        return ""
    write_markers = (
        "请记住",
        "帮我记住",
        "记住：",
        "记住:",
        "记下",
        "保存一下",
        "remember that",
        "remember:",
        "save this",
    )
    recall_markers = ("记得", "还记得", "remember where", "do you remember", "recall")
    if any(marker in normalized for marker in recall_markers):
        return ""
    if not any(marker in normalized for marker in write_markers):
        return ""
    return (
        "Current user message explicitly asks you to save stable memory for future Mina turns. "
        "Call memory_write before claiming the information was remembered or saved. "
        "If the information should not be saved, answer without saying it was remembered."
    )


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        payload = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _string_items(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        text = " ".join(str(item).split())
        if text:
            items.append(text[:220])
        if len(items) >= limit:
            break
    return items


def _world_id(snapshot: dict[str, Any]) -> str | None:
    value = snapshot.get("world_id") or snapshot.get("world")
    if value:
        return str(value)
    player_state = snapshot.get("player_state")
    if isinstance(player_state, dict) and player_state.get("dimension"):
        return str(player_state.get("dimension"))
    return None


def build_target_summary(snapshot: dict[str, Any]) -> str:
    lines: list[str] = []
    nearby_blocks = snapshot.get("nearby_blocks")
    blocks = _flatten_blocks(nearby_blocks)
    if blocks:
        lines.append("Nearby notable blocks for observation:")
        for block in blocks[:12]:
            if not isinstance(block, dict):
                continue
            compact = _compact_block_target(block)
            block_pos = f"block=({compact.get('x')},{compact.get('y')},{compact.get('z')})"
            lines.append(
                f"- {compact.get('category')} {compact.get('block')} {block_pos} "
                f"distance={compact.get('distance')} approach_available={compact.get('approach_available')}"
            )
    return "\n".join(lines)


def build_context_summary(turn: dict[str, Any]) -> str:
    snapshot = turn.get("snapshot") or {}
    player_state = snapshot.get("player_state") if isinstance(snapshot.get("player_state"), dict) else {}
    permissions = turn.get("permissions") or {}
    nearby_entities = snapshot.get("nearby_entities") if isinstance(snapshot.get("nearby_entities"), list) else []
    nearby_blocks = _flatten_blocks(snapshot.get("nearby_blocks"))
    logs = [block for block in nearby_blocks if block.get("category") == "log"][:12]
    hostile = [entity for entity in nearby_entities if entity.get("category") == "hostile"][:8]
    payload = {
        "trigger": turn.get("trigger"),
        "player": turn.get("player") or {},
        "permissions": permissions,
        "player_state": {
            "health": player_state.get("health"),
            "max_health": player_state.get("max_health"),
            "health_points": player_state.get("health"),
            "max_health_points": player_state.get("max_health"),
            "health_hearts": _half_health(player_state.get("health")),
            "max_health_hearts": _half_health(player_state.get("max_health")),
            "food": player_state.get("food"),
            "dimension": player_state.get("dimension"),
            "x": player_state.get("x"),
            "y": player_state.get("y"),
            "z": player_state.get("z"),
        },
        "candidate_logs": [_compact_block_target(block) for block in logs],
        "nearby_hostiles": hostile,
    }
    return json.dumps(payload, ensure_ascii=False)


def _companion_tick_prompt(turn: dict[str, Any]) -> str:
    reason = _companion_tick_alert_reason(turn)
    if reason:
        return (
            "这是一次 companion tick。当前 Minecraft context 已显示及时提醒理由："
            + reason
            + "。请用玩家最近使用的语言简短提醒玩家，不要调用工具。"
        )
    return "这是一次 companion tick。如果没有重要、及时的理由要提醒玩家，请回复空字符串；如果需要提醒，请使用玩家最近使用的语言。"


def _companion_tick_alert_reason(turn: dict[str, Any]) -> str:
    snapshot = turn.get("snapshot") if isinstance(turn.get("snapshot"), dict) else {}
    player_state = snapshot.get("player_state") if isinstance(snapshot.get("player_state"), dict) else {}
    health = _float_value(player_state.get("health"))
    max_health = _float_value(player_state.get("max_health")) or 20.0
    if health is not None and health <= max(6.0, max_health * 0.5):
        return (
            "玩家生命值较低（"
            f"{_format_number(health)}/{_format_number(max_health)} health points，"
            f"约 {_format_number(health / 2.0)}/{_format_number(max_health / 2.0)} 颗心）"
        )
    nearby_entities = snapshot.get("nearby_entities") if isinstance(snapshot.get("nearby_entities"), list) else []
    hostiles = [entity for entity in nearby_entities if isinstance(entity, dict) and entity.get("category") == "hostile"]
    if hostiles:
        nearest = hostiles[0]
        entity_type = str(nearest.get("type") or "hostile entity")
        distance = _float_value(nearest.get("distance"))
        if distance is not None:
            return f"附近有敌对生物 {entity_type}，距离约 {_format_number(distance)} 格"
        return f"附近有敌对生物 {entity_type}"
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


def _half_health(value: Any) -> float | int | None:
    parsed = _float_value(value)
    if parsed is None:
        return None
    half = parsed / 2.0
    return int(half) if half.is_integer() else half


def _flatten_blocks(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        blocks: list[dict[str, Any]] = []
        for nested in value.values():
            blocks.extend(_flatten_blocks(nested))
        return blocks
    return []


def _compact_block_target(block: dict[str, Any]) -> dict[str, Any]:
    return {
        "block": block.get("block"),
        "category": block.get("category"),
        "x": block.get("x"),
        "y": block.get("y"),
        "z": block.get("z"),
        "distance": block.get("distance"),
        "approach_available": all(key in block for key in ("approach_x", "approach_y", "approach_z")),
    }
