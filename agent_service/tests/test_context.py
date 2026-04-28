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


def test_context_omits_recent_memory_content_for_recall_requests(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    memory.add_conversation("old-1", "player-1", "user", "记住 RecallCode=Emerald-2718")
    memory.add_event("player-1", "player_fact", {"content": "RecallCode=Emerald-2718"}, importance=4)

    messages = build_messages(
        {
            "request_id": "req-1",
            "trigger": "command",
            "message": "你还记得 RecallCode 吗？",
            "player": {"uuid": "player-1", "name": "Tester"},
            "snapshot": {},
        },
        memory,
    )
    context = "\n".join(str(message.get("content") or "") for message in messages)

    assert "memory_search" in context
    assert "Recent conversation memory is intentionally omitted" in context
    assert "Emerald-2718" not in context


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


def test_context_includes_body_identity_item_and_raycast(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")

    messages = build_messages(
        {
            "request_id": "req-1",
            "trigger": "command",
            "message": "状态",
            "player": {"uuid": "player-1", "name": "Tester"},
            "snapshot": {
                "body_state": {
                    "online": True,
                    "username": "mina",
                    "x": 1,
                    "y": 80,
                    "z": 1,
                    "yaw": 90,
                    "pitch": 10,
                    "distance_to_requester": 2.5,
                    "selected_item": {"slot": 0, "item": "minecraft:stone_axe"},
                    "targeted_block": {"x": 2, "y": 80, "z": 0, "block": "minecraft:spruce_log"},
                },
            },
        },
        memory,
    )
    context = "\n".join(str(message.get("content") or "") for message in messages)

    assert '"username": "mina"' in context
    assert "minecraft:stone_axe" in context
    assert '"targeted_block"' in context
    assert "minecraft:spruce_log" in context
