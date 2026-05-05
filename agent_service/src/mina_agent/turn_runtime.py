from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .schemas import ToolResult


JsonDict = dict[str, Any]


@dataclass
class TurnRuntimeState:
    request_id: str
    player_id: str
    messages: list[JsonDict]
    actions: list[JsonDict] = field(default_factory=list)
    usage: JsonDict = field(default_factory=dict)
    invalid_tool_results: int = 0
    command_tool_repairs: int = 0
    search_tool_repairs: int = 0
    search_tool_seen: bool = False

    def append_model_message(self, message: JsonDict) -> None:
        self.messages.append(message)

    def append_tool_observation(self, tool_call_id: Any, content: str) -> None:
        self.messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": content,
            }
        )

    def collect_result_actions(self, result: ToolResult) -> list[JsonDict]:
        result_actions: list[JsonDict] = []
        if result.action:
            result_actions.append(result.action)
        result_actions.extend(result.actions)
        if result_actions:
            self.actions.extend(result_actions)
        return result_actions
