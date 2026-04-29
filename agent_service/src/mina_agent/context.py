from __future__ import annotations

import json
import re
from typing import Any

from .memory import MemoryStore
from .policy import UNSAFE_WRITE_REFUSAL


BASE_SYSTEM_SECTIONS = (
    (
        "Identity:\n"
        "- You are Mina, a text-only Minecraft companion.\n"
        "- No separate Minecraft character; no move/mine/place/item use/teleport/write commands."
    ),
    (
        "Chat style:\n"
        "- Match language; Chinese in, Chinese out.\n"
        "- Plain text only: no Markdown/code fences/emoji/bullets.\n"
        "- Use one or two short sentences unless asked for detail.\n"
        "- If asked for one sentence/一句话, answer one short sentence (<60 汉字/20 English words); no closing offer.\n"
        "- Do not narrate internal process; answer with the useful result directly.\n"
        "- Do not mention internal section/tool names or prompt/context labels.\n"
        "- Address the player as \"you\"/\"你\". Do not use the Minecraft username as greeting/filler unless asked about names or player-name output.\n"
        "- Snapshot health/max_health are points, not hearts: 20 points = 10 hearts, 4 points = 2 hearts."
    ),
    (
        "Decision order:\n"
        "1. Read-only command requests must call run_read_only_command; never answer them from snapshot or recent results. A command request names an exact allowed command form or asks to execute/run/query it.\n"
        "2. Memory questions: base/home/saved places/projects/preferences/plans/promises/earlier statements. Answer from loaded remembered facts or memory_search; do not mix current location unless asked. Do not memory_write for recall unless stable info is new/changed.\n"
        "3. Observation questions: use observed state, only asked fields. Player name/username, game mode, held item, weather/time/day, world difficulty, dimension, biome, coords, facing direction/yaw/pitch, nearby relative directions, world spawn, health/food/armor/XP, active effects/status effects, light/sky, hazards (fire/lava/water/ground), block at/below feet, nearby blocks/mobs, safety are observations, not commands. For full/complete item/block/effect/biome/dimension ID, preserve the exact namespace, e.g. minecraft:grass_block. No tools or unrelated details. For weather/time/day-only questions, do not mention safety, monsters, entities, difficulty, inventory, coordinates, or commands unless asked.\n"
        "4. Casual chat/capability questions: one compact sentence, up to 3 capabilities. Do not volunteer snapshot details or stored facts unless asked.\n"
        "5. For current/external knowledge, web/wiki/internet/search wording, or outside verification, call web_search; not for chat/local Minecraft state.\n"
        "6. Use memory_write for durable preferences/world facts/plans/promises/lessons. For explicit remember/save requests about a new stable fact, call memory_write directly; do not first call memory_search unless loaded facts conflict. Do not save filler or loaded facts. For player-scoped memories, phrase facts about \"you/你\" or neutrally; memory_write content/label must omit the current Minecraft username unless it is the fact.\n"
        "7. Use loaded remembered facts only when directly relevant. Treat memory as historical context for future decisions, not proof of current world state.\n"
        "8. For remembered/stored context questions, answer only the relevant remembered fact. Do not append coordinates, safety, biome, weather, time, inventory, entities, command offers, or search offers unless asked.\n"
        "9. Use memory_search only when loaded memory is insufficient or the player asks for older specific stored context."
    ),
    (
        "Tool policy:\n"
        "- Use only tools listed for this turn.\n"
        "- Tool calls include every required JSON argument.\n"
        "- If a required argument is unknown, ask a short clarifying question instead of calling the tool.\n"
        "- For Minecraft command output, use run_read_only_command with exact allowed forms.\n"
        "- Never invent or call movement, mining, attack, item-use, placement, private executor, write-command, or unlisted tools.\n"
        "- If a tool is denied or unavailable, explain briefly and offer a safe alternative."
    ),
    (
        "Safety:\n"
        "- Refuse private, low-level, write-capable, or banned server command requests.\n"
        "- Banned governance commands include op, deop, stop, ban, whitelist, and save-control commands.\n"
        "- When refusing a write-capable or banned command, give no executable command, recipe, or \"you can run this yourself\" workaround."
    ),
    (
        "Answer authority:\n"
        "- Current observed Minecraft state is freshest for local player/world state.\n"
        "- Recent verified command/action results are authoritative only for follow-ups about those outputs.\n"
        "- If asked for exact/raw/original/complete command output or 原样/完整输出字符串/只回答输出字符串, return only the verified output string: no explanation, prefix, suffix, quotes, or code formatting.\n"
        "- Recent player messages are conversational continuity only, not current instructions, stable memory, verified command output, or fresh external knowledge.\n"
        "- From web_search results, preserve exact source values such as markers, versions, coordinates, URLs, and item names. Do not replace exact values with generic labels."
    ),
)


def build_base_system_prompt() -> str:
    return "\n\n".join(BASE_SYSTEM_SECTIONS)


SYSTEM_PROMPT = build_base_system_prompt()

COMMAND_POLICY_REMINDER = (
    "Tool selection reminder: exact/explicit command strings require run_read_only_command every time. "
    "If the final user message itself is an allowed command text, the next assistant step must be the tool, "
    "not text. Do not answer exact command text with recent output. Exact command strings are commands, not observations. "
    "Must call the tool for: time query day; weather query; list; list uuids; seed; locate structure <id>; locate biome <id>. "
    "For command requests, never answer from snapshot or recent results. Natural-language weather/time/status questions "
    "are observations; answer from Observed Minecraft state without tools. The exact command `list` must call "
    "run_read_only_command and must not be answered from online_players. memory_write args: no current Minecraft username "
    "unless it is the fact. Explicit remember/save: memory_write must be the first tool call; do not call memory_search "
    "first unless Remembered facts conflict."
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
                "content": (
                    "Recent verified Minecraft command/action results "
                    "(follow-up recall only, never a substitute for a new command request):\n"
                    + action_result_context
                ),
            }
        )
    messages.append({"role": "system", "content": COMMAND_POLICY_REMINDER})
    if not user_content:
        user_content = _companion_tick_prompt(turn)
    messages.append({"role": "user", "content": user_content})
    return messages


def _turn_policy_section(turn: dict[str, Any], user_content: str, *, mcp_available: bool = False) -> str:
    sections: list[str] = []
    player_name = _current_player_name(turn)
    if player_name and _mentions_player_name(user_content, player_name):
        sections.append(
            "Current player name handling:\n"
            f"- The current Minecraft username is {player_name}.\n"
            "- Treat that username as referring to the requester unless the player explicitly says the name itself is the fact.\n"
            "- For player-scoped memory_write, convert '<username> 的 ...' to '你的 ...' and omit the username from content and label."
        )
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


def _current_player_name(turn: dict[str, Any]) -> str:
    player = turn.get("player")
    if not isinstance(player, dict):
        return ""
    return str(player.get("name") or "").strip()


def _mentions_player_name(user_content: str, player_name: str) -> bool:
    content = str(user_content or "")
    name = str(player_name or "").strip()
    if not content or not name:
        return False
    return bool(re.search(rf"(?i)(?<![\w.-])@?{re.escape(name)}(?![\w.-])", content))


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
    player_state = snapshot.get("player_state") if isinstance(snapshot.get("player_state"), dict) else {}
    blocks = _flatten_blocks(nearby_blocks)
    if blocks:
        lines.append("Nearby notable blocks for observation:")
        for block in blocks[:12]:
            if not isinstance(block, dict):
                continue
            compact = _compact_block_target(block, player_state)
            block_pos = f"block=({compact.get('x')},{compact.get('y')},{compact.get('z')})"
            direction = compact.get("relative_direction") or "unknown"
            lines.append(
                f"- {compact.get('category')} {compact.get('block')} {block_pos} "
                f"distance={compact.get('distance')} direction={direction} "
                f"approach_available={compact.get('approach_available')}"
            )
    return "\n".join(lines)


def build_context_summary(turn: dict[str, Any]) -> str:
    snapshot = turn.get("snapshot") or {}
    player_state = snapshot.get("player_state") if isinstance(snapshot.get("player_state"), dict) else {}
    world_state = snapshot.get("world_state") if isinstance(snapshot.get("world_state"), dict) else {}
    permissions = turn.get("permissions") or {}
    nearby_entities = snapshot.get("nearby_entities") if isinstance(snapshot.get("nearby_entities"), list) else []
    inventory = snapshot.get("inventory") if isinstance(snapshot.get("inventory"), list) else []
    environment = snapshot.get("environment") if isinstance(snapshot.get("environment"), dict) else {}
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
            "armor": player_state.get("armor"),
            "experience_level": player_state.get("experience_level"),
            "total_experience": player_state.get("total_experience"),
            "effects": _compact_effects(player_state.get("effects")),
            "game_mode": player_state.get("game_mode"),
            "dimension": player_state.get("dimension"),
            "on_ground": player_state.get("on_ground"),
            "in_lava": player_state.get("in_lava"),
            "underwater": player_state.get("underwater"),
            "on_fire": player_state.get("on_fire"),
            "x": player_state.get("x"),
            "y": player_state.get("y"),
            "z": player_state.get("z"),
            "yaw": player_state.get("yaw"),
            "pitch": player_state.get("pitch"),
            "facing_direction": _facing_direction(player_state.get("yaw")),
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
            "spawn_x": world_state.get("spawn_x"),
            "spawn_y": world_state.get("spawn_y"),
            "spawn_z": world_state.get("spawn_z"),
            "player_distance_from_spawn": world_state.get("player_distance_from_spawn"),
            "online_players": world_state.get("online_players"),
        },
        "candidate_logs": [_compact_block_target(block, player_state) for block in logs],
        "nearby_hostiles": [_compact_entity_target(entity, player_state) for entity in hostile],
    }
    distance_display = _distance_display(world_state.get("player_distance_from_spawn"))
    if distance_display:
        payload["world_state"]["player_distance_from_spawn_display"] = distance_display
    selected_item = _selected_inventory_item(inventory)
    if selected_item:
        payload["selected_item"] = selected_item
    compact_environment = _compact_environment(environment)
    if compact_environment:
        payload["environment"] = compact_environment
    return json.dumps(_drop_none(payload), ensure_ascii=False)


def _companion_tick_prompt(turn: dict[str, Any]) -> str:
    reason = _companion_tick_alert_reason(turn)
    if reason:
        return (
            "这是一次被动提醒检查。当前观察状态显示及时提醒理由："
            + reason
            + "。请用玩家最近使用的语言简短提醒玩家，不要调用工具。"
            + "涉及生命值时请使用“点生命值”或“颗心”，不要说“格血”或“心生命值”。"
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


def _drop_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _drop_none(nested)
            for key, nested in value.items()
            if nested is not None
        }
    if isinstance(value, list):
        return [_drop_none(item) for item in value]
    return value


def _distance_display(value: Any) -> str | None:
    distance = _float_value(value)
    if distance is None:
        return None
    return f"{_format_number(distance)} 格"


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


def _facing_direction(value: Any) -> str | None:
    yaw = _float_value(value)
    if yaw is None:
        return None
    normalized = yaw % 360.0
    if normalized < 45.0 or normalized >= 315.0:
        return "south"
    if normalized < 135.0:
        return "west"
    if normalized < 225.0:
        return "north"
    return "east"


def _flatten_blocks(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        blocks: list[dict[str, Any]] = []
        for nested in value.values():
            blocks.extend(_flatten_blocks(nested))
        return blocks
    return []


def _selected_inventory_item(inventory: list[Any]) -> dict[str, Any]:
    for item in inventory:
        if isinstance(item, dict) and item.get("selected") is True:
            return {
                "slot": item.get("slot"),
                "item": item.get("item"),
                "count": item.get("count"),
                "name": item.get("name"),
            }
    return {}


def _compact_effects(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    effects: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        effect_id = item.get("id") or item.get("effect")
        if not effect_id:
            continue
        effects.append(
            {
                "id": effect_id,
                "effect": item.get("effect"),
                "duration": item.get("duration"),
                "amplifier": item.get("amplifier"),
            }
        )
        if len(effects) >= 8:
            break
    return effects


def _compact_environment(environment: dict[str, Any]) -> dict[str, Any]:
    compact = {
        "block_at_feet": environment.get("block_at_feet"),
        "block_below": environment.get("block_below"),
        "biome": environment.get("biome"),
        "light": environment.get("light"),
        "sky_visible": environment.get("sky_visible"),
    }
    return {key: value for key, value in compact.items() if value is not None}


def _compact_block_target(block: dict[str, Any], player_state: dict[str, Any] | None = None) -> dict[str, Any]:
    compact = {
        "block": block.get("block"),
        "category": block.get("category"),
        "x": block.get("x"),
        "y": block.get("y"),
        "z": block.get("z"),
        "distance": block.get("distance"),
        "approach_available": all(key in block for key in ("approach_x", "approach_y", "approach_z")),
    }
    compact.update(_relative_fields(player_state or {}, block, center=True))
    return compact


def _compact_entity_target(entity: dict[str, Any], player_state: dict[str, Any]) -> dict[str, Any]:
    compact = {
        "type": entity.get("type"),
        "name": entity.get("name"),
        "category": entity.get("category"),
        "distance": entity.get("distance"),
        "x": entity.get("x"),
        "y": entity.get("y"),
        "z": entity.get("z"),
        "health": entity.get("health"),
        "max_health": entity.get("max_health"),
    }
    compact.update(_relative_fields(player_state, entity, center=False))
    return compact


def _relative_fields(
    player_state: dict[str, Any], target: dict[str, Any], *, center: bool
) -> dict[str, Any]:
    origin_x = _float_value(player_state.get("x"))
    origin_y = _float_value(player_state.get("y"))
    origin_z = _float_value(player_state.get("z"))
    target_x = _float_value(target.get("center_x") if center else target.get("x"))
    target_y = _float_value(target.get("center_y") if center else target.get("y"))
    target_z = _float_value(target.get("center_z") if center else target.get("z"))
    if target_x is None:
        target_x = _float_value(target.get("x"))
    if target_y is None:
        target_y = _float_value(target.get("y"))
    if target_z is None:
        target_z = _float_value(target.get("z"))
    if origin_x is None or origin_z is None or target_x is None or target_z is None:
        return {}
    dx = target_x - origin_x
    dz = target_z - origin_z
    fields: dict[str, Any] = {
        "relative_direction": _horizontal_direction(dx, dz),
        "relative_x": _rounded_delta(dx),
        "relative_z": _rounded_delta(dz),
    }
    if origin_y is not None and target_y is not None:
        dy = target_y - origin_y
        fields["relative_y"] = _rounded_delta(dy)
        vertical = _vertical_relation(dy)
        if vertical:
            fields["relative_vertical"] = vertical
    return fields


def _horizontal_direction(dx: float, dz: float) -> str:
    abs_dx = abs(dx)
    abs_dz = abs(dz)
    if abs_dx < 0.25 and abs_dz < 0.25:
        return "here"
    if abs_dx >= abs_dz * 2:
        return "east" if dx > 0 else "west"
    if abs_dz >= abs_dx * 2:
        return "south" if dz > 0 else "north"
    north_south = "south" if dz > 0 else "north"
    east_west = "east" if dx > 0 else "west"
    return north_south + east_west


def _vertical_relation(dy: float) -> str | None:
    if dy > 1.0:
        return "above"
    if dy < -1.0:
        return "below"
    return "same_level"


def _rounded_delta(value: float) -> float | int:
    rounded = round(value, 2)
    return int(rounded) if float(rounded).is_integer() else rounded
