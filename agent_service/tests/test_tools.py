from __future__ import annotations

from mina_agent.memory import MemoryStore
from mina_agent.searxng import SearxngClient
from mina_agent.tools import ToolRunner


class FakeSearxng(SearxngClient):
    def __init__(self) -> None:
        pass

    def search(self, query: str, max_results: int = 5):
        return [{"title": query, "url": "https://example.com", "content": "ok"}]


def test_body_tool_requires_permission(tmp_path) -> None:
    runner = ToolRunner(MemoryStore(tmp_path / "mina.sqlite3"), FakeSearxng())

    result = runner.run("body_spawn", {}, {"permissions": {"can_use_actions": False}})

    assert "permission denied" in result.content
    assert result.action is None


def test_body_tool_schedules_action_when_allowed(tmp_path) -> None:
    runner = ToolRunner(MemoryStore(tmp_path / "mina.sqlite3"), FakeSearxng())

    result = runner.run("body_spawn", {}, {"permissions": {"can_use_actions": True}})

    assert result.action is not None
    assert result.action["name"] == "body_spawn"


def test_body_move_to_empty_args_does_not_guess_requester(tmp_path) -> None:
    runner = ToolRunner(MemoryStore(tmp_path / "mina.sqlite3"), FakeSearxng())

    result = runner.run("body_move_to", {}, {"permissions": {"can_use_actions": True}})

    assert result.action is None
    assert "requires target_type" in result.content


def test_body_move_to_explicit_requester_is_allowed(tmp_path) -> None:
    runner = ToolRunner(MemoryStore(tmp_path / "mina.sqlite3"), FakeSearxng())

    result = runner.run("body_move_to", {"target_type": "requester"}, {"permissions": {"can_use_actions": True}})

    assert result.action is not None
    assert result.action["args"]["target_type"] == "requester"


def test_body_spawn_is_skipped_when_body_already_online(tmp_path) -> None:
    runner = ToolRunner(MemoryStore(tmp_path / "mina.sqlite3"), FakeSearxng())

    result = runner.run(
        "body_spawn",
        {},
        {"permissions": {"can_use_actions": True}, "snapshot": {"body_state": {"online": True}}},
    )

    assert result.action is None
    assert "already online" in result.content


def test_run_safe_command_empty_args_are_rejected(tmp_path) -> None:
    runner = ToolRunner(MemoryStore(tmp_path / "mina.sqlite3"), FakeSearxng())

    result = runner.run("run_safe_command", {}, {"permissions": {"can_use_actions": True}})

    assert result.action is None
    assert "requires command" in result.content


def test_body_attack_empty_args_are_rejected(tmp_path) -> None:
    runner = ToolRunner(MemoryStore(tmp_path / "mina.sqlite3"), FakeSearxng())

    result = runner.run("body_attack", {}, {"permissions": {"can_use_actions": True}})

    assert result.action is None
    assert "requires mode" in result.content


def test_body_chain_requires_actions(tmp_path) -> None:
    runner = ToolRunner(MemoryStore(tmp_path / "mina.sqlite3"), FakeSearxng())

    result = runner.run("body_chain", {"clear": True, "loop": False, "restart": True}, {"permissions": {"can_use_actions": True}})

    assert result.action is None
    assert "requires actions" in result.content


def test_body_chain_accepts_block_break_sequence(tmp_path) -> None:
    runner = ToolRunner(MemoryStore(tmp_path / "mina.sqlite3"), FakeSearxng())

    result = runner.run(
        "body_chain",
        {
            "clear": True,
            "loop": False,
            "restart": True,
            "actions": [
                {"type": "move_to_position", "x": 1.5, "y": 64, "z": 2.5, "sprint": False, "jump": False},
                {"type": "look_at_position", "x": 1.5, "y": 64.5, "z": 3.5},
                {"type": "attack", "mode": "hold"},
                {"type": "delay", "seconds": 4.5},
                {"type": "attack", "mode": "release"},
            ],
        },
        {"permissions": {"can_use_actions": True}},
    )

    assert result.action is not None
    assert result.action["name"] == "body_chain"
    assert result.action["args"]["actions"][3]["seconds"] == 4.5


def test_mcp_call_is_explicitly_unavailable_without_config(tmp_path) -> None:
    runner = ToolRunner(MemoryStore(tmp_path / "mina.sqlite3"), FakeSearxng())

    result = runner.run("mcp_call", {"server": "local", "tool": "ping", "arguments": {}}, {})

    assert "not configured" in result.content
