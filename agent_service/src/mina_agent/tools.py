from __future__ import annotations

import json
import logging
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


FABRIC_ACTION_TOOLS = {
    "send_player_message",
    "send_global_message",
    "run_safe_command",
    "locate_structure",
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

ACTION_PERMISSION_TOOLS = {
    "run_safe_command",
    "locate_structure",
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
                "description": "Search Mina's long-term memory for the current player.",
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
                "name": "send_player_message",
                "description": "Send a Minecraft chat/system message to the current player.",
                "parameters": _schema({"content": {"type": "string"}}, ["content"]),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "send_global_message",
                "description": "Send a Minecraft chat/system message to all online players.",
                "parameters": _schema({"content": {"type": "string"}}, ["content"]),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "run_safe_command",
                "description": "Ask the Fabric mod to run a non-denylisted server command.",
                "parameters": _schema({"command": {"type": "string"}}, ["command"]),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "locate_structure",
                "description": "Ask Minecraft to locate a structure identifier such as minecraft:village.",
                "parameters": _schema({"structure": {"type": "string"}}, ["structure"]),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "body_spawn",
                "description": "Spawn or join Mina's PuppetPlayers body near the requester.",
                "strict": True,
                "parameters": _schema({}, []),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "body_move_to_position",
                "description": "Move Mina's PuppetPlayers body to an exact world position.",
                "strict": True,
                "parameters": _schema(
                    {
                        "x": {"type": "number"},
                        "y": {"type": "number"},
                        "z": {"type": "number"},
                        "sprint": {"type": "boolean"},
                        "jump": {"type": "boolean"},
                    },
                    ["x", "y", "z", "sprint", "jump"],
                ),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "body_move_to_entity",
                "description": "Move Mina's PuppetPlayers body to an entity selected by a Minecraft selector.",
                "strict": True,
                "parameters": _schema(
                    {
                        "entity_selector": {"type": "string"},
                        "sprint": {"type": "boolean"},
                        "jump": {"type": "boolean"},
                    },
                    ["entity_selector", "sprint", "jump"],
                ),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "body_move_to_requester",
                "description": "Move Mina's PuppetPlayers body to the player who requested this turn.",
                "strict": True,
                "parameters": _schema(
                    {
                        "sprint": {"type": "boolean"},
                        "jump": {"type": "boolean"},
                    },
                    ["sprint", "jump"],
                ),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "mcp_call",
                "description": "Call a configured MCP tool through Mina's sidecar MCP registry.",
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
        {
            "type": "function",
            "function": {
                "name": "body_look_at_position",
                "description": "Make Mina's PuppetPlayers body look at an exact world position.",
                "strict": True,
                "parameters": _schema(
                    {
                        "x": {"type": "number"},
                        "y": {"type": "number"},
                        "z": {"type": "number"},
                    },
                    ["x", "y", "z"],
                ),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "body_look_at_requester",
                "description": "Make Mina's PuppetPlayers body look at the player who requested this turn.",
                "strict": True,
                "parameters": _schema({}, []),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "body_chain",
                "description": (
                    "Build and start an ordered PuppetPlayers action chain. Use this for any sequence that needs "
                    "movement followed by looking, held attack/use, or delay. Supported action types: "
                    "move_to_position(x,y,z,sprint,jump), move_to_requester(sprint,jump), "
                    "look_at_position(x,y,z), look_at_requester(), attack(mode), use(mode), "
                    "delay(seconds), swap_slot(slot). For block breaking, a typical chain is: move_to_position "
                    "to an approach coordinate, look_at_position at the block center, attack hold, delay 4-6 seconds, "
                    "attack release; verify from the next snapshot before claiming completion."
                ),
                "strict": True,
                "parameters": _schema(
                    {
                        "clear": {"type": "boolean", "description": "Stop and clear existing body controls before adding this chain."},
                        "loop": {"type": "boolean", "description": "Whether PuppetPlayers should loop the chain."},
                        "restart": {"type": "boolean", "description": "Whether to restart the chain after adding all actions."},
                        "actions": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 20,
                            "items": {
                                "type": "object",
                                "properties": {
                                    "type": {
                                        "type": "string",
                                        "enum": [
                                            "move_to_position",
                                            "move_to_requester",
                                            "look_at_position",
                                            "look_at_requester",
                                            "attack",
                                            "use",
                                            "delay",
                                            "swap_slot",
                                        ],
                                    },
                                    "x": {"type": "number"},
                                    "y": {"type": "number"},
                                    "z": {"type": "number"},
                                    "sprint": {"type": "boolean"},
                                    "jump": {"type": "boolean"},
                                    "mode": {"type": "string", "enum": ["once", "hold", "release"]},
                                    "seconds": {"type": "number", "minimum": 0.1, "maximum": 30},
                                    "slot": {"type": "integer", "minimum": 0, "maximum": 8},
                                },
                                "required": ["type"],
                                "additionalProperties": False,
                            },
                        },
                    },
                    ["clear", "loop", "restart", "actions"],
                ),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "body_attack",
                "description": "Make Mina's PuppetPlayers body attack. Use hold to keep left-clicking/mining a block, and release to stop.",
                "strict": True,
                "parameters": _schema({"mode": {"type": "string", "enum": ["once", "hold", "release"]}}, ["mode"]),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "body_use",
                "description": "Make Mina's PuppetPlayers body use/right-click once, hold, or release.",
                "strict": True,
                "parameters": _schema({"mode": {"type": "string", "enum": ["once", "hold", "release"]}}, ["mode"]),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "body_swap_slot",
                "description": "Switch Mina's PuppetPlayers body hotbar slot.",
                "strict": True,
                "parameters": _schema({"slot": {"type": "integer", "minimum": 0, "maximum": 8}}, ["slot"]),
            },
        },
        {
            "type": "function",
            "function": {
                "name": "body_stop",
                "description": "Stop Mina's PuppetPlayers body movement, look target, and action chain.",
                "strict": True,
                "parameters": _schema({}, []),
            },
        },
    ]


class ToolRunner:
    def __init__(self, memory: MemoryStore, searxng: SearxngClient, mcp: McpRegistry | None = None):
        self.memory = memory
        self.searxng = searxng
        self.mcp = mcp or McpRegistry()

    def run(self, name: str, args: dict[str, Any], turn: dict[str, Any]) -> ToolResult:
        local: dict[str, Callable[[dict[str, Any], dict[str, Any]], ToolResult]] = {
            "web_search": self._web_search,
            "memory_search": self._memory_search,
            "memory_write": self._memory_write,
            "mcp_call": self._mcp_call,
        }
        if name in local:
            return local[name](args, turn)
        if name in FABRIC_ACTION_TOOLS:
            return self._fabric_action(name, args, turn)
        return ToolResult(content=json.dumps({"error": f"unknown tool: {name}"}, ensure_ascii=False))

    def _web_search(self, args: dict[str, Any], turn: dict[str, Any]) -> ToolResult:
        query = str(args.get("query") or "").strip()
        max_results = int(args.get("max_results") or 5)
        LOGGER.info("web_search query=%s max_results=%s", query, max_results)
        results = self.searxng.search(query, max_results=max(1, min(10, max_results)))
        LOGGER.info("web_search result_count=%s", len(results))
        return ToolResult(content=json.dumps({"results": results}, ensure_ascii=False))

    def _memory_search(self, args: dict[str, Any], turn: dict[str, Any]) -> ToolResult:
        player_id = _player_id(turn)
        query = str(args.get("query") or "")
        limit = int(args.get("limit") or 8)
        results = self.memory.search(player_id, query, limit=max(1, min(12, limit)))
        LOGGER.info("memory_search player=%s query=%s result_count=%s", player_id, query, len(results))
        return ToolResult(content=json.dumps({"results": results}, ensure_ascii=False))

    def _memory_write(self, args: dict[str, Any], turn: dict[str, Any]) -> ToolResult:
        player_id = _player_id(turn)
        event_type = str(args.get("event_type") or "note")
        content = str(args.get("content") or "")
        importance = int(args.get("importance") or 1)
        self.memory.add_event(player_id, event_type, {"content": content}, importance=max(1, min(5, importance)))
        LOGGER.info("memory_write player=%s event_type=%s importance=%s content=%s", player_id, event_type, importance, content[:500])
        return ToolResult(content=json.dumps({"ok": True}, ensure_ascii=False))

    def _mcp_call(self, args: dict[str, Any], turn: dict[str, Any]) -> ToolResult:
        server = str(args.get("server") or "")
        tool = str(args.get("tool") or "")
        arguments = args.get("arguments")
        if not isinstance(arguments, dict):
            arguments = {}
        result = self.mcp.call(server, tool, arguments)
        LOGGER.info("mcp_call server=%s tool=%s ok=%s", server, tool, result.get("ok"))
        return ToolResult(content=json.dumps(result, ensure_ascii=False))

    def _fabric_action(self, name: str, args: dict[str, Any], turn: dict[str, Any]) -> ToolResult:
        args = args if isinstance(args, dict) else {}
        permissions = turn.get("permissions") or {}
        requires_permission = name in ACTION_PERMISSION_TOOLS
        if requires_permission and not permissions.get("can_use_actions", False):
            LOGGER.info("fabric_action denied name=%s args=%s", name, args)
            return ToolResult(content=json.dumps({"ok": False, "error": "permission denied"}, ensure_ascii=False))
        if name == "body_spawn" and _body_is_online(turn):
            LOGGER.info("fabric_action skipped name=body_spawn reason=body_already_online")
            return ToolResult(
                content=json.dumps(
                    {
                        "ok": False,
                        "error": "Mina body is already online. Use movement, looking, or action tools instead of spawning.",
                    },
                    ensure_ascii=False,
                )
            )
        validation_error = _validate_fabric_args(name, args)
        if validation_error is not None:
            LOGGER.info("fabric_action invalid_args name=%s args=%s error=%s", name, args, validation_error)
            return ToolResult(content=json.dumps({"ok": False, "error": validation_error}, ensure_ascii=False))
        action = {
            "id": str(uuid.uuid4()),
            "name": name,
            "args": args,
            "requires_permission": requires_permission,
        }
        LOGGER.info("fabric_action scheduled id=%s name=%s args=%s requires_permission=%s", action["id"], name, args, requires_permission)
        return ToolResult(
            content=json.dumps(
                {
                    "ok": True,
                    "scheduled_action_id": action["id"],
                    "status": "scheduled_not_confirmed",
                    "instruction": "The Fabric mod has been asked to execute this action, but completion is not confirmed yet. Do not claim success.",
                },
                ensure_ascii=False,
            ),
            action=action,
        )


def _player_id(turn: dict[str, Any]) -> str:
    player = turn.get("player") or {}
    return str(player.get("uuid") or player.get("id") or "unknown")


def _body_is_online(turn: dict[str, Any]) -> bool:
    snapshot = turn.get("snapshot") or {}
    body_state = snapshot.get("body_state") or {}
    return bool(body_state.get("online")) if isinstance(body_state, dict) else False


def _validate_fabric_args(name: str, args: dict[str, Any]) -> str | None:
    if name == "send_player_message":
        return _require(args, "send_player_message", "content")
    if name == "send_global_message":
        return _require(args, "send_global_message", "content")
    if name == "run_safe_command":
        return _require(args, "run_safe_command", "command")
    if name == "locate_structure":
        return _require(args, "locate_structure", "structure")
    if name == "body_move_to_position":
        return _require(args, "body_move_to_position", "x", "y", "z", "sprint", "jump")
    if name == "body_move_to_entity":
        return _require(args, "body_move_to_entity", "entity_selector", "sprint", "jump")
    if name == "body_move_to_requester":
        return _require(args, "body_move_to_requester", "sprint", "jump")
    if name == "body_look_at_position":
        return _require(args, "body_look_at_position", "x", "y", "z")
    if name == "body_look_at_entity":
        return "body_look_at_entity is not supported by PuppetPlayers 1.21.11; use body_look_at_position"
    if name == "body_look_at_requester":
        return None
    if name == "body_attack":
        return _require(args, "body_attack", "mode")
    if name == "body_chain":
        return _validate_body_chain(args)
    if name == "body_use":
        return _require(args, "body_use", "mode")
    if name == "body_swap_slot":
        return _require(args, "body_swap_slot", "slot")
    if name not in {"body_move_to", "body_look_at"}:
        return None
    target_type = args.get("target_type")
    if target_type == "requester":
        return None
    if target_type == "entity":
        if args.get("entity_selector"):
            return None
        return f"{name} target_type=entity requires entity_selector"
    if target_type == "position":
        if all(key in args for key in ("x", "y", "z")):
            return None
        return f"{name} target_type=position requires x, y, and z"
    if all(key in args for key in ("x", "y", "z")):
        args["target_type"] = "position"
        return None
    if args.get("entity_selector"):
        args["target_type"] = "entity"
        return None
    return f"{name} requires target_type=requester, target_type=entity with entity_selector, or target_type=position with x/y/z"


def _validate_body_chain(args: dict[str, Any]) -> str | None:
    top_level = _require(args, "body_chain", "clear", "loop", "restart", "actions")
    if top_level is not None:
        return top_level
    actions = args.get("actions")
    if not isinstance(actions, list) or not actions:
        return "body_chain actions must be a non-empty array"
    if len(actions) > 20:
        return "body_chain supports at most 20 actions"
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            return f"body_chain actions[{index}] must be an object"
        action_name = f"body_chain actions[{index}]"
        action_type = action.get("type")
        if action_type == "move_to_position":
            error = _require(action, action_name, "x", "y", "z", "sprint", "jump")
        elif action_type == "move_to_requester":
            error = _require(action, action_name, "sprint", "jump")
        elif action_type == "look_at_position":
            error = _require(action, action_name, "x", "y", "z")
        elif action_type == "look_at_requester":
            error = None
        elif action_type in {"attack", "use"}:
            error = _require(action, action_name, "mode")
            if error is None and action.get("mode") not in {"once", "hold", "release"}:
                error = f"{action_name} mode must be once, hold, or release"
        elif action_type == "delay":
            error = _require(action, action_name, "seconds")
        elif action_type == "swap_slot":
            error = _require(action, action_name, "slot")
        else:
            error = f"{action_name} has unsupported type {action_type}"
        if error is not None:
            return error
    return None


def _require(args: dict[str, Any], tool_name: str, *keys: str) -> str | None:
    missing = [key for key in keys if key not in args or args[key] is None]
    if missing:
        return f"{tool_name} requires {', '.join(missing)}"
    return None
