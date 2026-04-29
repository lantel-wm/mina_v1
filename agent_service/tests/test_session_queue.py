from __future__ import annotations

import asyncio
import threading

from mina_agent.session_queue import SessionTurnQueue, session_key_for_turn


def test_session_key_prefers_player_uuid() -> None:
    assert session_key_for_turn({"player": {"uuid": "player-1"}, "world_id": "world"}) == "player:player-1"
    assert session_key_for_turn({"world_id": "world"}) == "world:world"
    assert session_key_for_turn({}) == "global:*"


def test_session_queue_serializes_turns_and_suppresses_stale_response() -> None:
    async def run() -> None:
        queue = SessionTurnQueue()
        first_started = threading.Event()
        release_first = threading.Event()
        events: list[str] = []

        def runner(payload: dict) -> dict:
            request_id = payload["request_id"]
            events.append(f"start:{request_id}")
            if request_id == "req-1":
                first_started.set()
                assert release_first.wait(timeout=2)
            events.append(f"end:{request_id}")
            return {
                "messages": [{"target": "requester", "content": f"done {request_id}"}],
                "actions": [{"id": request_id, "name": "run_read_only_command"}],
            }

        first = asyncio.create_task(queue.run_turn(_turn("req-1"), runner))
        assert await asyncio.to_thread(first_started.wait, 2)
        second = asyncio.create_task(queue.run_turn(_turn("req-2"), runner))
        await asyncio.sleep(0.05)
        release_first.set()

        first_response, second_response = await asyncio.gather(first, second)

        assert events == ["start:req-1", "end:req-1", "start:req-2", "end:req-2"]
        assert first_response["messages"] == []
        assert first_response["actions"] == []
        assert first_response["debug"]["stale_turn"] is True
        assert first_response["debug"]["stale_phase"] == "after_run"
        assert second_response["messages"][0]["content"] == "done req-2"
        assert second_response["actions"][0]["id"] == "req-2"

        health = queue.health()
        session = health["sessions"]["player:player-1"]
        assert session["enqueued_count"] == 2
        assert session["completed_count"] == 2
        assert session["stale_count"] == 1

    asyncio.run(run())


def test_session_queue_skips_stale_waiting_turn_before_model_run() -> None:
    async def run() -> None:
        queue = SessionTurnQueue()
        first_started = threading.Event()
        release_first = threading.Event()
        calls: list[str] = []

        def runner(payload: dict) -> dict:
            request_id = payload["request_id"]
            calls.append(request_id)
            if request_id == "req-1":
                first_started.set()
                assert release_first.wait(timeout=2)
            return {"messages": [{"target": "requester", "content": request_id}], "actions": []}

        first = asyncio.create_task(queue.run_turn(_turn("req-1"), runner))
        assert await asyncio.to_thread(first_started.wait, 2)
        second = asyncio.create_task(queue.run_turn(_turn("req-2"), runner))
        await asyncio.sleep(0.01)
        third = asyncio.create_task(queue.run_turn(_turn("req-3"), runner))
        await asyncio.sleep(0.05)
        release_first.set()

        first_response, second_response, third_response = await asyncio.gather(first, second, third)

        assert calls == ["req-1", "req-3"]
        assert first_response["debug"]["stale_phase"] == "after_run"
        assert second_response["debug"]["stale_phase"] == "before_run"
        assert third_response["messages"][0]["content"] == "req-3"

    asyncio.run(run())


def _turn(request_id: str) -> dict:
    return {
        "request_id": request_id,
        "player": {"uuid": "player-1", "name": "Tester"},
        "message": request_id,
        "snapshot": {},
    }
