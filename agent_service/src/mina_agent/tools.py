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
from .tasks import SkillRuntime

LOGGER = logging.getLogger("mina_agent.tools")


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


# These are private Fabric executor actions. The model must not call them
# directly; SkillRuntime emits them as observed, resumable steps.
FABRIC_ACTION_TOOLS = {
    "send_player_message",
    "send_global_message",
    "body_spawn",
    "body_move_to_position",
    "body_move_to_entity",
    "body_move_to_requester",
    "body_look_at_position",
    "body_look_at_requester",
    "body_move_to",
    "body_look_at",
    "body_attack",
    "body_use",
    "body_chain",
    "body_swap_slot",
    "body_stop",
}

BODY_CONTROL_TOOLS = {"start_body_task", "stop_body_task", "task_status"}
BODY_CONTROL_DISABLED_ERROR = (
    "Puppet/body control is temporarily disabled; Mina now focuses on chat, knowledge/search, "
    "read-only command execution, and player/world state observation"
)

READ_ONLY_TIME_QUERIES = {"daytime", "gametime", "day"}
READ_ONLY_LOCATE_TARGET = re.compile(r"^[a-z0-9_:.\-/#]+$")

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


def tool_specs() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the web through the local SearXNG instance and return concise results.",
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
                "description": "Search the current player's memories and stable world facts.",
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
                "description": "Persist a useful player preference, plan, promise, base location, or important event.",
                "parameters": _schema(
                    {
                        "event_type": {"type": "string"},
                        "content": {"type": "string"},
                        "importance": {"type": "integer", "minimum": 1, "maximum": 5},
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
                    "Allowed forms: seed; time query daytime|gametime|day; weather query; list [uuids]; "
                    "locate structure <identifier>; locate biome <identifier>."
                ),
                "strict": True,
                "parameters": _schema({"command": {"type": "string"}}, ["command"]),
            },
        },
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
        },
    ]


class ToolRunner:
    def __init__(
        self,
        memory: MemoryStore,
        searxng: SearxngClient,
        mcp: McpRegistry | None = None,
        skills: SkillRuntime | None = None,
    ):
        self.memory = memory
        self.searxng = searxng
        self.mcp = mcp or McpRegistry()
        self.skills = skills or SkillRuntime(memory)

    def run(self, name: str, args: dict[str, Any], turn: dict[str, Any]) -> ToolResult:
        local: dict[str, Callable[[dict[str, Any], dict[str, Any]], ToolResult]] = {
            "web_search": self._web_search,
            "memory_search": self._memory_search,
            "memory_write": self._memory_write,
            "start_body_task": self._start_body_task,
            "stop_body_task": self._stop_body_task,
            "task_status": self._task_status,
            "run_read_only_command": self._run_read_only_command,
            "mcp_call": self._mcp_call,
        }
        if name in local:
            return local[name](args if isinstance(args, dict) else {}, turn)
        if name in FABRIC_ACTION_TOOLS or name == "run_safe_command":
            LOGGER.info("rejected_private_fabric_tool name=%s args=%s", name, args)
            return ToolResult(
                content=json.dumps(
                    {
                        "ok": False,
                        "error": f"{name} is a private executor primitive and body control is temporarily disabled.",
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
        LOGGER.info("web_search result_count=%s", len(results))
        return ToolResult(content=json.dumps({"ok": True, "results": results}, ensure_ascii=False))

    def _memory_search(self, args: dict[str, Any], turn: dict[str, Any]) -> ToolResult:
        player_id = _player_id(turn)
        query = str(args.get("query") or "").strip()
        limit = _bounded_int(args.get("limit"), fallback=8, minimum=1, maximum=12)
        if not query:
            return ToolResult(content=json.dumps({"ok": False, "error": "memory_search query is required"}, ensure_ascii=False))
        results = self.memory.search(player_id, query, limit=limit)
        LOGGER.info("memory_search player=%s query=%s result_count=%s", player_id, query, len(results))
        return ToolResult(content=json.dumps({"ok": True, "results": results}, ensure_ascii=False))

    def _memory_write(self, args: dict[str, Any], turn: dict[str, Any]) -> ToolResult:
        player_id = _player_id(turn)
        event_type = str(args.get("event_type") or "note")
        content = str(args.get("content") or "").strip()
        importance = _bounded_int(args.get("importance"), fallback=1, minimum=1, maximum=5)
        if not content:
            return ToolResult(content=json.dumps({"ok": False, "error": "memory_write content is required"}, ensure_ascii=False))
        self.memory.add_event(player_id, event_type, {"content": content}, importance=importance)
        LOGGER.info("memory_write player=%s event_type=%s importance=%s content=%s", player_id, event_type, importance, content[:500])
        return ToolResult(content=json.dumps({"ok": True}, ensure_ascii=False))

    def _start_body_task(self, args: dict[str, Any], turn: dict[str, Any]) -> ToolResult:
        permissions = turn.get("permissions") or {}
        if not permissions.get("can_use_actions", False):
            return ToolResult(content=json.dumps({"ok": False, "error": "permission denied"}, ensure_ascii=False))
        task_type = str(args.get("task_type") or "")
        if task_type not in {"chop_tree", "follow_player"}:
            return ToolResult(content=json.dumps({"ok": False, "error": f"unsupported body task: {task_type}"}, ensure_ascii=False))
        response = self.skills.start_task(task_type, args, turn)
        task_status = response.debug.get("task_status") if isinstance(response.debug.get("task_status"), dict) else {}
        ok = bool(response.actions) or bool(response.messages)
        error = ""
        if task_status.get("status") == "failed":
            ok = False
            error = str(task_status.get("last_error") or "")
        payload = {
            "ok": ok,
            "task_type": task_type,
            "messages": response.messages,
            "actions": response.actions,
            "debug": response.debug,
        }
        if error:
            payload["error"] = error
        return ToolResult(content=json.dumps(payload, ensure_ascii=False), actions=response.actions)

    def _stop_body_task(self, args: dict[str, Any], turn: dict[str, Any]) -> ToolResult:
        permissions = turn.get("permissions") or {}
        if not permissions.get("can_use_actions", False):
            return ToolResult(content=json.dumps({"ok": False, "error": "permission denied"}, ensure_ascii=False))
        response = self.skills.stop_task(str(args.get("task_id") or "") or None, turn)
        ok = bool(response.actions)
        payload: dict[str, Any] = {"ok": ok, "messages": response.messages, "actions": response.actions}
        if not ok:
            payload["error"] = "no active body task"
        return ToolResult(
            content=json.dumps(payload, ensure_ascii=False),
            actions=response.actions,
        )

    def _task_status(self, args: dict[str, Any], turn: dict[str, Any]) -> ToolResult:
        status = self.skills.task_status(
            str(args.get("task_id") or "") or None,
            turn,
            include_recent=bool(args.get("include_recent")),
        )
        return ToolResult(content=json.dumps(status, ensure_ascii=False))

    def _run_read_only_command(self, args: dict[str, Any], turn: dict[str, Any]) -> ToolResult:
        command = _strip_slash(str(args.get("command") or ""))
        if not is_read_only_command(command):
            return ToolResult(
                content=json.dumps(
                    {
                        "ok": False,
                        "error": (
                            "Only read-only commands are allowed: seed; time query daytime|gametime|day; "
                            "weather query; list [uuids]; locate structure <identifier>; locate biome <identifier>."
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


def is_read_only_command(command: str) -> bool:
    normalized = _strip_slash(command).lower()
    parts = normalized.split()
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
