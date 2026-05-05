from __future__ import annotations

import asyncio
import threading
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
    progress = ProgressStore()
    harness = AgentHarness(resolved, memory, deepseek, tools, progress_callback=progress.emit)
    turn_queue = SessionTurnQueue()

    app = FastAPI(title="Mina Agent Service", version="0.1.0")

    async def record_scheduled_actions(request_id: str, data: dict[str, Any]) -> None:
        for action in data.get("actions") or []:
            if isinstance(action, dict):
                await asyncio.to_thread(memory.record_action_event, request_id, "action_scheduled", action)

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        memory_health = memory.health()
        return {
            "ok": bool(memory_health.get("ok")),
            "service": "mina-agent-service",
            "uptime_seconds": round(time.time() - started_at, 3),
            "model": resolved.model,
            "deepseek_configured": deepseek.configured(),
            "thinking": resolved.thinking,
            "db_path": str(resolved.db_path),
            "db": memory_health,
            "log_path": str(resolved.log_path),
            "searxng": searxng.health(),
            "mcp": mcp.health(),
            "session_queue": turn_queue.health(),
        }

    @app.post("/v1/turn")
    async def turn(payload: dict[str, Any]) -> dict[str, Any]:
        request_id = str(payload.get("request_id") or "")
        progress.start(request_id)
        try:
            data = await turn_queue.run_turn(payload, harness.run_turn)
        finally:
            progress.complete(request_id)
        data["progress_events"] = progress.events(request_id)
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

    @app.get("/v1/progress/{request_id}")
    def progress_events(request_id: str, after: int = 0) -> dict[str, Any]:
        return progress.read(request_id, after=after)

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


class ProgressStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[str, list[dict[str, Any]]] = {}
        self._completed: set[str] = set()

    def start(self, request_id: str) -> None:
        if not request_id:
            return
        with self._lock:
            self._events[request_id] = []
            self._completed.discard(request_id)

    def emit(self, request_id: str, event: dict[str, Any]) -> None:
        if not request_id:
            return
        with self._lock:
            events = self._events.setdefault(request_id, [])
            item = dict(event)
            item["seq"] = len(events) + 1
            item.setdefault("created_at", time.time())
            events.append(item)

    def complete(self, request_id: str) -> None:
        if not request_id:
            return
        with self._lock:
            self._completed.add(request_id)

    def events(self, request_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(event) for event in self._events.get(request_id, [])]

    def read(self, request_id: str, *, after: int = 0) -> dict[str, Any]:
        with self._lock:
            events = [dict(event) for event in self._events.get(request_id, []) if int(event.get("seq") or 0) > after]
            return {
                "ok": True,
                "request_id": request_id,
                "after": after,
                "completed": request_id in self._completed,
                "events": events,
            }


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
