from __future__ import annotations

import asyncio

from mina_agent.app import create_app
from mina_agent.config import Settings


def test_app_records_action_events_for_read_only_command(tmp_path) -> None:
    app = create_app(Settings(api_key="", db_path=tmp_path / "mina.sqlite3", log_path=tmp_path / "mina.log"))
    turn = _route(app, "/v1/turn")
    action_results = _route(app, "/v1/action-results")
    action_events = _route(app, "/v1/action-events")

    response = asyncio.run(turn(_turn("查询时间", "req-time")))
    action = response["actions"][0]

    advanced = asyncio.run(
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

    assert advanced == {"messages": [], "actions": [], "ok": True, "received": "req-time"}
    assert [event["event_type"] for event in events] == ["action_scheduled", "action_result"]
    assert events[0]["action_name"] == "run_read_only_command"
    assert "The time is 1200" in events[1]["payload_json"]


def test_app_exposes_tool_and_model_call_journals(tmp_path) -> None:
    app = create_app(Settings(api_key="", db_path=tmp_path / "mina.sqlite3", log_path=tmp_path / "mina.log"))
    turn = _route(app, "/v1/turn")
    tool_calls = _route(app, "/v1/tool-calls")
    model_calls = _route(app, "/v1/model-calls")

    asyncio.run(turn(_turn("查询时间", "req-time")))

    calls = tool_calls(request_id="req-time")["tool_calls"]
    assert len(calls) == 1
    assert calls[0]["tool_name"] == "run_read_only_command"
    assert calls[0]["status"] == "ok"
    assert "time query daytime" in calls[0]["args_json"]
    assert model_calls(request_id="req-time")["model_calls"] == []


def test_app_trace_contains_model_tool_and_action_sections_without_tasks(tmp_path) -> None:
    app = create_app(Settings(api_key="", db_path=tmp_path / "mina.sqlite3", log_path=tmp_path / "mina.log"))
    turn = _route(app, "/v1/turn")
    traces = _route(app, "/v1/traces/{trace_id}")

    asyncio.run(turn(_turn("执行 time query day", "req-trace")))
    trace = traces(trace_id="req-trace")

    assert trace["ok"] is True
    assert trace["trace_id"] == "req-trace"
    assert trace["model_calls"] == []
    assert len(trace["tool_calls"]) == 1
    assert len(trace["action_events"]) == 1
    assert "task_events" not in trace
    assert "tasks" not in trace


def test_removed_body_endpoints_are_not_registered(tmp_path) -> None:
    app = create_app(Settings(api_key="", db_path=tmp_path / "mina.sqlite3", log_path=tmp_path / "mina.log"))
    paths = {route.path for route in app.routes}

    assert "/v1/observations" not in paths
    assert "/v1/tasks" not in paths
    assert "/v1/tasks/{task_id}" not in paths


def _turn(message: str, request_id: str) -> dict:
    return {
        "request_id": request_id,
        "trigger": "command",
        "message": message,
        "player": {"uuid": "player-1", "name": "Tester"},
        "permissions": {"can_use_actions": False},
        "snapshot": {},
    }


def _route(app, path: str):  # noqa: ANN001, ANN201
    for route in app.routes:
        if getattr(route, "path", None) == path:
            return route.endpoint
    raise AssertionError(f"missing route {path}")
