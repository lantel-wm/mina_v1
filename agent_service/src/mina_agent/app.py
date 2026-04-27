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
from .tasks import SkillRuntime
from .tools import ToolRunner


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or load_settings()
    configure_logging(resolved)
    started_at = time.time()
    memory = MemoryStore(resolved.db_path)
    searxng = SearxngClient(resolved.searxng_url)
    mcp = McpRegistry()
    deepseek = DeepSeekClient(resolved)
    skills = SkillRuntime(memory)
    tools = ToolRunner(memory, searxng, mcp, skills)
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
        response = await asyncio.to_thread(skills.handle_action_results, payload)
        data = response.to_dict()
        data["ok"] = True
        data["received"] = payload.get("request_id") or payload.get("action_id")
        return data

    @app.post("/v1/observations")
    async def observations(payload: dict[str, Any]) -> dict[str, Any]:
        response = await asyncio.to_thread(skills.handle_observation, payload)
        data = response.to_dict()
        data["ok"] = True
        return data

    @app.get("/v1/tasks/{task_id}")
    def task(task_id: str) -> dict[str, Any]:
        status = skills.task_status(task_id)
        return {"ok": status.get("ok", True) is not False, "task": status}

    @app.get("/v1/tasks/{task_id}/events")
    def task_events(task_id: str) -> dict[str, Any]:
        return {"ok": True, "events": memory.recent_task_events(task_id, limit=200)}

    @app.get("/v1/tasks")
    def tasks() -> dict[str, Any]:
        return {"ok": True, "tasks": skills.list_tasks()}

    return app


app = create_app()
