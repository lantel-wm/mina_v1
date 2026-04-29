from __future__ import annotations

from mina_agent.context import SYSTEM_PROMPT, build_messages, build_target_summary
from mina_agent.memory import MemoryStore


def test_system_prompt_excludes_body_tools_and_allows_current_focus() -> None:
    assert "web_search" in SYSTEM_PROMPT
    assert "preserve exact source values" in SYSTEM_PROMPT
    assert "memory_search" in SYSTEM_PROMPT
    assert "run_read_only_command" in SYSTEM_PROMPT
    assert "separate Minecraft character" in SYSTEM_PROMPT
    assert "start_body_task" not in SYSTEM_PROMPT
    assert "body_chain" not in SYSTEM_PROMPT


def test_target_summary_is_observation_only(tmp_path) -> None:
    snapshot = {
        "nearby_blocks": {
            "requester": [
                {
                    "block": "minecraft:spruce_log",
                    "category": "log",
                    "x": 2,
                    "y": 80,
                    "z": 0,
                    "distance": 2.5,
                    "approach_x": 1.5,
                    "approach_y": 80,
                    "approach_z": 0.5,
                }
            ]
        }
    }

    summary = build_target_summary(snapshot)

    assert "Nearby notable blocks for observation" in summary
    assert "minecraft:spruce_log" in summary
    assert "body-control" not in summary


def test_build_messages_uses_budgeted_snapshot_without_body_state(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    turn = {
        "request_id": "req-1",
        "trigger": "command",
        "message": "附近有什么？",
        "player": {"uuid": "player-1", "name": "Tester"},
        "permissions": {"can_use_actions": True},
        "snapshot": {
            "player_state": {"x": 0.5, "y": 80, "z": -2.5, "health": 20, "food": 20},
            "nearby_entities": [{"type": "minecraft:cow", "category": "passive", "distance": 4}],
            "nearby_blocks": {"requester": [{"block": "minecraft:spruce_log", "category": "log", "x": 2, "y": 80, "z": 0}]},
        },
    }

    messages = build_messages(turn, memory)
    context = "\n".join(str(message["content"]) for message in messages)

    assert "candidate_logs" in context
    assert "nearby_hostiles" in context
    assert "body_state" not in context
    assert len(context) < 6000


def test_memory_recall_requests_force_memory_search(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    memory.add_conversation("old", "player-1", "user", "我家在云杉林旁边")
    turn = {
        "request_id": "req-1",
        "trigger": "command",
        "message": "你还记得我家在哪里吗？",
        "player": {"uuid": "player-1", "name": "Tester"},
        "snapshot": {},
    }

    messages = build_messages(turn, memory)
    content = "\n".join(message["content"] for message in messages)

    assert "must call memory_search" in content
    assert "Recent conversation memory is intentionally omitted" in content
