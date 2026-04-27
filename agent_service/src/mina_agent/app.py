from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import FastAPI

from .config import Settings, load_settings
from .deepseek import DeepSeekClient
from .harness import AgentHarness
from .logging_config import configure_logging
from .mcp import McpRegistry
from .memory import MemoryStore
from .searxng import SearxngClient
from .tools import ToolRunner


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or load_settings()
    configure_logging(resolved)
    started_at = time.time()
    memory = MemoryStore(resolved.db_path)
    searxng = SearxngClient(resolved.searxng_url)
    mcp = McpRegistry()
    deepseek = DeepSeekClient(resolved)
    tools = ToolRunner(memory, searxng, mcp)
    harness = AgentHarness(resolved, memory, deepseek, tools)

    app = FastAPI(title="Mina Agent Service", version="0.1.0")

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {
            "ok": True,
            "service": "mina-agent-service",
            "uptime_seconds": round(time.time() - started_at, 3),
            "model": resolved.model,
            "deepseek_configured": deepseek.configured(),
            "thinking": resolved.thinking,
            "db_path": str(resolved.db_path),
            "log_path": str(resolved.log_path),
            "searxng": searxng.health(),
            "mcp": mcp.health(),
        }

    @app.post("/v1/turn")
    async def turn(payload: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(harness.run_turn, payload)

    @app.post("/v1/action-results")
    async def action_results(payload: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "received": payload.get("request_id") or payload.get("action_id")}

    return app


app = create_app()
