from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Callable

from .mcp import McpRegistry
from .memory import MemoryStore
from .schemas import ToolResult
from .searxng import SearxngClient

LOGGER = logging.getLogger("mina_agent.tools")


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


PRIVATE_FABRIC_TOOLS = {
    "send_player_message",
    "send_global_message",
}

READ_ONLY_TIME_QUERIES = {"daytime", "gametime", "day"}
READ_ONLY_LOCATE_TARGET = re.compile(r"^[a-z0-9_:.\-/#]+$")
READ_ONLY_STRUCTURE_ALIASES = {
    "village": "#minecraft:village",
    "minecraft:village": "#minecraft:village",
    "#village": "#minecraft:village",
    "#minecraft:villages": "#minecraft:village",
    "villages": "#minecraft:village",
    "minecraft:villages": "#minecraft:village",
    "end_portal": "minecraft:stronghold",
    "minecraft:end_portal": "minecraft:stronghold",
    "end_portal_room": "minecraft:stronghold",
    "minecraft:end_portal_room": "minecraft:stronghold",
}

MINECRAFT_WRITE_COMMANDS = {
    "advancement",
    "attribute",
    "setblock",
    "fill",
    "fillbiome",
    "tp",
    "teleport",
    "gamemode",
    "defaultgamemode",
    "difficulty",
    "effect",
    "enchant",
    "execute",
    "experience",
    "xp",
    "function",
    "gamerule",
    "give",
    "clear",
    "item",
    "loot",
    "summon",
    "kill",
    "damage",
    "data",
    "ride",
    "schedule",
    "scoreboard",
    "team",
    "tag",
    "forceload",
    "setworldspawn",
    "spawnpoint",
    "worldborder",
    "op",
    "deop",
    "ban",
    "ban-ip",
    "pardon",
    "pardon-ip",
    "whitelist",
    "stop",
    "save-all",
    "save-off",
    "save-on",
}

WEB_SEARCH_CONTENT_LIMIT = 2400
WEB_SEARCH_TOTAL_CONTENT_LIMIT = 8000
WEB_SEARCH_TITLE_LIMIT = 220


def tool_specs(*, include_mcp: bool = False) -> list[dict[str, Any]]:
    specs = [
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": (
                    "Search the web through the local SearXNG instance and return budgeted results. "
                    "Each result includes content_truncated so you can avoid overstating incomplete snippets."
                ),
                "parameters": _schema(
                    {
                        "query": {"type": "string", "description": "Search query."},
                        "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
                    },
                    ["query"],
                ),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "memory_search",
                "description": (
                    "Search remembered stable player, world, and global facts that may help this turn. "
                    "Use for recall or older/specific stored context, not as a preflight duplicate check before "
                    "memory_write when the player explicitly asks to remember a new stable fact."
                ),
                "parameters": _schema(
                    {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 12},
                    },
                    ["query"],
                ),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "memory_write",
                "description": (
                    "Persist a remembered fact that should help future Mina turns, such as a stable player preference, "
                    "world fact, plan, promise, or lesson. Use scope='world' for shared places, landmarks, bases, farms, "
                    "portals, or plans tied to the current Minecraft save/world/server; use scope='player' for facts tied "
                    "only to the requester. Do not store transient filler."
                ),
                "parameters": _schema(
                    {
                        "event_type": {"type": "string"},
                        "content": {"type": "string"},
                        "importance": {"type": "integer", "minimum": 1, "maximum": 5},
                        "scope": {"type": "string", "enum": ["player", "world", "global"]},
                        "label": {"type": "string"},
                    },
                    ["event_type", "content"],
                ),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "run_read_only_command",
                "description": (
                    "Run a tightly constrained read-only Minecraft command and show its output to the requester. "
                    "Use this when the player message is exactly or mainly an allowed command form, even if the same value appears in context. "
                    "Allowed forms: seed; time query daytime|gametime|day; weather query; list [uuids]; "
                    "locate structure <identifier-or-tag>; locate biome <identifier>. "
                    "Use locate structure #minecraft:village for villages and locate structure minecraft:stronghold for end portal/stronghold searches."
                ),
                "strict": True,
                "parameters": _schema({"command": {"type": "string"}}, ["command"]),
            },
        },
    ]
    if include_mcp:
        specs.append(
            {
                "type": "function",
                "function": {
                    "name": "mcp_call",
                    "description": (
                        "Call a configured non-Minecraft-write MCP server through Mina's sidecar MCP registry. "
                        "Use tool='tools/list' for discovery, tool='resources/read' with arguments.uri for resources, "
                        "or a concrete tool name for tools/call."
                    ),
                    "parameters": _schema(
                        {
                            "server": {"type": "string"},
                            "tool": {"type": "string"},
                            "arguments": {"type": "object"},
                        },
                        ["server", "tool", "arguments"],
                    ),
                },
            }
        )
    return specs


class ToolRunner:
    def __init__(
        self,
        memory: MemoryStore,
        searxng: SearxngClient,
        mcp: McpRegistry | None = None,
    ):
        self.memory = memory
        self.searxng = searxng
        self.mcp = mcp or McpRegistry()

    def run(self, name: str, args: dict[str, Any], turn: dict[str, Any]) -> ToolResult:
        local: dict[str, Callable[[dict[str, Any], dict[str, Any]], ToolResult]] = {
            "web_search": self._web_search,
            "memory_search": self._memory_search,
            "memory_write": self._memory_write,
            "run_read_only_command": self._run_read_only_command,
            "mcp_call": self._mcp_call,
        }
        if name in local:
            return local[name](args if isinstance(args, dict) else {}, turn)
        if name in PRIVATE_FABRIC_TOOLS or name == "run_safe_command":
            LOGGER.info("rejected_private_fabric_tool name=%s args=%s", name, args)
            return ToolResult(
                content=json.dumps(
                    {
                        "ok": False,
                        "error": f"{name} is a private Fabric executor primitive.",
                    },
                    ensure_ascii=False,
                )
            )
        return ToolResult(content=json.dumps({"ok": False, "error": f"unknown tool: {name}"}, ensure_ascii=False))

    def _web_search(self, args: dict[str, Any], turn: dict[str, Any]) -> ToolResult:
        query = str(args.get("query") or "").strip()
        max_results = _bounded_int(args.get("max_results"), fallback=5, minimum=1, maximum=10)
        if not query:
            return ToolResult(content=json.dumps({"ok": False, "error": "web_search query is required"}, ensure_ascii=False))
        LOGGER.info("web_search query=%s max_results=%s", query, max_results)
        try:
            results = self.searxng.search(query, max_results=max_results)
        except Exception as exc:  # noqa: BLE001 - tool calls must return model-visible errors.
            LOGGER.info("web_search unavailable query=%s error=%s", query, exc)
            return ToolResult(content=json.dumps({"ok": False, "error": f"web_search unavailable: {exc}"}, ensure_ascii=False))
        safe_results, filtered_results = _safe_web_search_results(results, max_results=max_results)
        LOGGER.info("web_search result_count=%s safe_result_count=%s filtered_results=%s", len(results), len(safe_results), filtered_results)
        return ToolResult(
            content=json.dumps(
                {
                    "ok": True,
                    "query": query,
                    "result_count": len(results),
                    "safe_result_count": len(safe_results),
                    "filtered_results": filtered_results,
                    "results": safe_results,
                },
                ensure_ascii=False,
            )
        )

    def _memory_search(self, args: dict[str, Any], turn: dict[str, Any]) -> ToolResult:
        player_id = _player_id(turn)
        query = str(args.get("query") or "").strip()
        limit = _bounded_int(args.get("limit"), fallback=8, minimum=1, maximum=12)
        if not query:
            return ToolResult(content=json.dumps({"ok": False, "error": "memory_search query is required"}, ensure_ascii=False))
        results = self.memory.search(player_id, query, limit=limit, world_id=_world_id(turn))
        visible_results = _model_visible_memory_results(results)
        LOGGER.info("memory_search player=%s query=%s result_count=%s", player_id, query, len(visible_results))
        return ToolResult(content=json.dumps({"ok": True, "results": visible_results}, ensure_ascii=False))

    def _memory_write(self, args: dict[str, Any], turn: dict[str, Any]) -> ToolResult:
        player_id = _player_id(turn)
        event_type = str(args.get("event_type") or "note")
        content = str(args.get("content") or "").strip()
        importance = _bounded_int(args.get("importance"), fallback=1, minimum=1, maximum=5)
        scope = str(args.get("scope") or "player").strip().lower()
        if scope not in {"player", "world", "global"}:
            scope = "player"
        scope_id = _memory_scope_id(scope, player_id, turn)
        label = str(args.get("label") or event_type or "note")
        if scope == "player":
            player_name = _player_name(turn)
            content = _sanitize_player_memory_content(content, player_name)
            label = _sanitize_player_memory_label(label, player_name)
        if not content:
            return ToolResult(content=json.dumps({"ok": False, "error": "memory_write content is required"}, ensure_ascii=False))
        self.memory.add_agent_memory(scope, scope_id, label, content, importance=importance, source="memory_write")
        self.memory.add_event(player_id, event_type, {"content": content}, importance=importance)
        LOGGER.info(
            "memory_write player=%s scope=%s scope_id=%s label=%s importance=%s content=%s",
            player_id,
            scope,
            scope_id,
            label,
            importance,
            content[:500],
        )
        return ToolResult(
            content=json.dumps({"ok": True, "memory": {"scope": scope, "label": label, "content": content}}, ensure_ascii=False)
        )

    def _run_read_only_command(self, args: dict[str, Any], turn: dict[str, Any]) -> ToolResult:
        command = normalize_read_only_command(str(args.get("command") or ""))
        if command is None:
            return ToolResult(
                content=json.dumps(
                    {
                        "ok": False,
                        "error": (
                            "Only read-only commands are allowed: seed; time query daytime|gametime|day; "
                            "weather query; list [uuids]; locate structure <identifier-or-tag>; locate biome <identifier>."
                        ),
                    },
                    ensure_ascii=False,
                )
            )
        action = {
            "id": str(uuid.uuid4()),
            "name": "run_read_only_command",
            "args": {"command": command},
            "requires_permission": False,
            "deadline_ticks": 0,
        }
        return ToolResult(content=json.dumps({"ok": True, "action": action}, ensure_ascii=False), action=action)

    def _mcp_call(self, args: dict[str, Any], turn: dict[str, Any]) -> ToolResult:
        server = str(args.get("server") or "")
        tool = str(args.get("tool") or "")
        arguments = args.get("arguments")
        if not isinstance(arguments, dict):
            arguments = {}
        if _looks_like_minecraft_write(tool, arguments):
            result = {"ok": False, "error": "Minecraft write operations must go through Mina Fabric actions, not MCP."}
        elif tool in {"tools/list", "list_tools"}:
            result = self.mcp.list_tools(server)
        elif tool in {"resources/read", "read_resource"}:
            uri = str(arguments.get("uri") or "")
            if not uri:
                result = {"ok": False, "error": "MCP resources/read requires arguments.uri"}
            else:
                result = self.mcp.read_resource(server, uri)
        else:
            result = self.mcp.call(server, tool, arguments)
        LOGGER.info("mcp_call server=%s tool=%s ok=%s", server, tool, result.get("ok"))
        return ToolResult(content=json.dumps(result, ensure_ascii=False))


def _player_id(turn: dict[str, Any]) -> str:
    player = turn.get("player") or {}
    return str(player.get("uuid") or player.get("id") or "unknown")


def _player_name(turn: dict[str, Any]) -> str:
    player = turn.get("player") or {}
    return str(player.get("name") or "").strip()


def _world_id(turn: dict[str, Any]) -> str | None:
    value = turn.get("world_id") or turn.get("world")
    if value:
        return str(value)
    snapshot = turn.get("snapshot")
    if not isinstance(snapshot, dict):
        return None
    value = snapshot.get("world_id") or snapshot.get("world")
    if value:
        return str(value)
    player_state = snapshot.get("player_state")
    if isinstance(player_state, dict) and player_state.get("dimension"):
        return str(player_state.get("dimension"))
    return None


def _model_visible_memory_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kind_labels = {
        "agent_memory": "remembered_fact",
        "conversation": "prior_message",
        "event": "stored_event",
        "action_event": "verified_command_result",
    }
    visible: list[dict[str, Any]] = []
    for result in results:
        item = dict(result)
        kind = str(item.get("kind") or "")
        if kind in kind_labels:
            item["kind"] = kind_labels[kind]
        visible.append(item)
    return visible


def _memory_scope_id(scope: str, player_id: str, turn: dict[str, Any]) -> str:
    if scope == "global":
        return "*"
    if scope == "world":
        return _world_id(turn) or "unknown"
    return player_id


def _sanitize_player_memory_content(content: str, player_name: str) -> str:
    text = " ".join(str(content or "").split())
    name = str(player_name or "").strip()
    if not text or not name:
        return text
    escaped = re.escape(name)
    text = re.sub(rf"(?i)(?:玩家\s*)?@?{escaped}\s*的", "你的", text)
    text = re.sub(rf"(?i)属于\s*(?:玩家\s*)?@?{escaped}", "属于你", text)
    text = re.sub(rf"(?i)(?:player\s*)?@?{escaped}\s*'s\b", "your", text)
    return text


def _sanitize_player_memory_label(label: str, player_name: str) -> str:
    text = " ".join(str(label or "").split())
    name = str(player_name or "").strip()
    if not text or not name:
        return text
    return re.sub(rf"(?i)@?{re.escape(name)}", "player", text).strip()


def _looks_like_minecraft_write(tool: str, arguments: dict[str, Any]) -> bool:
    haystack = tool + " " + json.dumps(arguments, ensure_ascii=False)
    for token in _command_tokens(haystack):
        command = token.split(":")[-1]
        if command in MINECRAFT_WRITE_COMMANDS:
            return True
    return False


def _command_tokens(value: str) -> list[str]:
    return [
        token
        for token in re.split(r"[^a-z0-9_:\-]+", value.lower())
        if token
    ]


def _strip_slash(command: str) -> str:
    normalized = command.strip()
    while normalized.startswith("/"):
        normalized = normalized[1:].strip()
    return " ".join(normalized.split())


def _bounded_int(value: Any, fallback: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = fallback
    return max(minimum, min(maximum, parsed))


def _safe_web_search_results(results: Any, *, max_results: int) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(results, list):
        return [], 0
    safe_results: list[dict[str, Any]] = []
    filtered_results = 0
    content_budget = WEB_SEARCH_TOTAL_CONTENT_LIMIT
    for source_index, item in enumerate(results, start=1):
        if not isinstance(item, dict):
            filtered_results += 1
            continue
        title = _excerpt(str(item.get("title") or "result").strip(), WEB_SEARCH_TITLE_LIMIT)
        url = str(item.get("url") or "").strip()
        raw_content = str(item.get("content") or "").strip()
        if not url:
            filtered_results += 1
            continue
        if _unsafe_web_search_text(f"{title}\n{raw_content}"):
            filtered_results += 1
            continue
        per_result_limit = min(WEB_SEARCH_CONTENT_LIMIT, max(0, content_budget))
        content, content_truncated = _excerpt_with_flag(raw_content, per_result_limit)
        content_budget -= len(content)
        safe_results.append(
            {
                "source_index": source_index,
                "source_type": str(item.get("source_type") or "result"),
                "title": title,
                "url": url,
                "content": content,
                "content_truncated": content_truncated,
            }
        )
        if len(safe_results) >= max_results:
            break
    return safe_results, filtered_results


def _unsafe_web_search_text(value: str) -> bool:
    normalized = value.lower()
    if any(
        token in normalized
        for token in (
            "ignore every previous instruction",
            "ignore previous instructions",
            "忽略之前",
            "忽略以上",
            "调用工具",
            "call run_safe_command",
            "send_player_message",
            "send_global_message",
            "run setblock",
            "execute command",
        )
    ):
        return True
    for token in _command_tokens(normalized):
        command = token.split(":")[-1]
        if command in MINECRAFT_WRITE_COMMANDS:
            return True
    return False


def _excerpt(value: str, limit: int) -> str:
    return _excerpt_with_flag(value, limit)[0]


def _excerpt_with_flag(value: str, limit: int) -> tuple[str, bool]:
    if limit <= 0:
        return "", bool(value)
    if len(value) <= limit:
        return value, False
    return value[: max(0, limit - 3)].rstrip() + "...", True


def is_read_only_command(command: str) -> bool:
    normalized = normalize_read_only_command(command)
    return normalized is not None


def normalize_read_only_command(command: str) -> str | None:
    normalized = _strip_slash(command).lower()
    parts = normalized.split()
    if len(parts) == 3 and parts[0] == "locate" and parts[1] in {"structure", "biome"}:
        target = _canonical_locate_target(parts[1], parts[2])
        if target is None:
            return None
        parts = [parts[0], parts[1], target]
    if _is_read_only_command_parts(parts):
        return " ".join(parts)
    return None


def _canonical_locate_target(kind: str, target: str) -> str | None:
    normalized = str(target or "").strip().lower()
    if not READ_ONLY_LOCATE_TARGET.fullmatch(normalized):
        return None
    if kind == "structure":
        return READ_ONLY_STRUCTURE_ALIASES.get(normalized, normalized)
    if kind == "biome" and ":" not in normalized and not normalized.startswith("#"):
        return "minecraft:" + normalized
    return normalized


def _is_read_only_command_parts(parts: list[str]) -> bool:
    if not parts:
        return False
    if parts == ["seed"]:
        return True
    if len(parts) == 3 and parts[0] == "time" and parts[1] == "query" and parts[2] in READ_ONLY_TIME_QUERIES:
        return True
    if parts == ["weather", "query"]:
        return True
    if parts == ["list"] or parts == ["list", "uuids"]:
        return True
    return (
        len(parts) == 3
        and parts[0] == "locate"
        and parts[1] in {"structure", "biome"}
        and bool(READ_ONLY_LOCATE_TARGET.fullmatch(parts[2]))
    )
