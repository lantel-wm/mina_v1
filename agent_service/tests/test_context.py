from __future__ import annotations

from mina_agent.context import build_messages
from mina_agent.memory import MemoryStore


def test_context_includes_relevant_player_memory(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    memory.add_event("player-1", "base_note", {"content": "main base is near spawn under spruce hill"}, importance=4)
    memory.add_event("player-2", "base_note", {"content": "secret desert base"}, importance=4)

    messages = build_messages(
        {
            "request_id": "req-1",
            "trigger": "command",
            "message": "where is my base near spawn",
            "player": {"uuid": "player-1", "name": "Tester"},
            "snapshot": {},
        },
        memory,
    )
    context = "\n".join(str(message.get("content") or "") for message in messages)

    assert "Relevant memory and skill reflections" in context
    assert "main base is near spawn" in context
    assert "secret desert base" not in context


def test_context_includes_skill_reflection_for_chinese_body_intent(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    memory.add_skill_reflection("chop_tree", "When chopping, move to the approach point before attacking.", {"task_id": "task-1"})

    messages = build_messages(
        {
            "request_id": "req-1",
            "trigger": "command",
            "message": "帮我砍树",
            "player": {"uuid": "player-1", "name": "Tester"},
            "snapshot": {},
        },
        memory,
    )
    context = "\n".join(str(message.get("content") or "") for message in messages)

    assert "skill_reflection/chop_tree" in context
    assert "move to the approach point" in context


def test_target_summary_keeps_model_on_high_level_body_tasks(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")

    messages = build_messages(
        {
            "request_id": "req-1",
            "trigger": "command",
            "message": "砍树",
            "player": {"uuid": "player-1", "name": "Tester"},
            "snapshot": {
                "body_state": {
                    "online": True,
                    "x": 1,
                    "y": 80,
                    "z": 1,
                    "yaw": 90,
                    "pitch": 10,
                    "inventory": [{"slot": 0, "item": "minecraft:stone_axe"}],
                },
                "nearby_blocks": [
                    {
                        "block": "minecraft:oak_log",
                        "category": "log",
                        "x": 2,
                        "y": 80,
                        "z": 2,
                        "center_x": 2.5,
                        "center_y": 80.5,
                        "center_z": 2.5,
                        "distance": 3.0,
                        "approach_x": 1.5,
                        "approach_y": 80,
                        "approach_z": 2.5,
                    }
                ],
            },
        },
        memory,
    )
    context = "\n".join(str(message.get("content") or "") for message in messages)

    assert "Use start_body_task" in context
    assert "approach_available=True" in context
    assert "move_to_position" not in context
    assert "look_at_position" not in context
    assert "inventory" not in context
