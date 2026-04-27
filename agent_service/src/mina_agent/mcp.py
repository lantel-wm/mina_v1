from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class McpRegistry:
    def __init__(self, config_path: Path = Path("agent_service/config/mcp.json")):
        self.config_path = config_path
        self.servers = self._load()

    def health(self) -> dict[str, Any]:
        return {
            "configured": bool(self.servers),
            "servers": sorted(self.servers),
        }

    def call(self, server: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if server not in self.servers:
            return {"ok": False, "error": f"MCP server is not configured: {server}"}
        return {
            "ok": False,
            "error": "MCP transport execution is not enabled in v1; registry entry is present but calls are disabled.",
            "server": server,
            "tool": tool,
        }

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.config_path.exists():
            return {}
        payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        servers = payload.get("servers", {})
        if not isinstance(servers, dict):
            return {}
        return {str(name): value for name, value in servers.items() if isinstance(value, dict)}

