from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from mina_agent.memory import MemoryStore
from mina_agent.tasks import SkillRuntime

memory = MemoryStore(Path(os.getenv("MINA_DB_PATH", "build/e2e/mina-scripted.sqlite3")))
skills = SkillRuntime(memory)
started_at = time.time()
app = FastAPI(title="Mina Scripted Sidecar", version="0.1.0")


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "mina-scripted-sidecar",
        "uptime_seconds": round(time.time() - started_at, 3),
        "model": "scripted",
        "deepseek_configured": False,
    }


@app.post("/v1/turn")
def turn(payload: dict[str, Any]) -> dict[str, Any]:
    player = payload.get("player") if isinstance(payload.get("player"), dict) else {}
    memory.upsert_player(player)
    message = str(payload.get("message") or "").lower()
    if "砍树" in message or "chop" in message or "tree" in message:
        response = skills.start_task("chop_tree", {"task_type": "chop_tree", "target_hint": message}, payload)
        return response.to_dict()
    return {"messages": [{"target": "requester", "content": "scripted sidecar only handles chop_tree."}], "actions": []}


@app.post("/v1/action-results")
def action_results(payload: dict[str, Any]) -> dict[str, Any]:
    response = skills.handle_action_results(payload)
    data = response.to_dict()
    data["ok"] = True
    return data


@app.post("/v1/observations")
def observations(payload: dict[str, Any]) -> dict[str, Any]:
    response = skills.handle_observation(payload)
    data = response.to_dict()
    data["ok"] = True
    return data


@app.get("/v1/tasks")
def tasks() -> dict[str, Any]:
    return {"ok": True, "tasks": skills.list_tasks()}


@app.get("/v1/tasks/{task_id}")
def task(task_id: str) -> dict[str, Any]:
    return {"ok": True, "task": skills.task_status(task_id)}


@app.get("/v1/tasks/{task_id}/events")
def task_events(task_id: str) -> dict[str, Any]:
    return {"ok": True, "events": memory.recent_task_events(task_id, limit=200)}
