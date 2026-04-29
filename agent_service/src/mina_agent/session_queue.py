from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable


JsonDict = dict[str, Any]
TurnRunner = Callable[[JsonDict], JsonDict]


@dataclass
class SessionState:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    latest_sequence: int = 0
    running_sequence: int = 0
    running_request_id: str = ""
    enqueued_count: int = 0
    completed_count: int = 0
    stale_count: int = 0
    last_seen: float = field(default_factory=time.time)


class SessionTurnQueue:
    """Serializes Mina turns per player session and suppresses stale responses."""

    def __init__(self) -> None:
        self._state_lock = asyncio.Lock()
        self._sessions: dict[str, SessionState] = {}

    async def run_turn(self, payload: JsonDict, runner: TurnRunner) -> JsonDict:
        session_key = session_key_for_turn(payload)
        request_id = str(payload.get("request_id") or "")
        state, sequence = await self._enqueue(session_key)
        async with state.lock:
            if await self._is_stale_before_run(session_key, state, sequence, request_id):
                return _stale_response(session_key, sequence, request_id, "before_run")

            data = await asyncio.to_thread(runner, payload)
            stale_after_run = await self._complete(session_key, state, sequence)
            if stale_after_run:
                return _stale_response(session_key, sequence, request_id, "after_run", original=data)
            data.setdefault("debug", {})
            if isinstance(data["debug"], dict):
                data["debug"]["session_key"] = session_key
                data["debug"]["session_sequence"] = sequence
            return data

    def health(self) -> JsonDict:
        sessions: dict[str, JsonDict] = {}
        for key, state in self._sessions.items():
            sessions[key] = {
                "latest_sequence": state.latest_sequence,
                "running_sequence": state.running_sequence,
                "running_request_id": state.running_request_id,
                "enqueued_count": state.enqueued_count,
                "completed_count": state.completed_count,
                "stale_count": state.stale_count,
                "last_seen": round(state.last_seen, 3),
                "locked": state.lock.locked(),
            }
        return {"session_count": len(sessions), "sessions": sessions}

    async def _enqueue(self, session_key: str) -> tuple[SessionState, int]:
        async with self._state_lock:
            state = self._sessions.setdefault(session_key, SessionState())
            state.latest_sequence += 1
            state.enqueued_count += 1
            state.last_seen = time.time()
            return state, state.latest_sequence

    async def _is_stale_before_run(self, session_key: str, state: SessionState, sequence: int, request_id: str) -> bool:
        async with self._state_lock:
            state.last_seen = time.time()
            if sequence != state.latest_sequence:
                state.stale_count += 1
                return True
            state.running_sequence = sequence
            state.running_request_id = request_id
            self._sessions[session_key] = state
            return False

    async def _complete(self, session_key: str, state: SessionState, sequence: int) -> bool:
        async with self._state_lock:
            state.completed_count += 1
            state.last_seen = time.time()
            stale = sequence != state.latest_sequence
            if stale:
                state.stale_count += 1
            if state.running_sequence == sequence:
                state.running_sequence = 0
                state.running_request_id = ""
            self._sessions[session_key] = state
            return stale


def session_key_for_turn(payload: JsonDict) -> str:
    player = payload.get("player")
    if isinstance(player, dict):
        player_id = str(player.get("uuid") or player.get("id") or "").strip()
        if player_id:
            return f"player:{player_id}"
    world_id = str(payload.get("world_id") or "").strip()
    if world_id:
        return f"world:{world_id}"
    return "global:*"


def _stale_response(
    session_key: str,
    sequence: int,
    request_id: str,
    phase: str,
    *,
    original: JsonDict | None = None,
) -> JsonDict:
    debug: JsonDict = {
        "session_key": session_key,
        "session_sequence": sequence,
        "stale_turn": True,
        "stale_phase": phase,
    }
    if original and isinstance(original.get("debug"), dict):
        debug["original_debug"] = original["debug"]
    return {"messages": [], "actions": [], "debug": debug, "request_id": request_id}
