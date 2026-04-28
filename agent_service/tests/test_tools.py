from __future__ import annotations

import json

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


class RecordingSearxng(SearxngClient):
    def __init__(self) -> None:
        pass

    def search(self, query: str, max_results: int = 5):
        self.query = query
        self.max_results = max_results
        return [{"title": "ok", "url": "https://example.com", "content": "ok"}]


class RecordingMcp:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def list_tools(self, server: str) -> dict:
        self.calls.append(("tools/list", server))
        return {"ok": True, "tools": [{"name": "echo"}]}

    def read_resource(self, server: str, uri: str) -> dict:
        self.calls.append(("resources/read", server, uri))
        return {"ok": True, "contents": [{"uri": uri, "text": "resource text"}]}

    def call(self, server: str, tool: str, arguments: dict) -> dict:
        self.calls.append(("tools/call", server, tool, arguments))
        return {"ok": True, "content": [{"type": "text", "text": str(arguments.get("text") or "")}]}


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


def _allowed_turn_for(player_id: str, name: str) -> dict:
    turn = _allowed_turn()
    turn["player"] = {"uuid": player_id, "name": name}
    return turn


def _high_unreachable_log() -> dict:
    return {
        "block": "minecraft:oak_log",
        "category": "log",
        "x": 1,
        "y": 86,
        "z": 0,
        "center_x": 1.5,
        "center_y": 86.5,
        "center_z": 0.5,
        "distance": 1.0,
        "approach_x": 1.5,
        "approach_y": 86,
        "approach_z": -0.5,
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


def test_start_body_task_rejects_unsupported_task_type(tmp_path) -> None:
    runner = _runner(tmp_path)

    result = runner.run("start_body_task", {"task_type": "mine_diamond"}, _allowed_turn())

    assert result.actions == []
    assert '"ok": false' in result.content
    assert "unsupported body task" in result.content


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
    assert '"ok": false' in result.content
    assert '"error": "no log target with approach position"' in result.content
    assert "没有找到可安全接近的原木" in result.content
    assert '"task not found"' in runner.run("task_status", {}, turn).content


def test_chop_tree_ignores_vertically_unreachable_log_candidates(tmp_path) -> None:
    runner = _runner(tmp_path)
    turn = _allowed_turn()
    turn["snapshot"]["nearby_blocks"]["body"] = [_high_unreachable_log()]

    result = runner.run("start_body_task", {"task_type": "chop_tree", "target_hint": "nearest"}, turn)

    assert result.actions
    assert result.actions[0]["name"] == "body_move_to_position"
    assert result.actions[0]["args"]["x"] == 2.5
    assert result.actions[0]["args"]["y"] == 80.0
    status = runner.run("task_status", {"task_id": result.actions[0]["task_id"]}, turn)
    assert '"block": "minecraft:spruce_log"' in status.content
    assert '"y": 80' in status.content


def test_completed_task_is_not_current_but_remains_queryable_by_id(tmp_path) -> None:
    runner = _runner(tmp_path)
    turn = _allowed_turn()

    started = runner.run("start_body_task", {"task_type": "chop_tree", "target_hint": "nearest"}, turn)
    move = started.actions[0]
    task_id = move["task_id"]
    moved = runner.skills.handle_action_results(
        {
            "action_results": [
                {
                    "task_id": task_id,
                    "step_id": move["step_id"],
                    "name": move["name"],
                    "status": "success",
                    "command_success": True,
                    "monitor_result": {"status": "success", "reason": "body reached target"},
                    "snapshot": turn["snapshot"],
                }
            ]
        }
    )
    look = moved.actions[0]
    assert look["name"] == "body_look_at_position"
    assert look["monitor"]["type"] == "body_targeted_block"
    looked = runner.skills.handle_action_results(
        {
            "action_results": [
                {
                    "task_id": task_id,
                    "step_id": look["step_id"],
                    "name": look["name"],
                    "status": "success",
                    "command_success": True,
                    "monitor_result": {"status": "success", "reason": "body targeted expected block"},
                    "snapshot": turn["snapshot"],
                }
            ]
        }
    )
    attack = looked.actions[0]
    assert attack["name"] == "body_chain"
    runner.skills.handle_action_results(
        {
            "action_results": [
                {
                    "task_id": task_id,
                    "step_id": attack["step_id"],
                    "name": attack["name"],
                    "status": "success",
                    "command_success": True,
                    "monitor_result": {"status": "success", "reason": "target block is absent"},
                    "snapshot": turn["snapshot"],
                }
            ]
        }
    )

    assert '"task not found"' in runner.run("task_status", {}, turn).content
    assert '"status": "completed"' in runner.run("task_status", {"task_id": task_id}, turn).content
    stopped = runner.run("stop_body_task", {"task_id": task_id}, turn)
    assert stopped.actions == []
    assert '"ok": false' in stopped.content
    assert "当前没有正在执行的身体任务" in stopped.content


def test_chop_tree_continues_to_stacked_upper_log_after_first_block(tmp_path) -> None:
    runner = _runner(tmp_path)
    turn = _allowed_turn()

    started = runner.run("start_body_task", {"task_type": "chop_tree", "target_hint": "nearest"}, turn)
    move = started.actions[0]
    task_id = move["task_id"]
    moved = runner.skills.handle_action_results(
        {
            "action_results": [
                {
                    "action_id": move["id"],
                    "task_id": task_id,
                    "step_id": move["step_id"],
                    "name": move["name"],
                    "status": "success",
                    "command_success": True,
                    "monitor_result": {"status": "success", "reason": "body reached target"},
                    "snapshot": turn["snapshot"],
                }
            ]
        }
    )
    look = moved.actions[0]
    looked = runner.skills.handle_action_results(
        {
            "action_results": [
                {
                    "action_id": look["id"],
                    "task_id": task_id,
                    "step_id": look["step_id"],
                    "name": look["name"],
                    "status": "success",
                    "command_success": True,
                    "monitor_result": {"status": "success", "reason": "body targeted expected block"},
                    "snapshot": turn["snapshot"],
                }
            ]
        }
    )
    first_attack = looked.actions[0]
    upper_log = {
        "block": "minecraft:spruce_log",
        "category": "log",
        "x": 2,
        "y": 81,
        "z": 0,
        "center_x": 2.5,
        "center_y": 81.5,
        "center_z": 0.5,
        "distance": 3.2,
    }
    continued = runner.skills.handle_action_results(
        {
            "action_results": [
                {
                    "action_id": first_attack["id"],
                    "task_id": task_id,
                    "step_id": first_attack["step_id"],
                    "name": first_attack["name"],
                    "status": "success",
                    "command_success": True,
                    "monitor_result": {"status": "success", "reason": "target block is absent"},
                    "snapshot": {"body_state": {"online": True}, "nearby_blocks": {"body": [upper_log]}},
                }
            ]
        }
    )

    assert continued.messages == []
    assert continued.actions
    upper_look = continued.actions[0]
    assert upper_look["name"] == "body_look_at_position"
    assert upper_look["step_id"] == "look:1.0"
    assert upper_look["monitor"]["y"] == 81
    status = runner.run("task_status", {"task_id": task_id}, turn)
    assert '"target_ordinal": 1' in status.content
    assert '"y": 81' in status.content

    upper_looked = runner.skills.handle_action_results(
        {
            "action_results": [
                {
                    "action_id": upper_look["id"],
                    "task_id": task_id,
                    "step_id": upper_look["step_id"],
                    "name": upper_look["name"],
                    "status": "success",
                    "command_success": True,
                    "monitor_result": {"status": "success", "reason": "body targeted expected block"},
                    "snapshot": {"body_state": {"online": True}, "nearby_blocks": {"body": [upper_log]}},
                }
            ]
        }
    )
    upper_attack = upper_looked.actions[0]
    completed = runner.skills.handle_action_results(
        {
            "action_results": [
                {
                    "action_id": upper_attack["id"],
                    "task_id": task_id,
                    "step_id": upper_attack["step_id"],
                    "name": upper_attack["name"],
                    "status": "success",
                    "command_success": True,
                    "monitor_result": {"status": "success", "reason": "target block is absent"},
                    "snapshot": {"body_state": {"online": True}, "nearby_blocks": {"body": []}},
                }
            ]
        }
    )

    assert completed.actions == []
    assert completed.messages[0]["content"] == "砍树完成。"
    assert '"task not found"' in runner.run("task_status", {}, turn).content
    assert '"status": "completed"' in runner.run("task_status", {"task_id": task_id}, turn).content


def test_stale_action_result_does_not_advance_active_task(tmp_path) -> None:
    runner = _runner(tmp_path)
    turn = _allowed_turn()

    started = runner.run("start_body_task", {"task_type": "chop_tree", "target_hint": "nearest"}, turn)
    move = started.actions[0]
    moved = runner.skills.handle_action_results(
        {
            "action_results": [
                {
                    "action_id": move["id"],
                    "task_id": move["task_id"],
                    "step_id": move["step_id"],
                    "name": move["name"],
                    "status": "success",
                    "command_success": True,
                    "monitor_result": {"status": "success", "reason": "body reached target"},
                    "snapshot": turn["snapshot"],
                }
            ]
        }
    )
    assert moved.actions

    stale = runner.skills.handle_action_results(
        {
            "action_results": [
                {
                    "action_id": move["id"],
                    "task_id": move["task_id"],
                    "step_id": move["step_id"],
                    "name": move["name"],
                    "status": "success",
                    "command_success": True,
                    "monitor_result": {"status": "success", "reason": "duplicate old move result"},
                    "snapshot": turn["snapshot"],
                }
            ]
        }
    )

    assert stale.actions == []
    status = runner.run("task_status", {"task_id": move["task_id"]}, turn)
    assert '"stage": "look_sent"' in status.content


def test_stale_step_result_without_action_id_does_not_advance_active_task(tmp_path) -> None:
    runner = _runner(tmp_path)
    turn = _allowed_turn()

    started = runner.run("start_body_task", {"task_type": "chop_tree", "target_hint": "nearest"}, turn)
    move = started.actions[0]
    moved = runner.skills.handle_action_results(
        {
            "action_results": [
                {
                    "action_id": move["id"],
                    "task_id": move["task_id"],
                    "step_id": move["step_id"],
                    "name": move["name"],
                    "status": "success",
                    "command_success": True,
                    "monitor_result": {"status": "success", "reason": "body reached target"},
                    "snapshot": turn["snapshot"],
                }
            ]
        }
    )
    assert moved.actions

    stale = runner.skills.handle_action_results(
        {
            "action_results": [
                {
                    "task_id": move["task_id"],
                    "step_id": move["step_id"],
                    "name": move["name"],
                    "status": "success",
                    "command_success": True,
                    "monitor_result": {"status": "success", "reason": "duplicate old move result"},
                    "snapshot": turn["snapshot"],
                }
            ]
        }
    )

    assert stale.actions == []
    status = runner.run("task_status", {"task_id": move["task_id"]}, turn)
    assert '"stage": "look_sent"' in status.content
    assert '"active_step_id": "look:0"' in status.content


def test_chop_tree_reselects_when_target_disappears_before_attack(tmp_path) -> None:
    runner = _runner(tmp_path)
    turn = _allowed_turn()

    started = runner.run("start_body_task", {"task_type": "chop_tree", "target_hint": "nearest"}, turn)
    move = started.actions[0]
    replacement = {
        "block": "minecraft:spruce_log",
        "category": "log",
        "x": 4,
        "y": 80,
        "z": 0,
        "center_x": 4.5,
        "center_y": 80.5,
        "center_z": 0.5,
        "distance": 3.0,
        "approach_x": 4.5,
        "approach_y": 80,
        "approach_z": -0.5,
    }
    advanced = runner.skills.handle_action_results(
        {
            "action_results": [
                {
                    "action_id": move["id"],
                    "task_id": move["task_id"],
                    "step_id": move["step_id"],
                    "name": move["name"],
                    "status": "success",
                    "command_success": True,
                    "monitor_result": {"status": "success", "reason": "body reached target"},
                    "snapshot": {"body_state": {"online": True}, "nearby_blocks": {"body": [replacement]}},
                }
            ]
        }
    )

    assert advanced.actions
    assert advanced.actions[0]["name"] == "body_move_to_position"
    assert advanced.actions[0]["step_id"] == "move:1"
    assert advanced.actions[0]["args"]["x"] == 4.5
    status = runner.run("task_status", {"task_id": move["task_id"]}, turn)
    assert '"last_error": "target disappeared before attack"' in status.content
    assert '"x": 4' in status.content


def test_chop_tree_reselects_same_column_log_without_new_approach(tmp_path) -> None:
    runner = _runner(tmp_path)
    turn = _allowed_turn()

    started = runner.run("start_body_task", {"task_type": "chop_tree", "target_hint": "nearest"}, turn)
    move = started.actions[0]
    replacement = {
        "block": "minecraft:spruce_log",
        "category": "log",
        "x": 2,
        "y": 81,
        "z": 0,
        "center_x": 2.5,
        "center_y": 81.5,
        "center_z": 0.5,
        "distance": 3.2,
    }
    advanced = runner.skills.handle_action_results(
        {
            "action_results": [
                {
                    "action_id": move["id"],
                    "task_id": move["task_id"],
                    "step_id": move["step_id"],
                    "name": move["name"],
                    "status": "success",
                    "command_success": True,
                    "monitor_result": {"status": "success", "reason": "body reached target"},
                    "snapshot": {"body_state": {"online": True}, "nearby_blocks": {"body": [replacement]}},
                }
            ]
        }
    )

    assert advanced.actions
    assert advanced.actions[0]["name"] == "body_move_to_position"
    assert advanced.actions[0]["step_id"] == "move:1"
    assert advanced.actions[0]["args"]["x"] == 2.5
    assert advanced.actions[0]["args"]["z"] == -0.5
    status = runner.run("task_status", {"task_id": move["task_id"]}, turn)
    assert '"last_error": "target disappeared before attack"' in status.content
    assert '"y": 81' in status.content


def test_chop_tree_prefers_same_column_replacement_over_unreachable_log(tmp_path) -> None:
    runner = _runner(tmp_path)
    turn = _allowed_turn()

    started = runner.run("start_body_task", {"task_type": "chop_tree", "target_hint": "nearest"}, turn)
    move = started.actions[0]
    upper_log = {
        "block": "minecraft:spruce_log",
        "category": "log",
        "x": 2,
        "y": 81,
        "z": 0,
        "center_x": 2.5,
        "center_y": 81.5,
        "center_z": 0.5,
        "distance": 3.2,
    }

    advanced = runner.skills.handle_action_results(
        {
            "action_results": [
                {
                    "action_id": move["id"],
                    "task_id": move["task_id"],
                    "step_id": move["step_id"],
                    "name": move["name"],
                    "status": "success",
                    "command_success": True,
                    "monitor_result": {"status": "success", "reason": "body reached target"},
                    "snapshot": {
                        "body_state": {"online": True, "y": 80},
                        "nearby_blocks": {"body": [_high_unreachable_log(), upper_log]},
                    },
                }
            ]
        }
    )

    assert advanced.actions
    assert advanced.actions[0]["name"] == "body_move_to_position"
    assert advanced.actions[0]["args"]["x"] == 2.5
    status = runner.run("task_status", {"task_id": move["task_id"]}, turn)
    assert '"block": "minecraft:spruce_log"' in status.content
    assert '"y": 81' in status.content


def test_chop_tree_reselects_when_target_disappears_after_look_sent(tmp_path) -> None:
    runner = _runner(tmp_path)
    turn = _allowed_turn()

    started = runner.run("start_body_task", {"task_type": "chop_tree", "target_hint": "nearest"}, turn)
    move = started.actions[0]
    moved = runner.skills.handle_action_results(
        {
            "action_results": [
                {
                    "action_id": move["id"],
                    "task_id": move["task_id"],
                    "step_id": move["step_id"],
                    "name": move["name"],
                    "status": "success",
                    "command_success": True,
                    "monitor_result": {"status": "success", "reason": "body reached target"},
                    "snapshot": turn["snapshot"],
                }
            ]
        }
    )
    look = moved.actions[0]
    replacement = {
        "block": "minecraft:spruce_log",
        "category": "log",
        "x": 2,
        "y": 81,
        "z": 0,
        "center_x": 2.5,
        "center_y": 81.5,
        "center_z": 0.5,
        "distance": 3.2,
    }

    advanced = runner.skills.handle_action_results(
        {
            "action_results": [
                {
                    "action_id": look["id"],
                    "task_id": look["task_id"],
                    "step_id": look["step_id"],
                    "name": look["name"],
                    "status": "timeout",
                    "command_success": True,
                    "monitor_result": {"status": "timeout", "reason": "monitor deadline reached"},
                    "snapshot": {"body_state": {"online": True}, "nearby_blocks": {"body": [replacement]}},
                }
            ]
        }
    )

    assert advanced.actions
    assert advanced.actions[0]["name"] == "body_move_to_position"
    assert advanced.actions[0]["step_id"] == "move:1"
    assert advanced.actions[0]["args"]["x"] == 2.5
    status = runner.run("task_status", {"task_id": move["task_id"]}, turn)
    assert '"last_error": "target disappeared before attack"' in status.content
    assert '"active_step_id": "move:1"' in status.content
    assert '"y": 81' in status.content


def test_chop_tree_completes_when_target_disappears_and_no_replacement_exists(tmp_path) -> None:
    runner = _runner(tmp_path)
    turn = _allowed_turn()

    started = runner.run("start_body_task", {"task_type": "chop_tree", "target_hint": "nearest"}, turn)
    move = started.actions[0]
    advanced = runner.skills.handle_action_results(
        {
            "action_results": [
                {
                    "action_id": move["id"],
                    "task_id": move["task_id"],
                    "step_id": move["step_id"],
                    "name": move["name"],
                    "status": "success",
                    "command_success": True,
                    "monitor_result": {"status": "success", "reason": "body reached target"},
                    "snapshot": {"body_state": {"online": True}, "nearby_blocks": {"body": []}},
                }
            ]
        }
    )

    assert advanced.actions == []
    assert "目标原木已经不存在" in advanced.messages[0]["content"]
    status = runner.run("task_status", {"task_id": move["task_id"]}, turn)
    assert '"status": "completed"' in status.content
    assert '"last_error": "target disappeared before attack"' in status.content


def test_chop_tree_recovery_ignores_unreachable_high_replacement_log(tmp_path) -> None:
    runner = _runner(tmp_path)
    turn = _allowed_turn()

    started = runner.run("start_body_task", {"task_type": "chop_tree", "target_hint": "nearest"}, turn)
    move = started.actions[0]
    advanced = runner.skills.handle_action_results(
        {
            "action_results": [
                {
                    "action_id": move["id"],
                    "task_id": move["task_id"],
                    "step_id": move["step_id"],
                    "name": move["name"],
                    "status": "success",
                    "command_success": True,
                    "monitor_result": {"status": "success", "reason": "body reached target"},
                    "snapshot": {
                        "body_state": {"online": True, "y": 80},
                        "nearby_blocks": {"body": [_high_unreachable_log()]},
                    },
                }
            ]
        }
    )

    assert advanced.actions == []
    assert "目标原木已经不存在" in advanced.messages[0]["content"]
    status = runner.run("task_status", {"task_id": move["task_id"]}, turn)
    assert '"status": "completed"' in status.content
    assert '"block": "minecraft:oak_log"' not in status.content


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


def test_unknown_observation_task_id_does_not_advance_active_task(tmp_path) -> None:
    runner = _runner(tmp_path)
    turn = _allowed_turn()
    turn["snapshot"]["body_state"]["online"] = False

    result = runner.run("start_body_task", {"task_type": "follow_player"}, turn)
    task_id = result.actions[0]["task_id"]
    advanced = runner.skills.handle_observation(
        {
            "task_id": "missing-task",
            "snapshot": {"body_state": {"online": True}},
        }
    )
    status = runner.run("task_status", {"task_id": task_id}, turn)

    assert advanced.actions == []
    assert '"stage": "spawn_sent"' in status.content
    assert '"active_action_id": "' + result.actions[0]["id"] + '"' in status.content


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


def test_new_body_task_stops_other_players_active_body_task(tmp_path) -> None:
    runner = _runner(tmp_path)
    first_turn = _allowed_turn_for("player-1", "TesterOne")
    second_turn = _allowed_turn_for("player-2", "TesterTwo")

    first = runner.run("start_body_task", {"task_type": "follow_player", "target_hint": "me"}, first_turn)
    second = runner.run("start_body_task", {"task_type": "chop_tree", "target_hint": "nearest"}, second_turn)
    first_task_id = first.actions[0]["task_id"]

    assert first.actions
    assert len(second.actions) >= 2
    assert second.actions[0]["name"] == "body_stop"
    assert second.actions[0]["task_id"] == first_task_id
    assert second.actions[0]["step_id"] == "stop:replaced"
    assert second.actions[1]["name"] == "body_move_to_position"
    assert '"status": "cancelled"' in runner.run("task_status", {"task_id": first_task_id}, first_turn).content
    assert '"type": "chop_tree"' in runner.run("task_status", {}, first_turn).content
    active = [task for task in runner.skills.list_tasks() if task["status"] == "active"]
    assert [task["type"] for task in active] == ["chop_tree"]


def test_stop_body_task_cancels_active_task(tmp_path) -> None:
    runner = _runner(tmp_path)
    turn = _allowed_turn()

    started = runner.run("start_body_task", {"task_type": "follow_player", "target_hint": "me"}, turn)
    stopped = runner.run("stop_body_task", {"task_id": ""}, turn)
    status = runner.run("task_status", {"task_id": started.actions[0]["task_id"]}, turn)

    assert stopped.actions
    assert stopped.actions[0]["name"] == "body_stop"
    assert '"status": "cancelled"' in status.content


def test_stop_body_task_requires_permission(tmp_path) -> None:
    runner = _runner(tmp_path)
    allowed_turn = _allowed_turn()
    denied_turn = _allowed_turn()
    denied_turn["permissions"] = {"can_use_actions": False}

    started = runner.run("start_body_task", {"task_type": "follow_player", "target_hint": "me"}, allowed_turn)
    stopped = runner.run("stop_body_task", {}, denied_turn)
    status = runner.run("task_status", {"task_id": started.actions[0]["task_id"]}, allowed_turn)

    assert stopped.actions == []
    assert '"ok": false' in stopped.content
    assert "permission denied" in stopped.content
    assert '"status": "active"' in status.content


def test_stop_body_task_reports_error_when_no_task_is_active(tmp_path) -> None:
    runner = _runner(tmp_path)

    stopped = runner.run("stop_body_task", {}, _allowed_turn())

    assert stopped.actions == []
    assert '"ok": false' in stopped.content
    assert '"error": "no active body task"' in stopped.content
    assert "当前没有正在执行的身体任务" in stopped.content


def test_body_unavailable_failure_does_not_retry_repeatedly(tmp_path) -> None:
    runner = _runner(tmp_path)
    turn = _allowed_turn()

    started = runner.run("start_body_task", {"task_type": "follow_player", "target_hint": "me"}, turn)
    action = started.actions[0]
    response = runner.skills.handle_action_results(
        {
            "action_results": [
                {
                    "action_id": action["id"],
                    "task_id": action["task_id"],
                    "step_id": action["step_id"],
                    "name": action["name"],
                    "status": "failed",
                    "command_success": False,
                    "error": "Mina body is unavailable because PuppetPlayers is not installed or body use is disabled.",
                    "snapshot": turn["snapshot"],
                }
            ]
        }
    )

    assert response.actions == []
    assert "身体执行不可用" in response.messages[0]["content"]
    status = runner.run("task_status", {"task_id": action["task_id"]}, turn)
    assert '"status": "failed"' in status.content
    assert '"attempts": 1' in status.content


def test_task_status_can_use_current_active_task_without_id(tmp_path) -> None:
    runner = _runner(tmp_path)
    turn = _allowed_turn()

    runner.run("start_body_task", {"task_type": "follow_player", "target_hint": "me"}, turn)
    status = runner.run("task_status", {}, turn)

    assert '"type": "follow_player"' in status.content
    assert '"status": "active"' in status.content


def test_task_status_reports_global_body_task_to_other_player(tmp_path) -> None:
    runner = _runner(tmp_path)

    runner.run("start_body_task", {"task_type": "follow_player", "target_hint": "me"}, _allowed_turn_for("player-1", "TesterOne"))
    status = runner.run("task_status", {}, _allowed_turn_for("player-2", "TesterTwo"))

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


def test_read_only_command_allows_precise_safe_forms(tmp_path) -> None:
    runner = _runner(tmp_path)

    for command in (
        "seed",
        "time query gametime",
        "weather query",
        "list uuids",
        "locate structure minecraft:village_plains",
        "locate structure #minecraft:village",
    ):
        result = runner.run("run_read_only_command", {"command": command}, _allowed_turn())

        assert result.action is not None, command
        assert result.action["args"]["command"] == command


def test_read_only_command_rejects_extra_tokens_after_allowed_form(tmp_path) -> None:
    runner = _runner(tmp_path)

    for command in (
        "time query daytime setblock 0 80 0 minecraft:air",
        "weather query clear",
        "list @a",
        "locate structure minecraft:village_plains setblock 0 80 0 minecraft:air",
        "locate structure minecraft:village plains",
    ):
        result = runner.run("run_read_only_command", {"command": command}, _allowed_turn())

        assert result.action is None, command
        assert "Only read-only commands" in result.content


def test_write_command_is_rejected(tmp_path) -> None:
    runner = _runner(tmp_path)

    result = runner.run("run_read_only_command", {"command": "setblock 0 80 0 minecraft:air"}, _allowed_turn())

    assert result.action is None
    assert "Only read-only commands" in result.content


def test_web_search_returns_model_visible_error_when_unavailable(tmp_path) -> None:
    runner = ToolRunner(MemoryStore(tmp_path / "mina.sqlite3"), FailingSearxng())

    result = runner.run("web_search", {"query": "minecraft", "max_results": 3}, _allowed_turn())

    assert "web_search unavailable" in result.content


def test_web_search_rejects_empty_query(tmp_path) -> None:
    runner = _runner(tmp_path)

    result = runner.run("web_search", {"query": "   ", "max_results": 3}, _allowed_turn())

    assert '"ok": false' in result.content
    assert "query is required" in result.content


def test_web_search_tolerates_invalid_max_results(tmp_path) -> None:
    searxng = RecordingSearxng()
    runner = ToolRunner(MemoryStore(tmp_path / "mina.sqlite3"), searxng)

    result = runner.run("web_search", {"query": "minecraft", "max_results": "many"}, _allowed_turn())

    assert '"ok": true' in result.content
    assert searxng.max_results == 5


def test_memory_tools_tolerate_invalid_numeric_args(tmp_path) -> None:
    runner = _runner(tmp_path)
    turn = _allowed_turn()

    written = runner.run("memory_write", {"event_type": "note", "content": "base near spawn", "importance": "high"}, turn)
    searched = runner.run("memory_search", {"query": "base", "limit": "many"}, turn)

    assert '"ok": true' in written.content
    assert "base near spawn" in searched.content


def test_memory_tools_reject_empty_required_text(tmp_path) -> None:
    runner = _runner(tmp_path)
    turn = _allowed_turn()

    written = runner.run("memory_write", {"event_type": "note", "content": "   "}, turn)
    searched = runner.run("memory_search", {"query": "   "}, turn)

    assert '"ok": false' in written.content
    assert "content is required" in written.content
    assert '"ok": false' in searched.content
    assert "query is required" in searched.content
    assert runner.memory.search("player-1", "note", limit=5) == []


def test_mcp_call_is_explicitly_unavailable_without_config(tmp_path) -> None:
    runner = _runner(tmp_path)

    result = runner.run("mcp_call", {"server": "local", "tool": "ping", "arguments": {}}, {})

    assert "not configured" in result.content


def test_mcp_call_can_list_tools_read_resources_and_call_tools(tmp_path) -> None:
    mcp = RecordingMcp()
    runner = ToolRunner(MemoryStore(tmp_path / "mina.sqlite3"), FakeSearxng(), mcp)  # type: ignore[arg-type]

    tools = runner.run("mcp_call", {"server": "docs", "tool": "tools/list", "arguments": {}}, {})
    resource = runner.run("mcp_call", {"server": "docs", "tool": "resources/read", "arguments": {"uri": "file:///note"}}, {})
    called = runner.run("mcp_call", {"server": "docs", "tool": "echo", "arguments": {"text": "hello"}}, {})

    assert json.loads(tools.content)["tools"][0]["name"] == "echo"
    assert json.loads(resource.content)["contents"][0]["text"] == "resource text"
    assert json.loads(called.content)["content"][0]["text"] == "hello"
    assert mcp.calls == [
        ("tools/list", "docs"),
        ("resources/read", "docs", "file:///note"),
        ("tools/call", "docs", "echo", {"text": "hello"}),
    ]


def test_mcp_resource_read_requires_uri(tmp_path) -> None:
    runner = ToolRunner(MemoryStore(tmp_path / "mina.sqlite3"), FakeSearxng(), RecordingMcp())  # type: ignore[arg-type]

    result = runner.run("mcp_call", {"server": "docs", "tool": "resources/read", "arguments": {}}, {})

    assert json.loads(result.content)["ok"] is False
    assert "arguments.uri" in result.content


def test_mcp_call_blocks_minecraft_write_operations_before_transport(tmp_path) -> None:
    config = tmp_path / "mcp.json"
    config.write_text('{"servers": {"local": {"transport": "http", "url": "http://127.0.0.1:1"}}}', encoding="utf-8")
    runner = ToolRunner(MemoryStore(tmp_path / "mina.sqlite3"), FakeSearxng(), McpRegistry(config))

    result = runner.run("mcp_call", {"server": "local", "tool": "setblock", "arguments": {"x": 0}}, {})

    assert "Minecraft write operations" in result.content


def test_mcp_call_blocks_short_and_namespaced_minecraft_write_commands(tmp_path) -> None:
    config = tmp_path / "mcp.json"
    config.write_text('{"servers": {"local": {"transport": "http", "url": "http://127.0.0.1:1"}}}', encoding="utf-8")
    runner = ToolRunner(MemoryStore(tmp_path / "mina.sqlite3"), FakeSearxng(), McpRegistry(config))

    exact = runner.run("mcp_call", {"server": "local", "tool": "tp", "arguments": {"target": "mina"}}, {})
    namespaced = runner.run("mcp_call", {"server": "local", "tool": "minecraft:fill", "arguments": {}}, {})
    embedded = runner.run("mcp_call", {"server": "local", "tool": "admin", "arguments": {"command": "kill @e[type=item]"}}, {})

    assert "Minecraft write operations" in exact.content
    assert "Minecraft write operations" in namespaced.content
    assert "Minecraft write operations" in embedded.content


def test_mcp_call_blocks_broad_minecraft_mutation_commands(tmp_path) -> None:
    config = tmp_path / "mcp.json"
    config.write_text('{"servers": {"local": {"transport": "http", "url": "http://127.0.0.1:1"}}}', encoding="utf-8")
    runner = ToolRunner(MemoryStore(tmp_path / "mina.sqlite3"), FakeSearxng(), McpRegistry(config))

    execute = runner.run("mcp_call", {"server": "local", "tool": "execute", "arguments": {"run": "time set day"}}, {})
    gamerule = runner.run("mcp_call", {"server": "local", "tool": "admin", "arguments": {"command": "/gamerule doDaylightCycle false"}}, {})
    effect = runner.run("mcp_call", {"server": "local", "tool": "minecraft:effect", "arguments": {"target": "mina"}}, {})
    scoreboard = runner.run("mcp_call", {"server": "local", "tool": "scoreboard", "arguments": {"objective": "test"}}, {})

    assert "Minecraft write operations" in execute.content
    assert "Minecraft write operations" in gamerule.content
    assert "Minecraft write operations" in effect.content
    assert "Minecraft write operations" in scoreboard.content
