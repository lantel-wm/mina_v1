from __future__ import annotations

from mina_agent.memory import MemoryStore


def test_memory_search_is_scoped_to_current_player(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    memory.add_conversation("req-1", "player-1", "user", "my base is under the spruce hill")
    memory.add_conversation("req-2", "player-2", "user", "my base is under the desert temple")
    memory.add_event("player-2", "secret_note", {"content": "desert temple password"}, importance=5)

    results = memory.search("player-1", "desert temple", limit=8)

    content = "\n".join(str(result.get("content") or "") for result in results)
    assert "desert temple" not in content
    assert "password" not in content


def test_memory_search_can_return_reusable_skill_reflections(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    memory.add_skill_reflection("chop_tree", "Retry by recalculating approach if movement stalls.", {"task_id": "task-1"})

    results = memory.search("player-1", "recalculating approach", limit=8)

    assert any(result.get("kind") == "skill_reflection" for result in results)
    assert any("movement stalls" in str(result.get("content") or "") for result in results)
