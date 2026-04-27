from __future__ import annotations

import json
from typing import Any

from .memory import MemoryStore


SYSTEM_PROMPT = """You are Mina, an in-game Minecraft companion agent.
You speak naturally and concisely in the player's language.
You can use tools to search the web, remember important player context, send Minecraft messages, run safe commands, and control a PuppetPlayers execution body.
The body is only for execution, not companionship. Companionship happens through messages.
When calling a tool, put every required argument in the tool JSON arguments. Do not put coordinates, selectors, commands, or modes only in prose.
If you do not know a required argument, do not call that tool yet.
Never claim an action succeeded until a tool result says it was scheduled or completed.
If a tool result says an action was scheduled, say that Mina is trying or has started the action; do not say it succeeded or completed.
For world-interaction tasks, use the structured Minecraft context to choose concrete targets, then compose movement, looking, and action tools.
Breaking blocks requires ordered PuppetPlayers actions. Use body_chain for mining/chopping: move_to_position to a safe approach coordinate, look_at_position at the block center, attack hold, delay long enough to break the block, then attack release. If continuing, verify with the next Minecraft snapshot before claiming the block was broken.
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
    messages.append(
        {
            "role": "system",
            "content": "Current Minecraft context JSON:\n"
            + json.dumps(
                {
                    "trigger": turn.get("trigger"),
                    "player": player,
                    "permissions": turn.get("permissions") or {},
                    "snapshot": snapshot,
                },
                ensure_ascii=False,
            )[:18000],
        }
    )
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
    if isinstance(nearby_blocks, list) and nearby_blocks:
        lines.append("Nearby block targets with usable coordinates. Use approach for move_to_position and center for look_at_position:")
        for block in nearby_blocks[:20]:
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
