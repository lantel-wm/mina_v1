from __future__ import annotations

import asyncio
import json

import mina_agent.app as app_module
from mina_agent.config import Settings
from mina_agent.deepseek import DeepSeekResponse


def test_app_records_action_events_for_read_only_command(tmp_path, monkeypatch) -> None:
    app = _app_with_read_only_model(tmp_path, monkeypatch)
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


def test_app_exposes_tool_and_model_call_journals(tmp_path, monkeypatch) -> None:
    app = _app_with_read_only_model(tmp_path, monkeypatch, "time query daytime")
    turn = _route(app, "/v1/turn")
    tool_calls = _route(app, "/v1/tool-calls")
    model_calls = _route(app, "/v1/model-calls")

    asyncio.run(turn(_turn("查询时间", "req-time")))

    calls = tool_calls(request_id="req-time")["tool_calls"]
    assert len(calls) == 1
    assert calls[0]["tool_name"] == "run_read_only_command"
    assert calls[0]["status"] == "ok"
    assert "time query daytime" in calls[0]["args_json"]
    recorded_model_calls = model_calls(request_id="req-time")["model_calls"]
    assert len(recorded_model_calls) == 1
    assert "run_read_only_command" in recorded_model_calls[0]["tools_json"]


def test_action_results_are_loaded_into_next_turn_context(tmp_path, monkeypatch) -> None:
    fake = _FakeDeepSeek(
        [
            DeepSeekResponse(
                message={
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call-read-only",
                            "type": "function",
                            "function": {
                                "name": "run_read_only_command",
                                "arguments": json.dumps({"command": "time query day"}),
                            },
                        }
                    ],
                },
                finish_reason="tool_calls",
                usage={},
                raw={},
            ),
            DeepSeekResponse(
                message={"role": "assistant", "content": "刚才的查询结果是 The time is 1200。"},
                finish_reason="stop",
                usage={},
                raw={},
            ),
        ]
    )
    monkeypatch.setattr(app_module, "DeepSeekClient", lambda settings: fake)
    app = app_module.create_app(Settings(api_key="test", db_path=tmp_path / "mina.sqlite3", log_path=tmp_path / "mina.log"))
    turn = _route(app, "/v1/turn")
    action_results = _route(app, "/v1/action-results")

    first_response = asyncio.run(turn(_turn("查询时间", "req-time")))
    asyncio.run(
        action_results(
            {
                "request_id": "req-time",
                "action_results": [
                    {
                        "action_id": first_response["actions"][0]["id"],
                        "name": "run_read_only_command",
                        "status": "completed",
                        "command_success": True,
                        "command_results": [{"command": "time query day", "outputs": ["The time is 1200"]}],
                    }
                ],
            }
        )
    )
    second_response = asyncio.run(turn(_turn("刚才查询结果是什么？", "req-followup")))
    second_context = "\n".join(message["content"] for message in fake.calls[1]["messages"])

    assert "The time is 1200" in second_response["messages"][0]["content"]
    assert "Recent verified Minecraft command/action results" in second_context
    assert "The time is 1200" in second_context


def test_app_trace_contains_model_tool_and_action_sections_without_tasks(tmp_path, monkeypatch) -> None:
    app = _app_with_read_only_model(tmp_path, monkeypatch)
    turn = _route(app, "/v1/turn")
    traces = _route(app, "/v1/traces/{trace_id}")

    asyncio.run(turn(_turn("执行 time query day", "req-trace")))
    trace = traces(trace_id="req-trace")

    assert trace["ok"] is True
    assert trace["trace_id"] == "req-trace"
    assert len(trace["model_calls"]) == 1
    assert len(trace["tool_calls"]) == 1
    assert len(trace["action_events"]) == 1
    assert "task_events" not in trace
    assert "tasks" not in trace


def test_removed_body_endpoints_are_not_registered(tmp_path) -> None:
    app = app_module.create_app(Settings(api_key="", db_path=tmp_path / "mina.sqlite3", log_path=tmp_path / "mina.log"))
    paths = {route.path for route in app.routes}

    assert "/v1/observations" not in paths
    assert "/v1/tasks" not in paths
    assert "/v1/tasks/{task_id}" not in paths


def test_healthz_exposes_session_queue_state(tmp_path) -> None:
    app = app_module.create_app(Settings(api_key="", db_path=tmp_path / "mina.sqlite3", log_path=tmp_path / "mina.log"))
    healthz = _route(app, "/healthz")

    response = healthz()

    assert response["ok"] is True
    assert response["db"]["ok"] is True
    assert response["session_queue"]["session_count"] == 0
    assert response["session_queue"]["sessions"] == {}


def _app_with_read_only_model(tmp_path, monkeypatch, command: str = "time query day"):  # noqa: ANN001, ANN202
    fake = _FakeDeepSeek(
        [
            DeepSeekResponse(
                message={
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call-read-only",
                            "type": "function",
                            "function": {
                                "name": "run_read_only_command",
                                "arguments": json.dumps({"command": command}),
                            },
                        }
                    ],
                },
                finish_reason="tool_calls",
                usage={},
                raw={},
            )
        ]
    )
    monkeypatch.setattr(app_module, "DeepSeekClient", lambda settings: fake)
    return app_module.create_app(Settings(api_key="test", db_path=tmp_path / "mina.sqlite3", log_path=tmp_path / "mina.log"))


class _FakeDeepSeek:
    def __init__(self, responses: list[DeepSeekResponse]) -> None:
        self.responses = responses
        self.calls: list[dict] = []

    def configured(self) -> bool:
        return True

    def chat(self, messages, tools=None):  # noqa: ANN001, ANN201
        self.calls.append({"messages": messages, "tools": tools})
        if not self.responses:
            raise AssertionError("unexpected extra model call")
        return self.responses.pop(0)


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
