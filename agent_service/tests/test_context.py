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
