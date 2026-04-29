from __future__ import annotations

import asyncio
import sqlite3

from mina_agent.app import create_app
from mina_agent.config import Settings
from mina_agent.memory import MemoryStore


def test_app_records_action_events_for_read_only_command(tmp_path) -> None:
    app = create_app(Settings(api_key="", db_path=tmp_path / "mina.sqlite3", log_path=tmp_path / "mina.log"))
    turn = _route(app, "/v1/turn")
    action_results = _route(app, "/v1/action-results")
    action_events = _route(app, "/v1/action-events")

    response = asyncio.run(
        turn(
            {
                "request_id": "req-time",
                "trigger": "command",
                "message": "查询时间",
                "player": {"uuid": "player-1", "name": "Tester"},
                "permissions": {"can_use_actions": False},
                "snapshot": {},
            }
        )
    )
    action = response["actions"][0]

    asyncio.run(
        action_results(
            {
                "request_id": "req-time",
                "action_results": [
                    {
                        "action_id": action["id"],
                        "name": "run_read_only_command",
                        "status": "completed",
                        "command_success": True,
                        "command_results": [{"outputs": ["The time is 1200"]}],
                    }
                ],
            }
        )
    )
    events = action_events(request_id="req-time")["events"]

    assert [event["event_type"] for event in events] == ["action_scheduled", "action_result"]
    assert events[0]["action_name"] == "run_read_only_command"
    assert "The time is 1200" in events[1]["payload_json"]


def test_app_exposes_tool_call_journal(tmp_path) -> None:
    app = create_app(Settings(api_key="", db_path=tmp_path / "mina.sqlite3", log_path=tmp_path / "mina.log"))
    turn = _route(app, "/v1/turn")
    tool_calls = _route(app, "/v1/tool-calls")

    asyncio.run(
        turn(
            {
                "request_id": "req-time",
                "trigger": "command",
                "message": "查询时间",
                "player": {"uuid": "player-1", "name": "Tester"},
                "permissions": {"can_use_actions": False},
                "snapshot": {},
            }
        )
    )
    calls = tool_calls(request_id="req-time")["tool_calls"]

    assert len(calls) == 1
    assert calls[0]["tool_name"] == "run_read_only_command"
    assert calls[0]["status"] == "ok"
    assert "time query daytime" in calls[0]["args_json"]


def test_app_records_single_action_result_payload(tmp_path) -> None:
    app = create_app(Settings(api_key="", db_path=tmp_path / "mina.sqlite3", log_path=tmp_path / "mina.log"))
    action_results = _route(app, "/v1/action-results")
    action_events = _route(app, "/v1/action-events")

    asyncio.run(
        action_results(
            {
                "request_id": "req-single",
                "action_id": "action-1",
                "name": "run_read_only_command",
                "status": "completed",
                "command_success": True,
                "command_results": [{"outputs": ["There are 2 of a max of 20 players online"]}],
            }
        )
    )
    events = action_events(request_id="req-single")["events"]

    assert [event["event_type"] for event in events] == ["action_result"]
    assert events[0]["action_id"] == "action-1"
    assert events[0]["action_name"] == "run_read_only_command"


def test_app_does_not_schedule_body_actions_from_action_results_while_paused(tmp_path) -> None:
    app = create_app(Settings(api_key="", db_path=tmp_path / "mina.sqlite3", log_path=tmp_path / "mina.log"))
    turn = _route(app, "/v1/turn")
    action_results = _route(app, "/v1/action-results")
    action_events = _route(app, "/v1/action-events")

    response = asyncio.run(
        turn(
            {
                "request_id": "req-follow",
                "trigger": "command",
                "message": "跟随我",
                "player": {"uuid": "player-1", "name": "Tester"},
                "permissions": {"can_use_actions": True},
                "snapshot": {"body_state": {"online": True}},
            }
        )
    )
    assert response["actions"] == []
    assert "假人控制功能暂时停用" in response["messages"][0]["content"]

    advanced = asyncio.run(
        action_results(
            {
                "request_id": "req-follow",
                "action_results": [
                    {
                        "action_id": "stale-body-action",
                        "task_id": "stale-task",
                        "step_id": "follow:1",
                        "name": "body_move_to_requester",
                        "status": "success",
                        "command_success": True,
                        "monitor_result": {"status": "success", "reason": "follow heartbeat"},
                        "snapshot": {"body_state": {"online": True}},
                    }
                ],
            }
        )
    )

    assert advanced["actions"] == []
    assert advanced["debug"]["body_control_disabled"] is True
    events = action_events(request_id="req-follow")["events"]
    assert [event["event_type"] for event in events] == ["action_result"]
    assert [event["action_name"] for event in events] == ["body_move_to_requester"]


def test_app_does_not_schedule_body_actions_from_observations_while_paused(tmp_path) -> None:
    app = create_app(Settings(api_key="", db_path=tmp_path / "mina.sqlite3", log_path=tmp_path / "mina.log"))
    turn = _route(app, "/v1/turn")
    observations = _route(app, "/v1/observations")
    action_events = _route(app, "/v1/action-events")

    response = asyncio.run(
        turn(
            {
                "request_id": "req-spawn",
                "trigger": "command",
                "message": "跟随我",
                "player": {"uuid": "player-1", "name": "Tester"},
                "permissions": {"can_use_actions": True},
                "snapshot": {"body_state": {"online": False}},
            }
        )
    )
    assert response["actions"] == []
    assert "假人控制功能暂时停用" in response["messages"][0]["content"]

    advanced = asyncio.run(
        observations(
            {
                "request_id": "req-spawn",
                "task_id": "stale-task",
                "snapshot": {"body_state": {"online": True}},
            }
        )
    )

    assert advanced["actions"] == []
    assert advanced["debug"]["body_control_disabled"] is True
    events = action_events(request_id="req-spawn")["events"]
    assert events == []


def test_app_exposes_model_call_and_trace_endpoints(tmp_path) -> None:
    app = create_app(Settings(api_key="", db_path=tmp_path / "mina.sqlite3", log_path=tmp_path / "mina.log"))
    model_calls = _route(app, "/v1/model-calls")
    traces = _route(app, "/v1/traces/{trace_id}")

    assert model_calls(request_id="req-empty") == {"ok": True, "model_calls": []}
    trace = traces(trace_id="req-empty")
    assert trace["ok"] is True
    assert trace["trace_id"] == "req-empty"
    assert trace["model_calls"] == []
    assert trace["tool_calls"] == []
    assert trace["action_events"] == []


def test_trace_endpoint_filters_old_task_history(tmp_path) -> None:
    db_path = tmp_path / "mina.sqlite3"
    app = create_app(Settings(api_key="", db_path=db_path, log_path=tmp_path / "mina.log"))
    action_results = _route(app, "/v1/action-results")
    traces = _route(app, "/v1/traces/{trace_id}")
    memory = MemoryStore(db_path)
    task_id = "task-from-previous-request"

    memory.record_task_event(task_id, "started", {"request_id": "old"})
    with sqlite3.connect(db_path) as conn:
        conn.execute("update task_events set created_at = created_at - 60 where task_id = ?", (task_id,))

    asyncio.run(
        action_results(
            {
                "request_id": "req-replacement",
                "action_results": [
                    {
                        "action_id": "stop-1",
                        "task_id": task_id,
                        "step_id": "stop:replaced",
                        "name": "body_stop",
                        "status": "success",
                    }
                ],
            }
        )
    )
    memory.record_task_event(task_id, "cancelled_by_new_task", {"request_id": "req-replacement"})

    events = traces(trace_id="req-replacement")["task_events"]

    assert [event["event_type"] for event in events] == ["cancelled_by_new_task"]


def _route(app, path: str):  # noqa: ANN001, ANN202
    for route in app.routes:
        if getattr(route, "path", "") == path:
            return route.endpoint
    raise AssertionError(f"route not found: {path}")
