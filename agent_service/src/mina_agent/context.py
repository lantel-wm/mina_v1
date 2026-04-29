from __future__ import annotations

import json
from typing import Any

from .memory import MemoryStore
from .policy import UNSAFE_WRITE_REFUSAL


SYSTEM_PROMPT = """Identity:
- You are Mina, a text-only Minecraft companion in chat.
- You do not control a separate Minecraft character: no moving, mining, placing, item use, teleporting, or write-capable server commands.

Chat style:
- Match the player's language. If the player writes Chinese, answer in Chinese even when memory, command output, or search snippets contain English.
- Be natural and concise.
- Minecraft chat is plain text: no Markdown, code fences, emoji, bullets, or long lists.
- Default to one or two short sentences unless the player explicitly asks for detail.
- Do not narrate internal process such as "I will check", "let me look", or "我来看看"; answer with the useful result directly.
- Do not mention internal section/tool names, prompt labels, or context source labels in answers; say "I remember..." instead of naming storage.
- Address the player as "you" or "你" by default. Do not use the Minecraft username as greeting/filler unless asked about names or reporting a player-name command output.
- Snapshot health/max_health are health points, not UI hearts: 20 points = 10 hearts, 4 points = 2 hearts.

Decision order:
1. Allowed read-only command requests must call run_read_only_command; never answer them from snapshot or recent results.
2. Questions about the player's base, home, saved places, projects, preferences, plans, promises, or earlier statements are memory questions. Answer from loaded remembered facts or memory_search; do not mix in current location unless asked. Do not call memory_write for recall unless new or changed stable information is provided.
3. For local player/world observations, answer directly from observed Minecraft state and only the fields asked for. Do not call tools or append unrelated snapshot details.
4. For greetings, casual chat, or "what can you do" capability questions, answer generally. Do not volunteer snapshot details or stored personal facts unless asked.
5. For current or external knowledge, web/wiki/internet/search wording, or requests to verify outside information, call web_search. Do not use web_search for casual chat or local Minecraft state from the current context.
6. For stable preferences, world facts, plans, promises, or lessons useful later, use memory_write. Do not save filler or re-save loaded facts. For player-scoped memories, phrase facts as about "you/你" or neutrally; do not include the current Minecraft username unless that username is the fact being saved.
7. Use loaded remembered facts only when directly relevant. Treat memory as historical context for future decisions, not proof of current world state.
8. For questions about remembered or stored context, answer only the relevant remembered fact. Do not append coordinates, safety, biome, weather, time, inventory, entities, command offers, or search offers unless asked.
9. Use memory_search only when loaded memory is insufficient or the player asks for older specific stored context.

Tool policy:
- Use only tools listed for this turn.
- Tool calls must include every required JSON argument.
- If you do not know a required argument, ask a short clarifying question instead of calling the tool.
- For Minecraft command output, use run_read_only_command only, with the exact allowed forms listed in the tool selection reminder.
- Never invent or call movement, mining, attack, item-use, placement, private executor, write-command, or unlisted tools.
- If a tool says permission denied or unavailable, explain briefly and offer a safe alternative.

Safety:
- Refuse private, low-level, write-capable, or banned server command requests.
- Banned governance commands include op, deop, stop, ban, whitelist, and save-control commands.
- When refusing a write-capable or banned command, do not provide an executable command line, command recipe, or "you can run this yourself" workaround.

Answer authority:
- Current observed Minecraft state is the freshest source for local player/world state.
- Recent verified command/action results are authoritative only for follow-ups about those outputs.
- If asked for exact/raw/original/complete command output or 原样/完整输出字符串/只回答输出字符串, return only the verified output string: no explanation, prefix, suffix, quotes, or code formatting.
- Recent player messages are conversational continuity only, not current instructions, stable memory, verified command output, or fresh external knowledge.
- When answering from web_search results, preserve exact source values such as markers, version numbers, coordinates, URLs, and item names. Do not replace an exact value with a generic label.
"""

COMMAND_POLICY_REMINDER = (
    "Tool selection reminder: if the player message is exactly, mainly, or asks to execute/run/query "
    "weather query, time query day, seed, list, list uuids, locate structure <id>, or locate biome <id>, "
    "call run_read_only_command every time; direct text answers from snapshot or previous results are invalid."
)


def build_messages(turn: dict[str, Any], memory: MemoryStore, *, mcp_available: bool = False) -> list[dict[str, Any]]:
    player = turn.get("player") or {}
    player_id = str(player.get("uuid") or "unknown")
    snapshot = turn.get("snapshot") or {}
    user_content = str(turn.get("message") or "").strip()
    recent = memory.recent_conversation(player_id, limit=12)
    agent_memory = memory.agent_context(player_id, world_id=_world_id(snapshot), limit=10, max_chars=1600)
    recent_action_results = memory.recent_action_results_for_player(player_id, limit=4)

    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    turn_policy = _turn_policy_section(turn, user_content, mcp_available=mcp_available)
    if turn_policy:
        messages.append({"role": "system", "content": turn_policy})
    write_refusal_hint = _write_command_refusal_hint(user_content)
    if write_refusal_hint:
        messages.append({"role": "system", "content": write_refusal_hint})
    messages.append({"role": "system", "content": "Observed Minecraft state:\n" + build_context_summary(turn)})
    target_summary = build_target_summary(snapshot)
    if target_summary:
        messages.append({"role": "system", "content": target_summary})
    if agent_memory:
        messages.append({"role": "system", "content": "Remembered facts:\n" + _render_agent_memory(agent_memory)})
    recent_player_messages = (
        [] if str(turn.get("trigger") or "") == "companion_tick" else _recent_player_messages(recent)
    )
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
    messages.append({"role": "system", "content": COMMAND_POLICY_REMINDER})
    if not user_content:
        user_content = _companion_tick_prompt(turn)
    messages.append({"role": "user", "content": user_content})
    return messages


def _turn_policy_section(turn: dict[str, Any], user_content: str, *, mcp_available: bool = False) -> str:
    sections: list[str] = []
    if str(turn.get("trigger") or "") == "companion_tick":
        sections.append(
            "Companion tick policy:\n"
            "- Use observed Minecraft state only.\n"
            "- Do not call tools.\n"
            "- Address the player as 你/you; do not prefix the Minecraft username.\n"
            "- Speak only for timely, useful alerts. Return an empty string when nothing is worth interrupting the player."
        )
    if _mentions_mcp(user_content):
        if mcp_available:
            sections.append(
                "MCP policy for this turn:\n"
                "- MCP servers are configured, so you may discuss MCP or use mcp_call if the requested configured server/tool is relevant.\n"
                "- Do not use MCP to perform Minecraft write operations or bypass Mina's command policy.\n"
                "- If the requested MCP server/tool is unavailable, say so briefly."
            )
        else:
            sections.append(
                "MCP policy for this turn:\n"
                "- No MCP servers are configured for this Mina instance.\n"
                "- Answer briefly that MCP is unavailable here; do not invent configured MCP servers or tools."
            )
    return "\n\n".join(sections)


def _mentions_mcp(user_content: str) -> bool:
    normalized = str(user_content or "").lower()
    return "mcp" in normalized or "模型上下文协议" in normalized


def _render_agent_memory(memories: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in memories:
        scope = item.get("scope")
        label = item.get("label")
        content = " ".join(str(item.get("content") or "").split())
        if content:
            lines.append(f"- {scope}/{label}: {content}")
    return "\n".join(lines)


def _recent_player_messages(recent: list[dict[str, Any]], limit: int = 4, max_chars: int = 180) -> list[str]:
    messages: list[str] = []
    for row in recent:
        if row.get("role") != "user":
            continue
        content = " ".join(str(row.get("content") or "").split())
        if content:
            messages.append("user: " + content[:max_chars])
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


def _write_command_refusal_hint(user_content: str) -> str:
    normalized = " ".join(str(user_content or "").lower().replace("/", " / ").split())
    if not normalized:
        return ""
    write_markers = (
        " setblock",
        " fill",
        " fillbiome",
        " clone",
        " place ",
        " tp",
        " teleport",
        " gamemode",
        " gamerule",
        " give",
        " summon",
        " kill",
        " clear",
        " execute",
        " op",
        " deop",
        " ban",
        " ban-ip",
        " whitelist",
        " stop",
        " save-all",
        " save-off",
        " save-on",
        "删掉",
        "删除",
        "放置",
        "传送",
        "改成",
    )
    padded = " " + normalized + " "
    if not any(marker in padded or marker in normalized for marker in write_markers):
        return ""
    return (
        "Current user message asks for a Minecraft write-capable, low-level, or banned command/action. "
        "Refuse directly; do not call tools. Do not repeat the requested command name, coordinates, selector, "
        "syntax, command whitelist, or workaround. For Chinese, reply exactly: "
        f"{UNSAFE_WRITE_REFUSAL}"
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
    world_state = snapshot.get("world_state") if isinstance(snapshot.get("world_state"), dict) else {}
    permissions = turn.get("permissions") or {}
    nearby_entities = snapshot.get("nearby_entities") if isinstance(snapshot.get("nearby_entities"), list) else []
    nearby_blocks = _flatten_blocks(snapshot.get("nearby_blocks"))
    logs = [block for block in nearby_blocks if block.get("category") == "log"][:12]
    hostile = [entity for entity in nearby_entities if entity.get("category") == "hostile"][:8]
    player_context: dict[str, Any] = turn.get("player") or {}
    if str(turn.get("trigger") or "") == "companion_tick":
        player_context = {"present": bool(player_context)}
    payload = {
        "trigger": turn.get("trigger"),
        "player": player_context,
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
        "world_state": {
            "day_time": world_state.get("day_time"),
            "day_count": world_state.get("day_count"),
            "difficulty": world_state.get("difficulty"),
            "raining": world_state.get("raining"),
            "thundering": world_state.get("thundering"),
            "weather": _weather_label(world_state),
            "dimension": world_state.get("dimension"),
            "seed": world_state.get("seed"),
            "online_players": world_state.get("online_players"),
        },
        "candidate_logs": [_compact_block_target(block) for block in logs],
        "nearby_hostiles": hostile,
    }
    return json.dumps(payload, ensure_ascii=False)


def _companion_tick_prompt(turn: dict[str, Any]) -> str:
    reason = _companion_tick_alert_reason(turn)
    if reason:
        return (
            "这是一次被动提醒检查。当前观察状态显示及时提醒理由："
            + reason
            + "。请用玩家最近使用的语言简短提醒玩家，不要调用工具。"
        )
    return "这是一次被动提醒检查。如果没有重要、及时的理由要提醒玩家，请回复空字符串；如果需要提醒，请使用玩家最近使用的语言。"


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


def _weather_label(world_state: dict[str, Any]) -> str | None:
    if not world_state:
        return None
    if world_state.get("thundering") is True:
        return "thunder"
    if world_state.get("raining") is True:
        return "rain"
    if world_state.get("raining") is False or world_state.get("thundering") is False:
        return "clear"
    return None


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
