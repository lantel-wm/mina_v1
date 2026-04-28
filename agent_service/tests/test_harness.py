from __future__ import annotations

import json
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


class DangerousReadOnlyCommandDeepSeek:
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
                            "id": "call-setblock",
                            "type": "function",
                            "function": {
                                "name": "run_read_only_command",
                                "arguments": '{"command": "setblock 0 80 0 minecraft:air"}',
                            },
                        }
                    ],
                },
                finish_reason="tool_calls",
                usage={"prompt_tokens": 1},
                raw={},
            )
        assert self.tool_messages
        assert "Only read-only commands" in self.tool_messages[-1]["content"]
        return DeepSeekResponse(
            message={"role": "assistant", "content": "我不能执行写命令。"},
            finish_reason="stop",
            usage={"completion_tokens": 1},
            raw={},
        )


class EmptyDeepSeek:
    def configured(self) -> bool:
        return True

    def chat(self, messages, tools=None, response_format=None, max_tokens=2048):  # noqa: ANN001, ANN201
        return DeepSeekResponse(
            message={"role": "assistant", "content": ""},
            finish_reason="stop",
            usage={"completion_tokens": 0},
            raw={},
        )


class DirectAnswerDeepSeek:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls = 0

    def configured(self) -> bool:
        return True

    def chat(self, messages, tools=None, response_format=None, max_tokens=2048):  # noqa: ANN001, ANN201
        self.calls += 1
        return DeepSeekResponse(
            message={"role": "assistant", "content": self.content},
            finish_reason="stop",
            usage={"completion_tokens": 1},
            raw={},
        )


class RecallRepairDeepSeek:
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
                message={"role": "assistant", "content": "记得，RecallCode 是 Emerald-2718。"},
                finish_reason="stop",
                usage={"completion_tokens": 1},
                raw={},
            )
        if self.calls == 2:
            return DeepSeekResponse(
                message={
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call-memory-search",
                            "type": "function",
                            "function": {
                                "name": "memory_search",
                                "arguments": '{"query": "RecallCode", "limit": 5}',
                            },
                        }
                    ],
                },
                finish_reason="tool_calls",
                usage={"prompt_tokens": 1},
                raw={},
            )
        assert self.tool_messages
        assert "Emerald-2718" in self.tool_messages[-1]["content"]
        return DeepSeekResponse(
            message={"role": "assistant", "content": "记得，RecallCode 是 Emerald-2718。"},
            finish_reason="stop",
            usage={"completion_tokens": 1},
            raw={},
        )


class FailIfCalledDeepSeek:
    def __init__(self) -> None:
        self.calls = 0

    def configured(self) -> bool:
        return True

    def chat(self, messages, tools=None, response_format=None, max_tokens=2048):  # noqa: ANN001, ANN201
        self.calls += 1
        raise AssertionError("request should be handled before the main model")


class UnconfiguredDeepSeek:
    def configured(self) -> bool:
        return False


def test_harness_companion_cooldown_is_per_alert_reason(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    deepseek = FailIfCalledDeepSeek()
    harness = AgentHarness(
        Settings(api_key="test", db_path=tmp_path / "mina.sqlite3", emergency_cooldown_seconds=300),
        memory,
        deepseek,
        tools,
    )  # type: ignore[arg-type]
    base_turn = {
        "trigger": "companion_tick",
        "message": "",
        "player": {"uuid": "player-1", "name": "Tester"},
        "permissions": {"can_use_actions": True},
    }

    health = harness.run_turn(
        {
            **base_turn,
            "request_id": "companion-health",
            "snapshot": {"player_state": {"health": 4, "food": 20}, "nearby_entities": []},
        }
    )
    hunger = harness.run_turn(
        {
            **base_turn,
            "request_id": "companion-hunger",
            "snapshot": {"player_state": {"health": 20, "food": 4}, "nearby_entities": []},
        }
    )
    repeated_hunger = harness.run_turn(
        {
            **base_turn,
            "request_id": "companion-hunger-repeat",
            "snapshot": {"player_state": {"health": 20, "food": 4}, "nearby_entities": []},
        }
    )

    assert "血量很低" in health["messages"][0]["content"]
    assert "饥饿值偏低" in hunger["messages"][0]["content"]
    assert repeated_hunger["messages"] == []
    assert deepseek.calls == 0


def test_harness_answers_player_state_from_snapshot_without_model_or_tools(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    deepseek = FailIfCalledDeepSeek()
    harness = AgentHarness(Settings(api_key="test", db_path=tmp_path / "mina.sqlite3"), memory, deepseek, tools)  # type: ignore[arg-type]

    response = harness.run_turn(
        {
            "request_id": "req-player-observation",
            "trigger": "command",
            "message": "我的状态和坐标怎么样？",
            "player": {"uuid": "player-1", "name": "Tester"},
            "permissions": {"can_use_actions": True},
            "snapshot": {
                "player_state": {
                    "health": 12.5,
                    "max_health": 20,
                    "food": 7,
                    "game_mode": "survival",
                    "dimension": "minecraft:overworld",
                    "x": 1.25,
                    "y": 80,
                    "z": -2.5,
                }
            },
        }
    )

    content = response["messages"][0]["content"]
    assert "坐标 (1.25, 80, -2.5)" in content
    assert "生命 12.5/20" in content
    assert "饥饿 7" in content
    assert response["debug"]["intent"] == "player_observation"
    assert deepseek.calls == 0
    assert memory.recent_tool_calls(request_id="req-player-observation", limit=10) == []


def test_harness_answers_bare_status_from_snapshot_when_no_body_task(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    deepseek = FailIfCalledDeepSeek()
    harness = AgentHarness(Settings(api_key="test", db_path=tmp_path / "mina.sqlite3"), memory, deepseek, tools)  # type: ignore[arg-type]

    response = harness.run_turn(
        {
            "request_id": "req-bare-status-player-observation",
            "trigger": "command",
            "message": "状态",
            "player": {"uuid": "player-1", "name": "Tester"},
            "permissions": {"can_use_actions": True},
            "snapshot": {
                "player_state": {
                    "health": 19,
                    "max_health": 20,
                    "food": 18,
                    "game_mode": "survival",
                    "dimension": "minecraft:overworld",
                    "x": 0.5,
                    "y": 80,
                    "z": -2.5,
                }
            },
        }
    )

    content = response["messages"][0]["content"]
    assert "生命 19/20" in content
    assert "饥饿 18" in content
    assert "坐标 (0.5, 80, -2.5)" in content
    assert response["debug"]["intent"] == "player_observation"
    assert deepseek.calls == 0
    assert memory.recent_tool_calls(request_id="req-bare-status-player-observation", limit=10) == []


def test_harness_answers_body_position_from_snapshot_without_model_or_tools(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    deepseek = FailIfCalledDeepSeek()
    harness = AgentHarness(Settings(api_key="test", db_path=tmp_path / "mina.sqlite3"), memory, deepseek, tools)  # type: ignore[arg-type]

    response = harness.run_turn(
        {
            "request_id": "req-body-observation",
            "trigger": "command",
            "message": "Mina 的身体在哪？",
            "player": {"uuid": "player-1", "name": "Tester"},
            "permissions": {"can_use_actions": True},
            "snapshot": {
                "body_state": {
                    "online": True,
                    "dimension": "minecraft:overworld",
                    "x": 3.5,
                    "y": 80,
                    "z": -1.5,
                    "distance_to_requester": 4.25,
                    "health": 20,
                }
            },
        }
    )

    content = response["messages"][0]["content"]
    assert "Mina body 当前在线" in content
    assert "坐标 (3.5, 80, -1.5)" in content
    assert "距离你 4.25 格" in content
    assert response["debug"]["intent"] == "body_observation"
    assert deepseek.calls == 0
    assert memory.recent_tool_calls(request_id="req-body-observation", limit=10) == []


def test_harness_sanitizes_model_markdown_for_minecraft_chat(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    deepseek = DirectAnswerDeepSeek("已保存：**Quartz-1729** ✅\n- 可以运行 `seed` 查询。")
    harness = AgentHarness(Settings(api_key="test", db_path=tmp_path / "mina.sqlite3"), memory, deepseek, tools)  # type: ignore[arg-type]

    response = harness.run_turn(
        {
            "request_id": "req-chat-style",
            "trigger": "command",
            "message": "随便回答一句",
            "player": {"uuid": "player-1", "name": "Tester"},
            "permissions": {"can_use_actions": True},
            "snapshot": {},
        }
    )

    content = response["messages"][0]["content"]
    assert content == "已保存：Quartz-1729\n可以运行 seed 查询。"
    assert deepseek.calls == 1


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


def test_harness_routes_memory_recall_without_model(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    memory.add_event("player-1", "player_fact", {"content": "RecallCode=Emerald-2718"}, importance=4)
    tools = ToolRunner(memory, FakeSearch())
    deepseek = FailIfCalledDeepSeek()
    harness = AgentHarness(Settings(api_key="test", db_path=tmp_path / "mina.sqlite3"), memory, deepseek, tools)  # type: ignore[arg-type]

    response = harness.run_turn(
        {
            "request_id": "req-recall-repair",
            "trigger": "command",
            "message": "你还记得 RecallCode 吗？",
            "player": {"uuid": "player-1", "name": "Tester"},
            "permissions": {"can_use_actions": True},
            "snapshot": {},
        }
    )

    assert "Emerald-2718" in response["messages"][0]["content"]
    assert deepseek.calls == 0
    calls = memory.recent_tool_calls(request_id="req-recall-repair", limit=10)
    assert [call["tool_name"] for call in calls] == ["memory_search"]
    assert calls[0]["status"] == "ok"


def test_harness_records_model_call_journal(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    deepseek = ToolCallingDeepSeek()
    harness = AgentHarness(Settings(api_key="test", db_path=tmp_path / "mina.sqlite3"), memory, deepseek, tools)  # type: ignore[arg-type]

    harness.run_turn(
        {
            "request_id": "req-model",
            "trigger": "command",
            "message": "帮我查一下 diamond ore",
            "player": {"uuid": "player-1", "name": "Tester"},
            "permissions": {"can_use_actions": True},
            "snapshot": {},
        }
    )

    calls = memory.recent_model_calls(request_id="req-model", limit=10)
    assert [call["status"] for call in calls] == ["ok", "ok"]
    assert [call["subturn"] for call in calls] == [1, 2]
    assert "web_search" in calls[0]["tools_json"]
    assert "web_search" in calls[0]["response_json"]


def test_harness_dispatches_fabric_action_before_next_model_subturn(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    deepseek = ActionDispatchDeepSeek()
    harness = AgentHarness(Settings(api_key="test", db_path=tmp_path / "mina.sqlite3"), memory, deepseek, tools)  # type: ignore[arg-type]

    response = harness.run_turn(
        {
            "request_id": "req-action-barrier",
            "trigger": "command",
            "message": "model dispatch test",
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
            "message": "model multi dispatch test",
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


def test_harness_returns_visible_fallback_for_empty_model_response(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    harness = AgentHarness(Settings(api_key="test", db_path=tmp_path / "mina.sqlite3"), memory, EmptyDeepSeek(), tools)  # type: ignore[arg-type]

    response = harness.run_turn(
        {
            "request_id": "req-empty-model",
            "trigger": "command",
            "message": "你能做什么",
            "player": {"uuid": "player-1", "name": "Tester"},
            "permissions": {"can_use_actions": True},
            "snapshot": {},
        }
    )

    assert response["messages"][0]["content"] == "我没有生成可执行回应，请换个说法或补充目标。"
    assert response["actions"] == []
    assert response["debug"]["empty_model_fallback"] is True
    recent = memory.recent_conversation("player-1", limit=4)
    assert recent[-1]["role"] == "assistant"
    assert "补充目标" in recent[-1]["content"]


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
            "message": "model context inspect",
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
            "message": "model inspection check",
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


def test_harness_body_subagent_handles_configured_follow_without_model_call(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    deepseek = FailIfCalledDeepSeek()
    harness = AgentHarness(Settings(api_key="test", db_path=tmp_path / "mina.sqlite3"), memory, deepseek, tools)  # type: ignore[arg-type]

    response = harness.run_turn(
        {
            "request_id": "req-body-subagent-follow",
            "trigger": "command",
            "message": "跟着我",
            "player": {"uuid": "player-1", "name": "Tester"},
            "permissions": {"can_use_actions": True},
            "snapshot": {"body_state": {"online": True}},
        }
    )

    assert deepseek.calls == 0
    assert "我开始跟随你" in response["messages"][0]["content"]
    assert response["actions"][0]["name"] == "body_move_to_requester"
    assert response["debug"]["body_subagent"] is True
    calls = memory.recent_tool_calls(request_id="req-body-subagent-follow", limit=10)
    assert [call["tool_name"] for call in calls] == ["start_body_task"]


def test_harness_body_subagent_treats_negative_follow_as_stop(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    deepseek = FailIfCalledDeepSeek()
    harness = AgentHarness(Settings(api_key="test", db_path=tmp_path / "mina.sqlite3"), memory, deepseek, tools)  # type: ignore[arg-type]
    base_turn = {
        "trigger": "command",
        "player": {"uuid": "player-1", "name": "Tester"},
        "permissions": {"can_use_actions": True},
        "snapshot": {"body_state": {"online": True}},
    }

    harness.run_turn({"request_id": "req-negative-start-follow", "message": "跟随我", **base_turn})
    response = harness.run_turn({"request_id": "req-negative-stop-follow", "message": "别跟着我", **base_turn})

    assert deepseek.calls == 0
    assert "我已经停止当前身体任务" in response["messages"][0]["content"]
    assert response["actions"][0]["name"] == "body_stop"
    calls = memory.recent_tool_calls(request_id="req-negative-stop-follow", limit=10)
    assert [call["tool_name"] for call in calls] == ["stop_body_task"]


def test_harness_body_subagent_handles_short_stop_without_model_call(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    deepseek = FailIfCalledDeepSeek()
    harness = AgentHarness(Settings(api_key="test", db_path=tmp_path / "mina.sqlite3"), memory, deepseek, tools)  # type: ignore[arg-type]
    base_turn = {
        "trigger": "command",
        "player": {"uuid": "player-1", "name": "Tester"},
        "permissions": {"can_use_actions": True},
        "snapshot": {"body_state": {"online": True}},
    }

    harness.run_turn({"request_id": "req-short-stop-start", "message": "跟随我", **base_turn})
    response = harness.run_turn({"request_id": "req-short-stop", "message": "停下", **base_turn})

    assert deepseek.calls == 0
    assert "我已经停止当前身体任务" in response["messages"][0]["content"]
    assert response["actions"][0]["name"] == "body_stop"
    calls = memory.recent_tool_calls(request_id="req-short-stop", limit=10)
    assert [call["tool_name"] for call in calls] == ["stop_body_task"]


def test_harness_body_subagent_handles_referential_chop_without_model_call(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    deepseek = FailIfCalledDeepSeek()
    harness = AgentHarness(Settings(api_key="test", db_path=tmp_path / "mina.sqlite3"), memory, deepseek, tools)  # type: ignore[arg-type]

    response = harness.run_turn(
        {
            "request_id": "req-referential-chop",
            "trigger": "command",
            "message": "帮我把这棵树砍了",
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

    assert deepseek.calls == 0
    assert "我开始砍树" in response["messages"][0]["content"]
    assert response["actions"][0]["name"] == "body_move_to_position"
    calls = memory.recent_tool_calls(request_id="req-referential-chop", limit=10)
    assert [call["tool_name"] for call in calls] == ["start_body_task"]


def test_harness_body_subagent_handles_colloquial_chop_without_model_call(tmp_path) -> None:
    for index, message in enumerate(("帮我挖点木头", "帮我撸树", "break some logs")):
        memory = MemoryStore(tmp_path / f"mina-{index}.sqlite3")
        tools = ToolRunner(memory, FakeSearch())
        deepseek = FailIfCalledDeepSeek()
        harness = AgentHarness(Settings(api_key="test", db_path=tmp_path / f"mina-{index}.sqlite3"), memory, deepseek, tools)  # type: ignore[arg-type]

        response = harness.run_turn(
            {
                "request_id": f"req-colloquial-chop-{index}",
                "trigger": "command",
                "message": message,
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

        assert deepseek.calls == 0
        assert "我开始砍树" in response["messages"][0]["content"]
        assert response["actions"][0]["name"] == "body_move_to_position"
        calls = memory.recent_tool_calls(request_id=f"req-colloquial-chop-{index}", limit=10)
        assert [call["tool_name"] for call in calls] == ["start_body_task"]


def test_harness_body_subagent_treats_negative_colloquial_chop_as_stop(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    deepseek = FailIfCalledDeepSeek()
    harness = AgentHarness(Settings(api_key="test", db_path=tmp_path / "mina.sqlite3"), memory, deepseek, tools)  # type: ignore[arg-type]
    base_turn = {
        "trigger": "command",
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

    harness.run_turn({"request_id": "req-colloquial-chop-start", "message": "帮我挖点木头", **base_turn})
    response = harness.run_turn({"request_id": "req-colloquial-chop-stop", "message": "别撸树了", **base_turn})

    assert deepseek.calls == 0
    assert "我已经停止当前身体任务" in response["messages"][0]["content"]
    assert response["actions"][0]["name"] == "body_stop"
    calls = memory.recent_tool_calls(request_id="req-colloquial-chop-stop", limit=10)
    assert [call["tool_name"] for call in calls] == ["stop_body_task"]


def test_harness_body_subagent_does_not_intercept_tree_planning_request(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    deepseek = DirectAnswerDeepSeek("砍树时先找到原木，再保持合适距离持续攻击。")
    harness = AgentHarness(Settings(api_key="test", db_path=tmp_path / "mina.sqlite3"), memory, deepseek, tools)  # type: ignore[arg-type]

    response = harness.run_turn(
        {
            "request_id": "req-body-tree-planning",
            "trigger": "command",
            "message": "请告诉我怎么砍树，不要控制身体。",
            "player": {"uuid": "player-1", "name": "Tester"},
            "permissions": {"can_use_actions": True},
            "snapshot": {"body_state": {"online": True}},
        }
    )

    assert deepseek.calls == 1
    assert response.get("actions", []) == []
    assert "砍树时" in response["messages"][0]["content"]
    assert "body_subagent" not in response.get("debug", {})
    assert memory.recent_tool_calls(request_id="req-body-tree-planning", limit=10) == []


def test_harness_body_subagent_does_not_intercept_stop_instruction_question(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    deepseek = DirectAnswerDeepSeek("可以说“停止跟随”或“别跟着我”。")
    harness = AgentHarness(Settings(api_key="test", db_path=tmp_path / "mina.sqlite3"), memory, deepseek, tools)  # type: ignore[arg-type]

    response = harness.run_turn(
        {
            "request_id": "req-body-stop-instruction",
            "trigger": "command",
            "message": "请告诉我怎么停止跟随。",
            "player": {"uuid": "player-1", "name": "Tester"},
            "permissions": {"can_use_actions": True},
            "snapshot": {"body_state": {"online": True}},
        }
    )

    assert deepseek.calls == 1
    assert response.get("actions", []) == []
    assert "停止跟随" in response["messages"][0]["content"]
    assert "body_subagent" not in response.get("debug", {})
    assert memory.recent_tool_calls(request_id="req-body-stop-instruction", limit=10) == []


def test_harness_body_subagent_replaces_follow_with_chop_in_one_turn(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    deepseek = FailIfCalledDeepSeek()
    harness = AgentHarness(Settings(api_key="test", db_path=tmp_path / "mina.sqlite3"), memory, deepseek, tools)  # type: ignore[arg-type]
    base_turn = {
        "trigger": "command",
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

    harness.run_turn({"request_id": "req-start-follow", "message": "跟随我", **base_turn})
    response = harness.run_turn({"request_id": "req-chop-replaces-follow", "message": "帮我砍树", **base_turn})

    assert deepseek.calls == 0
    assert "我开始砍树" in response["messages"][0]["content"]
    assert [action["name"] for action in response["actions"][:2]] == ["body_stop", "body_move_to_position"]
    calls = memory.recent_tool_calls(request_id="req-chop-replaces-follow", limit=10)
    assert [call["tool_name"] for call in calls] == ["start_body_task"]
    tasks = tools.skills.list_tasks()
    active = [task for task in tasks if task["status"] == "active"]
    cancelled = [task for task in tasks if task["status"] == "cancelled"]
    assert [task["type"] for task in active] == ["chop_tree"]
    assert [task["type"] for task in cancelled] == ["follow_player"]


def test_harness_rejects_model_write_command_tool_call_without_action(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    deepseek = DangerousReadOnlyCommandDeepSeek()
    harness = AgentHarness(Settings(api_key="test", db_path=tmp_path / "mina.sqlite3"), memory, deepseek, tools)  # type: ignore[arg-type]

    response = harness.run_turn(
        {
            "request_id": "req-dangerous-command",
            "trigger": "command",
            "message": "model dangerous command test",
            "player": {"uuid": "player-1", "name": "Tester"},
            "permissions": {"can_use_actions": True},
            "snapshot": {},
        }
    )

    assert deepseek.calls == 2
    assert response["actions"] == []
    assert response["messages"][0]["content"] == "我不能执行写命令。"
    calls = memory.recent_tool_calls(request_id="req-dangerous-command", limit=10)
    assert [call["tool_name"] for call in calls] == ["run_read_only_command"]
    assert calls[0]["status"] == "error"
    assert "setblock" in calls[0]["args_json"]


def test_harness_local_read_only_router_schedules_without_model_when_configured(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    deepseek = FailIfCalledDeepSeek()
    harness = AgentHarness(Settings(api_key="test", db_path=tmp_path / "mina.sqlite3"), memory, deepseek, tools)  # type: ignore[arg-type]

    response = harness.run_turn(
        {
            "request_id": "req-local-read-only-time",
            "trigger": "command",
            "message": "查询当前游戏时间",
            "player": {"uuid": "player-1", "name": "Tester"},
            "permissions": {"can_use_actions": False},
            "snapshot": {},
        }
    )

    assert deepseek.calls == 0
    assert response["messages"][0]["content"] == "我会执行这个只读查询。"
    assert response["actions"][0]["name"] == "run_read_only_command"
    assert response["actions"][0]["args"]["command"] == "time query daytime"
    assert response["debug"] == {"local_read_only": True, "command": "time query daytime"}
    calls = memory.recent_tool_calls(request_id="req-local-read-only-time", limit=10)
    assert [call["tool_name"] for call in calls] == ["run_read_only_command"]


def test_harness_local_read_only_router_accepts_literal_allowed_commands(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    deepseek = FailIfCalledDeepSeek()
    harness = AgentHarness(Settings(api_key="test", db_path=tmp_path / "mina.sqlite3"), memory, deepseek, tools)  # type: ignore[arg-type]

    cases = [
        ("req-literal-time", "time query gametime", "time query gametime"),
        ("req-literal-weather", "/weather query", "weather query"),
        ("req-literal-list-uuids", "只读命令：list uuids", "list uuids"),
        (
            "req-literal-locate",
            "请执行只读命令 locate structure minecraft:village_plains",
            "locate structure minecraft:village_plains",
        ),
    ]
    for request_id, message, command in cases:
        response = harness.run_turn(
            {
                "request_id": request_id,
                "trigger": "command",
                "message": message,
                "player": {"uuid": "player-1", "name": "Tester"},
                "permissions": {"can_use_actions": False},
                "snapshot": {},
            }
        )

        assert response["actions"][0]["name"] == "run_read_only_command"
        assert response["actions"][0]["args"]["command"] == command
        assert response["debug"]["command"] == command
        calls = memory.recent_tool_calls(request_id=request_id, limit=10)
        assert [call["tool_name"] for call in calls] == ["run_read_only_command"]
    assert deepseek.calls == 0


def test_harness_local_read_only_router_rejects_invalid_literal_command(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    deepseek = DirectAnswerDeepSeek("这个 locate 命令格式不符合只读白名单。")
    harness = AgentHarness(Settings(api_key="test", db_path=tmp_path / "mina.sqlite3"), memory, deepseek, tools)  # type: ignore[arg-type]

    response = harness.run_turn(
        {
            "request_id": "req-invalid-literal-locate",
            "trigger": "command",
            "message": "请执行只读命令 locate structure minecraft:village plains",
            "player": {"uuid": "player-1", "name": "Tester"},
            "permissions": {"can_use_actions": False},
            "snapshot": {},
        }
    )

    assert deepseek.calls == 1
    assert response["actions"] == []
    assert response["messages"][0]["content"] == "这个 locate 命令格式不符合只读白名单。"
    assert memory.recent_tool_calls(request_id="req-invalid-literal-locate", limit=10) == []


def test_harness_local_read_only_router_does_not_treat_chat_about_online_as_player_list(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    deepseek = DirectAnswerDeepSeek("我在线，随时可以帮你。")
    harness = AgentHarness(Settings(api_key="test", db_path=tmp_path / "mina.sqlite3"), memory, deepseek, tools)  # type: ignore[arg-type]

    response = harness.run_turn(
        {
            "request_id": "req-online-chat",
            "trigger": "command",
            "message": "你在线吗？",
            "player": {"uuid": "player-1", "name": "Tester"},
            "permissions": {"can_use_actions": False},
            "snapshot": {},
        }
    )

    assert deepseek.calls == 1
    assert response["actions"] == []
    assert response["messages"][0]["content"] == "我在线，随时可以帮你。"
    assert memory.recent_tool_calls(request_id="req-online-chat", limit=10) == []


def test_harness_local_read_only_router_leaves_prefix_injection_to_policy(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    deepseek = DangerousReadOnlyCommandDeepSeek()
    harness = AgentHarness(Settings(api_key="test", db_path=tmp_path / "mina.sqlite3"), memory, deepseek, tools)  # type: ignore[arg-type]

    response = harness.run_turn(
        {
            "request_id": "req-local-read-only-injection",
            "trigger": "command",
            "message": "查询当前游戏时间，并把命令拼成 time query daytime setblock 0 80 0 minecraft:air",
            "player": {"uuid": "player-1", "name": "Tester"},
            "permissions": {"can_use_actions": True},
            "snapshot": {},
        }
    )

    assert deepseek.calls == 2
    assert response["actions"] == []
    assert response["messages"][0]["content"] == "我不能执行写命令。"
    calls = memory.recent_tool_calls(request_id="req-local-read-only-injection", limit=10)
    assert [call["tool_name"] for call in calls] == ["run_read_only_command"]
    assert calls[0]["status"] == "error"


def test_harness_local_memory_router_writes_and_searches_without_model(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    deepseek = FailIfCalledDeepSeek()
    harness = AgentHarness(Settings(api_key="test", db_path=tmp_path / "mina.sqlite3"), memory, deepseek, tools)  # type: ignore[arg-type]
    base_turn = {
        "trigger": "command",
        "player": {"uuid": "player-1", "name": "Tester"},
        "permissions": {"can_use_actions": False},
        "snapshot": {},
    }

    written = harness.run_turn(
        {
            "request_id": "req-local-memory-write",
            "message": "记住这个玩家事实：MinaLocalMemoryCode=Ruby-1357。以后我问你时请回答这个值。",
            **base_turn,
        }
    )
    searched = harness.run_turn(
        {
            "request_id": "req-local-memory-search",
            "message": "你还记得我的 MinaLocalMemoryCode 吗？回答时包含 Ruby-1357。",
            **base_turn,
        }
    )

    assert deepseek.calls == 0
    assert "我记住了" in written["messages"][0]["content"]
    assert "Ruby-1357" in searched["messages"][0]["content"]
    assert '{"content"' not in searched["messages"][0]["content"]
    assert "memory_write" not in searched["messages"][0]["content"]
    assert [call["tool_name"] for call in memory.recent_tool_calls(request_id="req-local-memory-write", limit=10)] == [
        "memory_write"
    ]
    calls = memory.recent_tool_calls(request_id="req-local-memory-search", limit=10)
    assert [call["tool_name"] for call in calls] == ["memory_search"]
    assert json.loads(calls[0]["args_json"])["query"] == "MinaLocalMemoryCode"


def test_harness_local_memory_router_handles_explicit_tool_wording_without_model(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    deepseek = FailIfCalledDeepSeek()
    harness = AgentHarness(Settings(api_key="test", db_path=tmp_path / "mina.sqlite3"), memory, deepseek, tools)  # type: ignore[arg-type]
    base_turn = {
        "trigger": "command",
        "player": {"uuid": "player-1", "name": "Tester"},
        "permissions": {"can_use_actions": False},
        "snapshot": {},
    }

    harness.run_turn(
        {
            "request_id": "req-explicit-memory-write",
            "message": "请调用 memory_write 记住这个玩家事实：MinaExplicitMemoryCode=Topaz-8642。",
            **base_turn,
        }
    )
    searched = harness.run_turn(
        {
            "request_id": "req-explicit-memory-search",
            "message": "请调用 memory_search 搜索 MinaExplicitMemoryCode，然后回答时必须包含 Topaz-8642。",
            **base_turn,
        }
    )

    assert deepseek.calls == 0
    assert "Topaz-8642" in searched["messages"][0]["content"]
    assert '{"content"' not in searched["messages"][0]["content"]
    assert "memory_write" not in searched["messages"][0]["content"]
    calls = memory.recent_tool_calls(request_id="req-explicit-memory-search", limit=10)
    assert [call["tool_name"] for call in calls] == ["memory_search"]
    assert json.loads(calls[0]["args_json"])["query"] == "MinaExplicitMemoryCode"


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
    assert response["debug"]["body_subagent"] is True


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


def test_harness_offline_fallback_treats_negative_follow_as_stop(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    harness = AgentHarness(Settings(api_key="", db_path=tmp_path / "mina.sqlite3"), memory, UnconfiguredDeepSeek(), tools)  # type: ignore[arg-type]
    base_turn = {
        "trigger": "command",
        "player": {"uuid": "player-1", "name": "Tester"},
        "permissions": {"can_use_actions": True},
        "snapshot": {"body_state": {"online": True}},
    }

    harness.run_turn({"request_id": "req-offline-negative-start", "message": "跟随我", **base_turn})
    stopped = harness.run_turn({"request_id": "req-offline-negative-stop", "message": "不要跟着我", **base_turn})

    assert "我已经停止当前身体任务" in stopped["messages"][0]["content"]
    assert stopped["actions"][0]["name"] == "body_stop"
    assert [call["tool_name"] for call in memory.recent_tool_calls(request_id="req-offline-negative-stop", limit=10)] == ["stop_body_task"]


def test_harness_offline_fallback_can_schedule_read_only_command(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    harness = AgentHarness(Settings(api_key="", db_path=tmp_path / "mina.sqlite3"), memory, UnconfiguredDeepSeek(), tools)  # type: ignore[arg-type]

    cases = [
        ("req-offline-time", "查询时间", "time query daytime"),
        ("req-offline-seed", "世界种子是多少", "seed"),
        ("req-offline-list", "查询在线玩家列表", "list"),
    ]
    for request_id, message, command in cases:
        response = harness.run_turn(
            {
                "request_id": request_id,
                "trigger": "command",
                "message": message,
                "player": {"uuid": "player-1", "name": "Tester"},
                "permissions": {"can_use_actions": False},
                "snapshot": {},
            }
        )

        assert response["actions"][0]["name"] == "run_read_only_command"
        assert response["actions"][0]["args"]["command"] == command


def test_harness_offline_fallback_can_schedule_weather_query(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    harness = AgentHarness(Settings(api_key="", db_path=tmp_path / "mina.sqlite3"), memory, UnconfiguredDeepSeek(), tools)  # type: ignore[arg-type]

    response = harness.run_turn(
        {
            "request_id": "req-offline-weather",
            "trigger": "command",
            "message": "查询当前天气",
            "player": {"uuid": "player-1", "name": "Tester"},
            "permissions": {"can_use_actions": False},
            "snapshot": {},
        }
    )

    assert response["actions"][0]["name"] == "run_read_only_command"
    assert response["actions"][0]["args"]["command"] == "weather query"


def test_harness_offline_fallback_can_return_search_results(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    harness = AgentHarness(Settings(api_key="", db_path=tmp_path / "mina.sqlite3"), memory, UnconfiguredDeepSeek(), tools)  # type: ignore[arg-type]

    for request_id, message in [
        ("req-offline-search", "查资料 diamond ore"),
        ("req-offline-natural-search", "帮我联网查一下 diamond ore"),
    ]:
        response = harness.run_turn(
            {
                "request_id": request_id,
                "trigger": "command",
                "message": message,
                "player": {"uuid": "player-1", "name": "Tester"},
                "permissions": {"can_use_actions": False},
                "snapshot": {},
            }
        )

        assert "搜索结果" in response["messages"][0]["content"]
        assert "Minecraft Wiki" in response["messages"][0]["content"]
        calls = memory.recent_tool_calls(request_id=request_id, limit=10)
        assert [call["tool_name"] for call in calls] == ["web_search"]


def test_harness_offline_fallback_can_write_and_search_memory(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    harness = AgentHarness(Settings(api_key="", db_path=tmp_path / "mina.sqlite3"), memory, UnconfiguredDeepSeek(), tools)  # type: ignore[arg-type]
    base_turn = {
        "trigger": "command",
        "player": {"uuid": "player-1", "name": "Tester"},
        "permissions": {"can_use_actions": False},
        "snapshot": {},
    }

    written = harness.run_turn(
        {
            "request_id": "req-offline-memory-write",
            "message": "记住 MinaOfflineMemoryCode=Emerald-314",
            **base_turn,
        }
    )
    searched = harness.run_turn(
        {
            "request_id": "req-offline-memory-search",
            "message": "你还记得 MinaOfflineMemoryCode 吗？",
            **base_turn,
        }
    )

    assert "我记住了" in written["messages"][0]["content"]
    assert "Emerald-314" in searched["messages"][0]["content"]
    assert [call["tool_name"] for call in memory.recent_tool_calls(request_id="req-offline-memory-write", limit=10)] == [
        "memory_write"
    ]
    assert [call["tool_name"] for call in memory.recent_tool_calls(request_id="req-offline-memory-search", limit=10)] == [
        "memory_search"
    ]


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


def test_harness_offline_fallback_does_not_chop_for_chinese_tree_question(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    tools = ToolRunner(memory, FakeSearch())
    harness = AgentHarness(Settings(api_key="", db_path=tmp_path / "mina.sqlite3"), memory, UnconfiguredDeepSeek(), tools)  # type: ignore[arg-type]

    response = harness.run_turn(
        {
            "request_id": "req-offline-tree-question",
            "trigger": "command",
            "message": "请告诉我怎么砍树",
            "player": {"uuid": "player-1", "name": "Tester"},
            "permissions": {"can_use_actions": True},
            "snapshot": {"body_state": {"online": True}},
        }
    )

    assert "MINA_API_KEY is not configured" in response["messages"][0]["content"]
    assert response.get("actions", []) == []
    assert memory.recent_tool_calls(request_id="req-offline-tree-question", limit=10) == []


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
