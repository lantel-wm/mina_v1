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
from .session_queue import SessionTurnQueue
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
    turn_queue = SessionTurnQueue()

    app = FastAPI(title="Mina Agent Service", version="0.1.0")

    async def record_scheduled_actions(request_id: str, data: dict[str, Any]) -> None:
        for action in data.get("actions") or []:
            if isinstance(action, dict):
                await asyncio.to_thread(memory.record_action_event, request_id, "action_scheduled", action)

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
            "session_queue": turn_queue.health(),
        }

    @app.post("/v1/turn")
    async def turn(payload: dict[str, Any]) -> dict[str, Any]:
        data = await turn_queue.run_turn(payload, harness.run_turn)
        request_id = str(payload.get("request_id") or "")
        await record_scheduled_actions(request_id, data)
        return data

    @app.post("/v1/action-results")
    async def action_results(payload: dict[str, Any]) -> dict[str, Any]:
        request_id = str(payload.get("request_id") or "")
        for result in _action_result_items(payload):
            await asyncio.to_thread(memory.record_action_event, request_id, "action_result", result)
        data: dict[str, Any] = {"messages": [], "actions": []}
        data["ok"] = True
        data["received"] = payload.get("request_id") or payload.get("action_id")
        return data

    @app.get("/v1/action-events")
    def action_events(request_id: str | None = None) -> dict[str, Any]:
        return {"ok": True, "events": memory.recent_action_events(request_id=request_id, limit=500)}

    @app.get("/v1/tool-calls")
    def tool_calls(request_id: str | None = None) -> dict[str, Any]:
        return {"ok": True, "tool_calls": memory.recent_tool_calls(request_id=request_id, limit=500)}

    @app.get("/v1/model-calls")
    def model_calls(request_id: str | None = None) -> dict[str, Any]:
        return {"ok": True, "model_calls": memory.recent_model_calls(request_id=request_id, limit=500)}

    @app.get("/v1/traces/{trace_id}")
    def trace(trace_id: str) -> dict[str, Any]:
        model_calls = memory.recent_model_calls(request_id=trace_id, limit=500)
        tool_calls = memory.recent_tool_calls(request_id=trace_id, limit=500)
        action_events = memory.recent_action_events(request_id=trace_id, limit=500)
        return {
            "ok": True,
            "trace_id": trace_id,
            "model_calls": model_calls,
            "tool_calls": tool_calls,
            "action_events": action_events,
        }

    return app


app = create_app()


def _action_result_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    results = payload.get("action_results")
    if isinstance(results, list):
        return [result for result in results if isinstance(result, dict)]
    single = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    if not isinstance(single, dict):
        return []
    if single.get("action_id") or single.get("task_id") or single.get("name"):
        return [single]
    return []
