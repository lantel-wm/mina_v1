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


def _route(app, path: str):  # noqa: ANN001, ANN202
    for route in app.routes:
        if getattr(route, "path", "") == path:
            return route.endpoint
    raise AssertionError(f"route not found: {path}")
