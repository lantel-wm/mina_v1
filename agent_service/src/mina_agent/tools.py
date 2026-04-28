from __future__ import annotations

import json
import logging
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

READ_ONLY_COMMAND_PREFIXES = {
    "seed",
    "time query",
    "weather query",
    "list",
    "locate structure",
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
                "description": "Search the current player's memories plus reusable skill reflections.",
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
                "name": "start_body_task",
                "description": (
                    "Start a high-level Minecraft body task. Use this instead of low-level movement, look, "
                    "attack, or command tools. The sidecar will decompose the task into observable PuppetPlayers "
                    "actions and continue only after Fabric reports real execution results."
                ),
                "strict": True,
                "parameters": _schema(
                    {
                        "task_type": {"type": "string", "enum": ["chop_tree", "follow_player"]},
                        "target_hint": {"type": "string"},
                    },
                    ["task_type"],
                ),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "stop_body_task",
                "description": "Stop Mina's current high-level body task and release body controls. Omit task_id to stop the current task.",
                "strict": True,
                "parameters": _schema({"task_id": {"type": "string"}}, []),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "task_status",
                "description": "Inspect Mina's current high-level body task status. Omit task_id for the current task.",
                "parameters": _schema({"task_id": {"type": "string"}}, []),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "run_read_only_command",
                "description": (
                    "Run a tightly constrained read-only Minecraft command and show its output to the requester. "
                    "Allowed prefixes: seed, time query, weather query, list, locate structure."
                ),
                "strict": True,
                "parameters": _schema({"command": {"type": "string"}}, ["command"]),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "mcp_call",
                "description": "Call a configured non-Minecraft-write MCP tool through Mina's sidecar MCP registry.",
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
                        "error": (
                            f"{name} is a private executor primitive. Use start_body_task, "
                            "stop_body_task, or task_status instead."
                        ),
                    },
                    ensure_ascii=False,
                )
            )
        return ToolResult(content=json.dumps({"ok": False, "error": f"unknown tool: {name}"}, ensure_ascii=False))

    def _web_search(self, args: dict[str, Any], turn: dict[str, Any]) -> ToolResult:
        query = str(args.get("query") or "").strip()
        max_results = int(args.get("max_results") or 5)
        LOGGER.info("web_search query=%s max_results=%s", query, max_results)
        try:
            results = self.searxng.search(query, max_results=max(1, min(10, max_results)))
        except Exception as exc:  # noqa: BLE001 - tool calls must return model-visible errors.
            LOGGER.info("web_search unavailable query=%s error=%s", query, exc)
            return ToolResult(content=json.dumps({"ok": False, "error": f"web_search unavailable: {exc}"}, ensure_ascii=False))
        LOGGER.info("web_search result_count=%s", len(results))
        return ToolResult(content=json.dumps({"ok": True, "results": results}, ensure_ascii=False))

    def _memory_search(self, args: dict[str, Any], turn: dict[str, Any]) -> ToolResult:
        player_id = _player_id(turn)
        query = str(args.get("query") or "")
        limit = int(args.get("limit") or 8)
        results = self.memory.search(player_id, query, limit=max(1, min(12, limit)))
        LOGGER.info("memory_search player=%s query=%s result_count=%s", player_id, query, len(results))
        return ToolResult(content=json.dumps({"ok": True, "results": results}, ensure_ascii=False))

    def _memory_write(self, args: dict[str, Any], turn: dict[str, Any]) -> ToolResult:
        player_id = _player_id(turn)
        event_type = str(args.get("event_type") or "note")
        content = str(args.get("content") or "")
        importance = int(args.get("importance") or 1)
        self.memory.add_event(player_id, event_type, {"content": content}, importance=max(1, min(5, importance)))
        LOGGER.info("memory_write player=%s event_type=%s importance=%s content=%s", player_id, event_type, importance, content[:500])
        return ToolResult(content=json.dumps({"ok": True}, ensure_ascii=False))

    def _start_body_task(self, args: dict[str, Any], turn: dict[str, Any]) -> ToolResult:
        permissions = turn.get("permissions") or {}
        if not permissions.get("can_use_actions", False):
            return ToolResult(content=json.dumps({"ok": False, "error": "permission denied"}, ensure_ascii=False))
        task_type = str(args.get("task_type") or "")
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
        response = self.skills.stop_task(str(args.get("task_id") or "") or None, turn)
        return ToolResult(
            content=json.dumps({"ok": True, "messages": response.messages, "actions": response.actions}, ensure_ascii=False),
            actions=response.actions,
        )

    def _task_status(self, args: dict[str, Any], turn: dict[str, Any]) -> ToolResult:
        status = self.skills.task_status(str(args.get("task_id") or "") or None, turn)
        return ToolResult(content=json.dumps(status, ensure_ascii=False))

    def _run_read_only_command(self, args: dict[str, Any], turn: dict[str, Any]) -> ToolResult:
        command = _strip_slash(str(args.get("command") or ""))
        if not _is_read_only_command(command):
            return ToolResult(
                content=json.dumps(
                    {
                        "ok": False,
                        "error": "Only read-only commands are allowed: seed, time query, weather query, list, locate structure.",
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
        else:
            result = self.mcp.call(server, tool, arguments)
        LOGGER.info("mcp_call server=%s tool=%s ok=%s", server, tool, result.get("ok"))
        return ToolResult(content=json.dumps(result, ensure_ascii=False))


def _player_id(turn: dict[str, Any]) -> str:
    player = turn.get("player") or {}
    return str(player.get("uuid") or player.get("id") or "unknown")


def _looks_like_minecraft_write(tool: str, arguments: dict[str, Any]) -> bool:
    haystack = (tool + " " + json.dumps(arguments, ensure_ascii=False)).lower()
    banned = ["setblock", "fill", "tp ", "teleport", "gamemode", "give ", "summon", "kill "]
    return any(token in haystack for token in banned)


def _strip_slash(command: str) -> str:
    normalized = command.strip()
    while normalized.startswith("/"):
        normalized = normalized[1:].strip()
    return " ".join(normalized.split())


def _is_read_only_command(command: str) -> bool:
    normalized = _strip_slash(command).lower()
    if not normalized:
        return False
    for prefix in READ_ONLY_COMMAND_PREFIXES:
        if normalized == prefix or normalized.startswith(prefix + " "):
            return True
    return False
