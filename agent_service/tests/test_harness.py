from __future__ import annotations

from typing import Any

from mina_agent.config import Settings
from mina_agent.deepseek import DeepSeekResponse
from mina_agent.harness import AgentHarness
from mina_agent.harness import _parse_args
from mina_agent.memory import MemoryStore
from mina_agent.searxng import SearxngClient
from mina_agent.tools import ToolRunner


def test_parse_args_accepts_deepseek_json_string() -> None:
    raw = '{"x": 10.5, "y": 69, "z": -7.5, "sprint": true, "jump": true}'

    parsed = _parse_args(raw)

    assert parsed == {"x": 10.5, "y": 69, "z": -7.5, "sprint": True, "jump": True}


def test_parse_args_rejects_non_object_json() -> None:
    assert _parse_args("[1, 2, 3]") == {}


def test_parse_args_rejects_invalid_json() -> None:
    assert _parse_args("{bad") == {}


class FakeSearch(SearxngClient):
    def __init__(self) -> None:
        pass

    def search(self, query: str, max_results: int = 5):
        return [{"title": "Minecraft Wiki", "url": "https://minecraft.wiki/", "content": f"Result for {query}"}]


class ToolCallingDeepSeek:
    def __init__(self) -> None:
        self.calls = 0
        self.tool_messages: list[dict[str, Any]] = []

    def configured(self) -> bool:
        return True

    def chat(self, messages, tools=None, response_format=None, max_tokens=2048):  # noqa: ANN001, ANN201
        self.calls += 1
        self.tool_messages = [message for message in messages if message.get("role") == "tool"]
        if self.calls == 1:
            return DeepSeekResponse(
                message={
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call-search",
                            "type": "function",
                            "function": {
                                "name": "web_search",
                                "arguments": '{"query": "minecraft diamond ore", "max_results": 3}',
                            },
                        }
                    ],
                },
                finish_reason="tool_calls",
                usage={"prompt_tokens": 1},
                raw={},
            )
        assert self.tool_messages
        assert "Minecraft Wiki" in self.tool_messages[-1]["content"]
        return DeepSeekResponse(
            message={"role": "assistant", "content": "我查到了 Minecraft Wiki 的相关结果。"},
            finish_reason="stop",
            usage={"completion_tokens": 1},
            raw={},
        )


class ContextInspectingDeepSeek:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    def configured(self) -> bool:
        return True

    def chat(self, messages, tools=None, response_format=None, max_tokens=2048):  # noqa: ANN001, ANN201
        self.messages = messages
        context = "\n".join(str(message.get("content") or "") for message in messages)
        assert '"active_task"' in context
        assert '"type": "follow_player"' in context
        assert '"status": "active"' in context
        return DeepSeekResponse(
            message={"role": "assistant", "content": "当前任务是跟随玩家。"},
            finish_reason="stop",
            usage={"completion_tokens": 1},
            raw={},
        )


class StatusCallingDeepSeek:
    def __init__(self) -> None:
        self.calls = 0
        self.tool_messages: list[dict[str, Any]] = []

    def configured(self) -> bool:
        return True

    def chat(self, messages, tools=None, response_format=None, max_tokens=2048):  # noqa: ANN001, ANN201
        self.calls += 1
        self.tool_messages = [message for message in messages if message.get("role") == "tool"]
        if self.calls == 1:
            return DeepSeekResponse(
                message={
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call-status",
                            "type": "function",
                            "function": {
                                "name": "task_status",
                                "arguments": "{}",
                            },
                        }
                    ],
                },
                finish_reason="tool_calls",
                usage={"prompt_tokens": 1},
                raw={},
            )
        assert self.tool_messages
        assert '"last_error": null' in self.tool_messages[-1]["content"]
        assert '"type": "follow_player"' in self.tool_messages[-1]["content"]
        return DeepSeekResponse(
            message={"role": "assistant", "content": "当前任务：follow_player，状态：active。"},
            finish_reason="stop",
            usage={"completion_tokens": 1},
            raw={},
        )


class ActionDispatchDeepSeek:
    def __init__(self) -> None:
        self.calls = 0

    def configured(self) -> bool:
        return True

    def chat(self, messages, tools=None, response_format=None, max_tokens=2048):  # noqa: ANN001, ANN201
        self.calls += 1
        if self.calls > 1:
            raise AssertionError("harness should dispatch Fabric actions before another model subturn")
        return DeepSeekResponse(
            message={
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-follow",
                        "type": "function",
                        "function": {
                            "name": "start_body_task",
                            "arguments": '{"task_type": "follow_player", "target_hint": "me"}',
                        },
                    }
                ],
            },
            finish_reason="tool_calls",
            usage={"prompt_tokens": 1},
            raw={},
        )


class MultiActionDispatchDeepSeek:
    def __init__(self) -> None:
        self.calls = 0

    def configured(self) -> bool:
        return True

    def chat(self, messages, tools=None, response_format=None, max_tokens=2048):  # noqa: ANN001, ANN201
        self.calls += 1
        if self.calls > 1:
            raise AssertionError("harness should not request another model subturn after action dispatch")
        return DeepSeekResponse(
            message={
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-follow",
                        "type": "function",
                        "function": {
                            "name": "start_body_task",
                            "arguments": '{"task_type": "follow_player", "target_hint": "me"}',
                        },
                    },
                    {
                        "id": "call-chop",
                        "type": "function",
                        "function": {
                            "name": "start_body_task",
                            "arguments": '{"task_type": "chop_tree", "target_hint": "nearby tree"}',
                        },
                    },
                ],
            },
            finish_reason="tool_calls",
            usage={"prompt_tokens": 1},
            raw={},
        )


class UnconfiguredDeepSeek:
    def configured(self) -> bool:
        return False


def test_harness_completes_web_search_tool_loop(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    deepseek = ToolCallingDeepSeek()
    harness = AgentHarness(Settings(api_key="test", db_path=tmp_path / "mina.sqlite3"), memory, deepseek, tools)  # type: ignore[arg-type]

    response = harness.run_turn(
        {
            "request_id": "req-1",
            "trigger": "command",
            "message": "帮我查一下 diamond ore",
            "player": {"uuid": "player-1", "name": "Tester"},
            "permissions": {"can_use_actions": True},
            "snapshot": {},
        }
    )

    assert response["messages"][0]["content"] == "我查到了 Minecraft Wiki 的相关结果。"
    assert deepseek.calls == 2
    calls = memory.recent_tool_calls(request_id="req-1", limit=10)
    assert [call["tool_name"] for call in calls] == ["web_search"]
    assert calls[0]["status"] == "ok"


def test_harness_dispatches_fabric_action_before_next_model_subturn(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    deepseek = ActionDispatchDeepSeek()
    harness = AgentHarness(Settings(api_key="test", db_path=tmp_path / "mina.sqlite3"), memory, deepseek, tools)  # type: ignore[arg-type]

    response = harness.run_turn(
        {
            "request_id": "req-action-barrier",
            "trigger": "command",
            "message": "跟随我",
            "player": {"uuid": "player-1", "name": "Tester"},
            "permissions": {"can_use_actions": True},
            "snapshot": {"body_state": {"online": True}},
        }
    )

    assert deepseek.calls == 1
    assert response["actions"][0]["name"] == "body_move_to_requester"
    assert "我开始跟随你" in response["messages"][0]["content"]
    assert response["debug"]["action_barrier"] is True


def test_harness_action_barrier_ignores_later_action_tool_calls(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    deepseek = MultiActionDispatchDeepSeek()
    harness = AgentHarness(Settings(api_key="test", db_path=tmp_path / "mina.sqlite3"), memory, deepseek, tools)  # type: ignore[arg-type]

    response = harness.run_turn(
        {
            "request_id": "req-multi-action-barrier",
            "trigger": "command",
            "message": "同时跟随并砍树",
            "player": {"uuid": "player-1", "name": "Tester"},
            "permissions": {"can_use_actions": True},
            "snapshot": {
                "body_state": {"online": True},
                "nearby_blocks": {
                    "requester": [
                        {
                            "block": "minecraft:spruce_log",
                            "category": "log",
                            "x": 2,
                            "y": 80,
                            "z": 0,
                            "center_x": 2.5,
                            "center_y": 80.5,
                            "center_z": 0.5,
                            "distance": 3.0,
                            "approach_x": 2.5,
                            "approach_y": 80,
                            "approach_z": -0.5,
                        }
                    ]
                },
            },
        }
    )

    assert deepseek.calls == 1
    assert [action["name"] for action in response["actions"]] == ["body_move_to_requester"]
    calls = memory.recent_tool_calls(request_id="req-multi-action-barrier", limit=10)
    assert [call["tool_name"] for call in calls] == ["start_body_task"]
    assert "follow_player" in calls[0]["args_json"]
    assert "chop_tree" not in calls[0]["args_json"]
    tasks = tools.skills.list_tasks()
    assert [task["type"] for task in tasks] == ["follow_player"]


def test_harness_injects_current_task_into_context(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    turn = {
        "request_id": "req-start",
        "trigger": "command",
        "message": "跟随我",
        "player": {"uuid": "player-1", "name": "Tester"},
        "permissions": {"can_use_actions": True},
        "snapshot": {"body_state": {"online": True}},
    }
    started = tools.run("start_body_task", {"task_type": "follow_player"}, turn)
    assert started.actions

    deepseek = ContextInspectingDeepSeek()
    harness = AgentHarness(Settings(api_key="test", db_path=tmp_path / "mina.sqlite3"), memory, deepseek, tools)  # type: ignore[arg-type]
    response = harness.run_turn(
        {
            "request_id": "req-status",
            "trigger": "command",
            "message": "现在状态如何",
            "player": {"uuid": "player-1", "name": "Tester"},
            "permissions": {"can_use_actions": True},
            "snapshot": {"body_state": {"online": True}},
        }
    )

    assert response["messages"][0]["content"] == "当前任务是跟随玩家。"


def test_harness_records_model_status_tool_result_as_ok(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    turn = {
        "request_id": "req-start",
        "trigger": "command",
        "message": "跟随我",
        "player": {"uuid": "player-1", "name": "Tester"},
        "permissions": {"can_use_actions": True},
        "snapshot": {"body_state": {"online": True}},
    }
    started = tools.run("start_body_task", {"task_type": "follow_player"}, turn)
    assert started.actions

    deepseek = StatusCallingDeepSeek()
    harness = AgentHarness(Settings(api_key="test", db_path=tmp_path / "mina.sqlite3"), memory, deepseek, tools)  # type: ignore[arg-type]
    response = harness.run_turn(
        {
            "request_id": "req-model-status",
            "trigger": "command",
            "message": "状态",
            "player": {"uuid": "player-1", "name": "Tester"},
            "permissions": {"can_use_actions": True},
            "snapshot": {"body_state": {"online": True}},
        }
    )

    assert response["messages"][0]["content"] == "当前任务：follow_player，状态：active。"
    assert deepseek.calls == 2
    calls = memory.recent_tool_calls(request_id="req-model-status", limit=10)
    assert [call["tool_name"] for call in calls] == ["task_status"]
    assert calls[0]["status"] == "ok"


def test_harness_offline_fallback_can_start_follow_task(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    harness = AgentHarness(Settings(api_key="", db_path=tmp_path / "mina.sqlite3"), memory, UnconfiguredDeepSeek(), tools)  # type: ignore[arg-type]

    response = harness.run_turn(
        {
            "request_id": "req-offline-follow",
            "trigger": "command",
            "message": "跟随我",
            "player": {"uuid": "player-1", "name": "Tester"},
            "permissions": {"can_use_actions": True},
            "snapshot": {"body_state": {"online": True}},
        }
    )

    assert "我开始跟随你" in response["messages"][0]["content"]
    assert response["actions"][0]["name"] == "body_move_to_requester"
    assert response["debug"]["offline_fallback"] is True


def test_harness_offline_fallback_records_status_and_stop_tool_calls(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    harness = AgentHarness(Settings(api_key="", db_path=tmp_path / "mina.sqlite3"), memory, UnconfiguredDeepSeek(), tools)  # type: ignore[arg-type]
    base_turn = {
        "trigger": "command",
        "player": {"uuid": "player-1", "name": "Tester"},
        "permissions": {"can_use_actions": True},
        "snapshot": {"body_state": {"online": True}},
    }

    harness.run_turn({"request_id": "req-start", "message": "跟随我", **base_turn})
    status = harness.run_turn({"request_id": "req-status", "message": "状态", **base_turn})
    stopped = harness.run_turn({"request_id": "req-stop", "message": "停止跟随", **base_turn})

    assert "当前任务：follow_player" in status["messages"][0]["content"]
    assert "我已经停止当前身体任务" in stopped["messages"][0]["content"]
    assert [call["tool_name"] for call in memory.recent_tool_calls(request_id="req-status", limit=10)] == ["task_status"]
    assert [call["tool_name"] for call in memory.recent_tool_calls(request_id="req-stop", limit=10)] == ["stop_body_task"]


def test_harness_offline_fallback_can_schedule_read_only_command(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    harness = AgentHarness(Settings(api_key="", db_path=tmp_path / "mina.sqlite3"), memory, UnconfiguredDeepSeek(), tools)  # type: ignore[arg-type]

    response = harness.run_turn(
        {
            "request_id": "req-offline-time",
            "trigger": "command",
            "message": "查询时间",
            "player": {"uuid": "player-1", "name": "Tester"},
            "permissions": {"can_use_actions": False},
            "snapshot": {},
        }
    )

    assert response["actions"][0]["name"] == "run_read_only_command"
    assert response["actions"][0]["args"]["command"] == "time query daytime"


def test_harness_offline_fallback_can_return_search_results(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    harness = AgentHarness(Settings(api_key="", db_path=tmp_path / "mina.sqlite3"), memory, UnconfiguredDeepSeek(), tools)  # type: ignore[arg-type]

    response = harness.run_turn(
        {
            "request_id": "req-offline-search",
            "trigger": "command",
            "message": "查资料 diamond ore",
            "player": {"uuid": "player-1", "name": "Tester"},
            "permissions": {"can_use_actions": False},
            "snapshot": {},
        }
    )

    assert "搜索结果" in response["messages"][0]["content"]
    assert "Minecraft Wiki" in response["messages"][0]["content"]
    calls = memory.recent_tool_calls(request_id="req-offline-search", limit=10)
    assert [call["tool_name"] for call in calls] == ["web_search"]


def test_harness_offline_fallback_still_reports_missing_key_for_complex_request(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    harness = AgentHarness(Settings(api_key="", db_path=tmp_path / "mina.sqlite3"), memory, UnconfiguredDeepSeek(), tools)  # type: ignore[arg-type]

    response = harness.run_turn(
        {
            "request_id": "req-offline-complex",
            "trigger": "command",
            "message": "帮我规划一个自动农场",
            "player": {"uuid": "player-1", "name": "Tester"},
            "permissions": {"can_use_actions": False},
            "snapshot": {},
        }
    )

    assert "MINA_API_KEY is not configured" in response["messages"][0]["content"]


def test_harness_offline_fallback_does_not_chop_for_tree_planning_request(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    harness = AgentHarness(Settings(api_key="", db_path=tmp_path / "mina.sqlite3"), memory, UnconfiguredDeepSeek(), tools)  # type: ignore[arg-type]

    response = harness.run_turn(
        {
            "request_id": "req-offline-tree-plan",
            "trigger": "command",
            "message": "help me plan a tree farm",
            "player": {"uuid": "player-1", "name": "Tester"},
            "permissions": {"can_use_actions": True},
            "snapshot": {"body_state": {"online": True}},
        }
    )

    assert "MINA_API_KEY is not configured" in response["messages"][0]["content"]
    assert response.get("actions", []) == []


def test_harness_offline_fallback_still_chops_for_explicit_tree_action(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    harness = AgentHarness(Settings(api_key="", db_path=tmp_path / "mina.sqlite3"), memory, UnconfiguredDeepSeek(), tools)  # type: ignore[arg-type]

    response = harness.run_turn(
        {
            "request_id": "req-offline-chop",
            "trigger": "command",
            "message": "chop tree",
            "player": {"uuid": "player-1", "name": "Tester"},
            "permissions": {"can_use_actions": True},
            "snapshot": {
                "body_state": {"online": True},
                "nearby_blocks": {
                    "requester": [
                        {
                            "block": "minecraft:oak_log",
                            "category": "log",
                            "x": 2,
                            "y": 80,
                            "z": 0,
                            "center_x": 2.5,
                            "center_y": 80.5,
                            "center_z": 0.5,
                            "distance": 3.0,
                            "approach_x": 2.5,
                            "approach_y": 80,
                            "approach_z": -0.5,
                        }
                    ]
                },
            },
        }
    )

    assert response["actions"][0]["name"] == "body_move_to_position"


def test_harness_offline_fallback_preserves_body_task_failure_message(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    harness = AgentHarness(Settings(api_key="", db_path=tmp_path / "mina.sqlite3"), memory, UnconfiguredDeepSeek(), tools)  # type: ignore[arg-type]

    response = harness.run_turn(
        {
            "request_id": "req-offline-unreachable-chop",
            "trigger": "command",
            "message": "chop tree",
            "player": {"uuid": "player-1", "name": "Tester"},
            "permissions": {"can_use_actions": True},
            "snapshot": {
                "body_state": {"online": True},
                "nearby_blocks": {
                    "requester": [
                        {
                            "block": "minecraft:oak_log",
                            "category": "log",
                            "x": 2,
                            "y": 80,
                            "z": 0,
                            "center_x": 2.5,
                            "center_y": 80.5,
                            "center_z": 0.5,
                            "distance": 3.0,
                        }
                    ]
                },
            },
        }
    )

    assert response.get("actions", []) == []
    assert "没有找到可安全接近的原木" in response["messages"][0]["content"]
