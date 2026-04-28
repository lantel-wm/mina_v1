from __future__ import annotations

from mina_agent.memory import MemoryStore
from mina_agent.mcp import McpRegistry
from mina_agent.searxng import SearxngClient
from mina_agent.tools import ToolRunner, tool_specs


class FakeSearxng(SearxngClient):
    def __init__(self) -> None:
        pass

    def search(self, query: str, max_results: int = 5):
        return [{"title": query, "url": "https://example.com", "content": "ok"}]


class FailingSearxng(SearxngClient):
    def __init__(self) -> None:
        pass

    def search(self, query: str, max_results: int = 5):
        raise OSError("offline")


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
    assert "run_read_only_command" in names
    assert "body_chain" not in names
    assert "run_safe_command" not in names


def test_stop_and_status_task_id_is_optional_for_model() -> None:
    specs = {spec["function"]["name"]: spec["function"]["parameters"] for spec in tool_specs()}

    assert specs["stop_body_task"]["required"] == []
    assert specs["task_status"]["required"] == []


def test_start_body_task_target_hint_is_optional_for_model() -> None:
    specs = {spec["function"]["name"]: spec["function"]["parameters"] for spec in tool_specs()}

    assert specs["start_body_task"]["required"] == ["task_type"]


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


def test_start_body_task_fails_gracefully_when_logs_have_no_approach(tmp_path) -> None:
    runner = _runner(tmp_path)
    turn = _allowed_turn()
    turn["snapshot"]["nearby_blocks"]["requester"][0].pop("approach_x")
    turn["snapshot"]["nearby_blocks"]["requester"][0].pop("approach_y")
    turn["snapshot"]["nearby_blocks"]["requester"][0].pop("approach_z")

    result = runner.run("start_body_task", {"task_type": "chop_tree", "target_hint": "nearest"}, turn)

    assert result.actions == []
    assert "没有找到可安全接近的原木" in result.content


def test_follow_player_schedules_observable_follow_when_body_online(tmp_path) -> None:
    runner = _runner(tmp_path)

    result = runner.run("start_body_task", {"task_type": "follow_player", "target_hint": "me"}, _allowed_turn())

    assert result.actions
    action = result.actions[0]
    assert action["name"] == "body_move_to_requester"
    assert action["monitor"]["type"] == "follow_requester"
    assert action["step_id"].startswith("follow:")


def test_start_body_task_works_without_target_hint(tmp_path) -> None:
    runner = _runner(tmp_path)

    result = runner.run("start_body_task", {"task_type": "follow_player"}, _allowed_turn())

    assert result.actions
    assert result.actions[0]["name"] == "body_move_to_requester"


def test_start_body_task_spawns_body_when_snapshot_reports_offline(tmp_path) -> None:
    runner = _runner(tmp_path)
    turn = _allowed_turn()
    turn["snapshot"]["body_state"]["online"] = False

    result = runner.run("start_body_task", {"task_type": "follow_player"}, turn)

    assert result.actions
    action = result.actions[0]
    assert action["name"] == "body_spawn"
    assert action["monitor"]["type"] == "body_online"


def test_new_body_task_stops_replaced_active_task(tmp_path) -> None:
    runner = _runner(tmp_path)
    turn = _allowed_turn()

    first = runner.run("start_body_task", {"task_type": "follow_player", "target_hint": "me"}, turn)
    second = runner.run("start_body_task", {"task_type": "chop_tree", "target_hint": "nearest"}, turn)

    assert first.actions
    assert len(second.actions) >= 2
    assert second.actions[0]["name"] == "body_stop"
    assert second.actions[0]["step_id"] == "stop:replaced"
    assert second.actions[1]["name"] == "body_move_to_position"


def test_stop_body_task_cancels_active_task(tmp_path) -> None:
    runner = _runner(tmp_path)
    turn = _allowed_turn()

    started = runner.run("start_body_task", {"task_type": "follow_player", "target_hint": "me"}, turn)
    stopped = runner.run("stop_body_task", {"task_id": ""}, turn)
    status = runner.run("task_status", {"task_id": started.actions[0]["task_id"]}, turn)

    assert stopped.actions
    assert stopped.actions[0]["name"] == "body_stop"
    assert '"status": "cancelled"' in status.content


def test_task_status_can_use_current_active_task_without_id(tmp_path) -> None:
    runner = _runner(tmp_path)
    turn = _allowed_turn()

    runner.run("start_body_task", {"task_type": "follow_player", "target_hint": "me"}, turn)
    status = runner.run("task_status", {}, turn)

    assert '"type": "follow_player"' in status.content
    assert '"status": "active"' in status.content


def test_low_level_body_tool_is_rejected(tmp_path) -> None:
    runner = _runner(tmp_path)

    result = runner.run("body_chain", {"actions": []}, _allowed_turn())

    assert result.actions == []
    assert "private executor primitive" in result.content


def test_read_only_command_schedules_fabric_action(tmp_path) -> None:
    runner = _runner(tmp_path)

    result = runner.run("run_read_only_command", {"command": "/time query daytime"}, _allowed_turn())

    assert result.action is not None
    assert result.action["name"] == "run_read_only_command"
    assert result.action["args"]["command"] == "time query daytime"


def test_write_command_is_rejected(tmp_path) -> None:
    runner = _runner(tmp_path)

    result = runner.run("run_read_only_command", {"command": "setblock 0 80 0 minecraft:air"}, _allowed_turn())

    assert result.action is None
    assert "Only read-only commands" in result.content


def test_web_search_returns_model_visible_error_when_unavailable(tmp_path) -> None:
    runner = ToolRunner(MemoryStore(tmp_path / "mina.sqlite3"), FailingSearxng())

    result = runner.run("web_search", {"query": "minecraft", "max_results": 3}, _allowed_turn())

    assert "web_search unavailable" in result.content


def test_mcp_call_is_explicitly_unavailable_without_config(tmp_path) -> None:
    runner = _runner(tmp_path)

    result = runner.run("mcp_call", {"server": "local", "tool": "ping", "arguments": {}}, {})

    assert "not configured" in result.content


def test_mcp_call_blocks_minecraft_write_operations_before_transport(tmp_path) -> None:
    config = tmp_path / "mcp.json"
    config.write_text('{"servers": {"local": {"transport": "http", "url": "http://127.0.0.1:1"}}}', encoding="utf-8")
    runner = ToolRunner(MemoryStore(tmp_path / "mina.sqlite3"), FakeSearxng(), McpRegistry(config))

    result = runner.run("mcp_call", {"server": "local", "tool": "setblock", "arguments": {"x": 0}}, {})

    assert "Minecraft write operations" in result.content
