from __future__ import annotations

from mina_agent.memory import MemoryStore
from mina_agent.searxng import SearxngClient
from mina_agent.tools import ToolRunner, tool_specs


class FakeSearxng(SearxngClient):
    def __init__(self) -> None:
        pass

    def search(self, query: str, max_results: int = 5):
        return [{"title": query, "url": "https://example.com", "content": "ok"}]


def _runner(tmp_path) -> ToolRunner:
    return ToolRunner(MemoryStore(tmp_path / "mina.sqlite3"), FakeSearxng())


def _allowed_turn() -> dict:
    return {
        "player": {"uuid": "player-1", "name": "Tester"},
        "permissions": {"can_use_actions": True},
        "snapshot": {
            "body_state": {"online": True, "x": 0.5, "y": 80, "z": -1.5},
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


def test_model_tool_specs_do_not_expose_low_level_body_tools() -> None:
    names = {spec["function"]["name"] for spec in tool_specs()}

    assert "start_body_task" in names
    assert "body_chain" not in names
    assert "run_safe_command" not in names


def test_start_body_task_requires_permission(tmp_path) -> None:
    runner = _runner(tmp_path)

    result = runner.run("start_body_task", {"task_type": "chop_tree", "target_hint": ""}, {"permissions": {"can_use_actions": False}})

    assert "permission denied" in result.content
    assert result.actions == []


def test_start_body_task_schedules_observable_move_when_body_online(tmp_path) -> None:
    runner = _runner(tmp_path)

    result = runner.run("start_body_task", {"task_type": "chop_tree", "target_hint": "nearest"}, _allowed_turn())

    assert result.actions
    action = result.actions[0]
    assert action["name"] == "body_move_to_position"
    assert action["task_id"]
    assert action["monitor"]["type"] == "body_near"
    assert action["step_id"].startswith("move:")


def test_low_level_body_tool_is_rejected(tmp_path) -> None:
    runner = _runner(tmp_path)

    result = runner.run("body_chain", {"actions": []}, _allowed_turn())

    assert result.actions == []
    assert "private executor primitive" in result.content


def test_mcp_call_is_explicitly_unavailable_without_config(tmp_path) -> None:
    runner = _runner(tmp_path)

    result = runner.run("mcp_call", {"server": "local", "tool": "ping", "arguments": {}}, {})

    assert "not configured" in result.content
