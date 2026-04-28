from __future__ import annotations

import json
from typing import Any

from .memory import MemoryStore


SYSTEM_PROMPT = """You are Mina, an in-game Minecraft companion agent.
You speak naturally and concisely in the player's language.
You can use tools to search the web, remember important player context, run constrained read-only Minecraft commands, inspect task status, and start or stop high-level body tasks.
Explicit body-control commands are normally routed to a dedicated body subagent before this prompt. If one still reaches you, keep control high-level and avoid step-by-step body micromanagement.
The body is only for execution, not companionship. Companionship happens through messages.
When calling a tool, put every required argument in the tool JSON arguments. Do not put coordinates, selectors, commands, or modes only in prose.
If you do not know a required argument, do not call that tool yet.
Never call low-level movement, look, attack, body_chain, or write-capable server command tools. For body execution, call start_body_task with a supported high-level task_type: chop_tree or follow_player. Do not offer unsupported block placement, building, or arbitrary block-breaking body tasks. For Minecraft command output, use run_read_only_command only, with one exact allowed form: seed; time query daytime|gametime|day; weather query; list; list uuids; locate structure <identifier>.
If the player explicitly asks you to call a private or low-level tool by name, refuse that tool request. Do not start a substitute high-level body task in the same turn; ask the player for a supported high-level goal instead.
Never claim a Minecraft action succeeded until task_status or the system context says the task is completed.
If a body task was started, say Mina has started trying the task and will continue based on real observations.
Respect permissions: if a tool says permission denied, explain briefly and offer a safe alternative.
Do not request banned server governance commands such as op, deop, stop, ban, whitelist, or save control unless the server config explicitly allows them.
"""


def build_messages(turn: dict[str, Any], memory: MemoryStore) -> list[dict[str, Any]]:
    player = turn.get("player") or {}
    player_id = str(player.get("uuid") or "unknown")
    snapshot = turn.get("snapshot") or {}
    recent = memory.recent_conversation(player_id, limit=12)

    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if recent:
        messages.append(
            {
                "role": "system",
                "content": "Recent player conversation memory:\n"
                + "\n".join(f"{row['role']}: {row['content']}" for row in recent),
            }
        )
    relevant = build_relevant_memory_summary(turn, memory, player_id)
    if relevant:
        messages.append({"role": "system", "content": relevant})
    messages.append({"role": "system", "content": "Current Minecraft context summary:\n" + build_context_summary(turn)})
    target_summary = build_target_summary(snapshot)
    if target_summary:
        messages.append({"role": "system", "content": target_summary})
    user_content = str(turn.get("message") or "").strip()
    if not user_content:
        user_content = "This is a companion tick. If there is no important, timely reason to speak, respond with an empty string."
    messages.append({"role": "user", "content": user_content})
    return messages


def build_relevant_memory_summary(turn: dict[str, Any], memory: MemoryStore, player_id: str) -> str:
    message = str(turn.get("message") or "").strip()
    snapshot = turn.get("snapshot") if isinstance(turn.get("snapshot"), dict) else {}
    active_task = snapshot.get("active_task") if isinstance(snapshot.get("active_task"), dict) else {}
    skill_names = {skill for skill in (_intent_skill(message), str(active_task.get("type") or "")) if skill}
    query = " ".join(part for part in [message, *sorted(skill_names)] if part).strip()
    lines: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    if query:
        for item in memory.search(player_id, query, limit=6):
            kind = str(item.get("kind") or "memory")
            label = str(item.get("label") or "")
            content = _compact_memory_content(item.get("content"))
            key = (kind, label, content)
            if content and key not in seen:
                seen.add(key)
                lines.append(f"- {kind}/{label}: {content}")
    for skill_name in sorted(skill_names):
        for reflection in memory.recent_skill_reflections(skill_name, limit=3):
            content = _compact_memory_content(reflection.get("reflection"))
            key = ("skill_reflection", skill_name, content)
            if content and key not in seen:
                seen.add(key)
                lines.append(f"- skill_reflection/{skill_name}: {content}")
    if not lines:
        return ""
    return "Relevant memory and skill reflections:\n" + "\n".join(lines[:8])


def build_target_summary(snapshot: dict[str, Any]) -> str:
    lines: list[str] = []
    body_state = snapshot.get("body_state")
    if isinstance(body_state, dict):
        lines.append("Mina body state: " + json.dumps(_compact_body_state(body_state), ensure_ascii=False))
    nearby_blocks = snapshot.get("nearby_blocks")
    blocks = _flatten_blocks(nearby_blocks)
    if blocks:
        lines.append("Nearby body-task targets. Use start_body_task; the sidecar skill runtime owns movement, look, and attack details:")
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
    body_state = snapshot.get("body_state") if isinstance(snapshot.get("body_state"), dict) else {}
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
            "food": player_state.get("food"),
            "dimension": player_state.get("dimension"),
            "x": player_state.get("x"),
            "y": player_state.get("y"),
            "z": player_state.get("z"),
        },
        "body_state": _compact_body_state(body_state),
        "candidate_logs": [_compact_block_target(block) for block in logs],
        "nearby_hostiles": hostile,
        "active_task": snapshot.get("active_task"),
    }
    return json.dumps(payload, ensure_ascii=False)


def _flatten_blocks(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        blocks: list[dict[str, Any]] = []
        for nested in value.values():
            blocks.extend(_flatten_blocks(nested))
        return blocks
    return []


def _compact_body_state(body_state: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "online",
        "username",
        "name",
        "x",
        "y",
        "z",
        "yaw",
        "pitch",
        "distance_to_requester",
        "selected_item",
        "targeted_block",
        "target_block",
        "active_task",
    )
    return {key: body_state.get(key) for key in keys if key in body_state}


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


def _intent_skill(message: str) -> str:
    normalized = message.lower()
    if any(token in normalized for token in ("砍树", "砍木头", "伐木", "chop tree", "cut tree", "chop wood")):
        return "chop_tree"
    if any(token in normalized for token in ("跟随", "跟着", "follow")):
        return "follow_player"
    return ""


def _compact_memory_content(value: Any, limit: int = 260) -> str:
    if isinstance(value, str):
        content = value
    else:
        content = json.dumps(value, ensure_ascii=False)
    content = " ".join(content.split())
    if len(content) <= limit:
        return content
    return content[: limit - 14].rstrip() + "...<truncated>"
