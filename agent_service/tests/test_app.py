from __future__ import annotations

import asyncio

from mina_agent.app import create_app
from mina_agent.config import Settings


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


def test_app_records_actions_scheduled_from_action_results(tmp_path) -> None:
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
    first = response["actions"][0]

    advanced = asyncio.run(
        action_results(
            {
                "request_id": "req-follow",
                "action_results": [
                    {
                        "action_id": first["id"],
                        "task_id": first["task_id"],
                        "step_id": first["step_id"],
                        "name": first["name"],
                        "status": "success",
                        "command_success": True,
                        "monitor_result": {"status": "success", "reason": "follow heartbeat"},
                        "snapshot": {"body_state": {"online": True}},
                    }
                ],
            }
        )
    )

    assert advanced["actions"][0]["step_id"] == "follow:2"
    events = action_events(request_id="req-follow")["events"]
    assert [event["event_type"] for event in events] == ["action_scheduled", "action_result", "action_scheduled"]
    assert [event["action_name"] for event in events] == ["body_move_to_requester", "body_move_to_requester", "body_move_to_requester"]
    assert "follow:2" in events[2]["payload_json"]


def test_app_records_actions_scheduled_from_observations(tmp_path) -> None:
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
    spawn = response["actions"][0]

    advanced = asyncio.run(
        observations(
            {
                "request_id": "req-spawn",
                "task_id": spawn["task_id"],
                "snapshot": {"body_state": {"online": True}},
            }
        )
    )

    assert advanced["actions"][0]["name"] == "body_move_to_requester"
    events = action_events(request_id="req-spawn")["events"]
    assert [event["event_type"] for event in events] == ["action_scheduled", "action_scheduled"]
    assert events[0]["action_name"] == "body_spawn"
    assert events[1]["action_name"] == "body_move_to_requester"


def _route(app, path: str):  # noqa: ANN001, ANN202
    for route in app.routes:
        if getattr(route, "path", "") == path:
            return route.endpoint
    raise AssertionError(f"route not found: {path}")
