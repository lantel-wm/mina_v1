from __future__ import annotations

from mina_agent.context import SYSTEM_PROMPT, build_messages, build_target_summary
from mina_agent.memory import MemoryStore


def test_system_prompt_excludes_body_tools_and_allows_current_focus() -> None:
    assert "web_search" in SYSTEM_PROMPT
    assert "preserve exact source values" in SYSTEM_PROMPT
    assert "memory_search" in SYSTEM_PROMPT
    assert "Agent memory" in SYSTEM_PROMPT or "agent memory" in SYSTEM_PROMPT
    assert "Do not volunteer stored player facts" in SYSTEM_PROMPT
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
    memory.add_agent_memory("player", "player-1", "base", "玩家基地在樱花林旁边", importance=4)
    memory.add_conversation("req-command", "player-1", "user", "执行 seed")
    memory.record_action_event(
        "req-command",
        "action_result",
        {
            "action_id": "action-1",
            "name": "run_read_only_command",
            "status": "completed",
            "command_success": True,
            "command_results": [{"command": "seed", "outputs": ["Seed: [98765]"]}],
        },
    )
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
    assert "Agent memory loaded for this turn" in context
    assert "玩家基地在樱花林旁边" in context
    assert "Recent verified Minecraft command/action results" in context
    assert "Seed: [98765]" in context
    assert "body_state" not in context
    assert len(context) < 6000


def test_memory_recall_requests_are_not_classified_by_context_builder(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    memory.add_conversation("old", "player-1", "user", "我家在云杉林旁边")
    memory.add_conversation("old", "player-1", "assistant", "我记得你的家在云杉林旁边")
    turn = {
        "request_id": "req-1",
        "trigger": "command",
        "message": "你还记得我家在哪里吗？",
        "player": {"uuid": "player-1", "name": "Tester"},
        "snapshot": {},
    }

    messages = build_messages(turn, memory)
    content = "\n".join(message["content"] for message in messages)

    assert "Recent player messages for continuity only" in content
    assert "我家在云杉林旁边" in content
    assert "我记得你的家" not in content
    assert "This user message is a memory recall request" not in content
    assert "Recent conversation memory is intentionally omitted" not in content


def test_companion_low_health_prompt_marks_alert_reason(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    turn = {
        "request_id": "req-companion",
        "trigger": "companion_tick",
        "message": "",
        "player": {"uuid": "player-1", "name": "Tester"},
        "snapshot": {
            "player_state": {"health": 5, "max_health": 20, "food": 20},
            "nearby_entities": [],
        },
    }

    messages = build_messages(turn, memory)
    user_message = messages[-1]["content"]

    assert "及时提醒理由" in user_message
    assert "生命值较低" in user_message
    assert "不要调用工具" in user_message
