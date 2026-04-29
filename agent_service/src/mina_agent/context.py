from __future__ import annotations

import json
from typing import Any

from .memory import MemoryStore


SYSTEM_PROMPT = """You are Mina, an in-game Minecraft companion agent.
You speak naturally and concisely in the player's language.
Minecraft chat is plain text: do not use Markdown formatting, code fences, emoji, decorative bullets, or long lists. Default to one or two short sentences unless the player explicitly asks for detail.
You are the decision maker for each player-facing turn. Use the provided Minecraft context directly for local player/world observation, and call tools only when the request needs external knowledge, persistent memory, configured MCP, or approved command output.
You can use tools to search the web, remember important player context, and run constrained read-only Minecraft commands.
Use web_search for requests to search, look up, verify current or external knowledge, or use wiki/web/internet/联网/搜索/查一下 wording. Do not use web_search for casual chat or local Minecraft state from the current context.
When answering from web_search results, preserve exact source values such as markers, version numbers, coordinates, URLs, and item names. Do not replace an exact value with a generic label.
Use memory_write when the player asks you to remember, save, or record a preference, plan, promise, base location, or important fact. For any request asking what you remember or whether you still remember something, you must call memory_search in this turn before answering; do not answer from recent conversation context alone.
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
    recall_request = is_memory_recall_request(user_content)
    recent = memory.recent_conversation(player_id, limit=12)

    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if recent and not recall_request:
        messages.append(
            {
                "role": "system",
                "content": "Recent player conversation memory:\n"
                + "\n".join(f"{row['role']}: {row['content']}" for row in recent),
            }
        )
    elif recent and recall_request:
        messages.append(
            {
                "role": "system",
                "content": (
                    "Recent conversation memory is intentionally omitted for this memory recall request. "
                    "Call memory_search with the relevant key terms before answering."
                ),
            }
        )
    if recall_request:
        messages.append(
            {
                "role": "system",
                "content": (
                    "This user message is a memory recall request. You must call memory_search in this turn "
                    "before any final answer, even if you think you know the answer."
                ),
            }
        )
    else:
        relevant = build_relevant_memory_summary(turn, memory, player_id)
        if relevant:
            messages.append({"role": "system", "content": relevant})
    messages.append({"role": "system", "content": "Current Minecraft context summary:\n" + build_context_summary(turn)})
    target_summary = build_target_summary(snapshot)
    if target_summary:
        messages.append({"role": "system", "content": target_summary})
    if not user_content:
        user_content = "这是一次 companion tick。如果没有重要、及时的理由要提醒玩家，请回复空字符串；如果需要提醒，请使用玩家最近使用的语言。"
    messages.append({"role": "user", "content": user_content})
    return messages


def is_memory_recall_request(message: str) -> bool:
    normalized = message.lower()
    return any(token in normalized for token in ("你还记得", "还记得", "记得我", "记不记得", "记忆里", "记忆中"))


def build_relevant_memory_summary(turn: dict[str, Any], memory: MemoryStore, player_id: str) -> str:
    message = str(turn.get("message") or "").strip()
    query = message
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
    if not lines:
        return ""
    return "Relevant memory:\n" + "\n".join(lines[:8])


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


def _compact_memory_content(value: Any, limit: int = 260) -> str:
    if isinstance(value, str):
        content = value
    else:
        content = json.dumps(value, ensure_ascii=False)
    content = " ".join(content.split())
    if len(content) <= limit:
        return content
    return content[: limit - 14].rstrip() + "...<truncated>"
