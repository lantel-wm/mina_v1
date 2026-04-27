from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


JsonDict = dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    content: str
    action: JsonDict | None = None


@dataclass
class TurnResponse:
    messages: list[JsonDict] = field(default_factory=list)
    actions: list[JsonDict] = field(default_factory=list)
    debug: JsonDict = field(default_factory=dict)

    def to_dict(self) -> JsonDict:
        data: JsonDict = {
            "messages": self.messages,
            "actions": self.actions,
        }
        if self.debug:
            data["debug"] = self.debug
        return data

