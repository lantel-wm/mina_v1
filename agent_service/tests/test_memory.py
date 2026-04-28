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


def test_action_event_journal_records_non_task_actions(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    memory.record_action_event(
        "req-1",
        "action_result",
        {
            "action_id": "action-1",
            "name": "run_read_only_command",
            "command_results": [{"outputs": ["The time is 1200"]}],
        },
    )

    events = memory.recent_action_events(limit=10)

    assert events[0]["request_id"] == "req-1"
    assert events[0]["action_id"] == "action-1"
    assert events[0]["action_name"] == "run_read_only_command"
    assert "The time is 1200" in events[0]["payload_json"]


def test_tool_call_journal_can_be_filtered_by_request(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    memory.record_tool_call("req-1", "web_search", {"query": "diamond"}, {"content": "{}"}, "ok")
    memory.record_tool_call("req-2", "task_status", {}, {"content": "{}"}, "ok")

    calls = memory.recent_tool_calls(request_id="req-1", limit=10)

    assert len(calls) == 1
    assert calls[0]["request_id"] == "req-1"
    assert calls[0]["tool_name"] == "web_search"
    assert '"diamond"' in calls[0]["args_json"]
