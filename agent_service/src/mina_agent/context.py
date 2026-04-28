from __future__ import annotations

import json
from typing import Any

from .memory import MemoryStore


SYSTEM_PROMPT = """You are Mina, an in-game Minecraft companion agent.
You speak naturally and concisely in the player's language.
You can use tools to search the web, remember important player context, run constrained read-only Minecraft commands, inspect task status, and start or stop high-level body tasks.
The body is only for execution, not companionship. Companionship happens through messages.
When calling a tool, put every required argument in the tool JSON arguments. Do not put coordinates, selectors, commands, or modes only in prose.
If you do not know a required argument, do not call that tool yet.
Never call low-level movement, look, attack, body_chain, or write-capable server command tools. For body execution, call start_body_task with a high-level task_type such as chop_tree or follow_player. For Minecraft command output, use run_read_only_command only.
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
    messages.append({"role": "system", "content": "Current Minecraft context summary:\n" + build_context_summary(turn)})
    target_summary = build_target_summary(snapshot)
    if target_summary:
        messages.append({"role": "system", "content": target_summary})
    user_content = str(turn.get("message") or "").strip()
    if not user_content:
        user_content = "This is a companion tick. If there is no important, timely reason to speak, respond with an empty string."
    messages.append({"role": "user", "content": user_content})
    return messages


def build_target_summary(snapshot: dict[str, Any]) -> str:
    lines: list[str] = []
    body_state = snapshot.get("body_state")
    if isinstance(body_state, dict):
        lines.append("Mina body state: " + json.dumps(body_state, ensure_ascii=False))
    nearby_blocks = snapshot.get("nearby_blocks")
    blocks = _flatten_blocks(nearby_blocks)
    if blocks:
        lines.append("Nearby block targets with usable coordinates. Use approach for move_to_position and center for look_at_position:")
        for block in blocks[:20]:
            if not isinstance(block, dict):
                continue
            category = block.get("category")
            name = block.get("block")
            block_pos = f"block=({block.get('x')},{block.get('y')},{block.get('z')})"
            center = f"center=({block.get('center_x')},{block.get('center_y')},{block.get('center_z')})"
            approach = ""
            if all(key in block for key in ("approach_x", "approach_y", "approach_z")):
                approach = f" approach=({block.get('approach_x')},{block.get('approach_y')},{block.get('approach_z')})"
            lines.append(f"- {category} {name} {block_pos} {center}{approach}")
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
        "body_state": body_state,
        "candidate_logs": logs,
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
