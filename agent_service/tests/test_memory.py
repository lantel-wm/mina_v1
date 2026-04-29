from __future__ import annotations

from mina_agent.memory import MemoryStore


def test_memory_search_returns_conversations_and_events(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")

    memory.add_conversation("req-1", "player-1", "user", "我喜欢云杉木基地")
    memory.add_event("player-1", "world_fact", {"content": "基地入口在河边"}, importance=3)

    results = memory.search("player-1", "基地", limit=5)

    assert any(result.get("kind") == "conversation" for result in results)
    assert any(result.get("kind") == "event" for result in results)


def test_action_tool_and_model_journals_round_trip(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")

    memory.record_tool_call("req-1", "run_read_only_command", {"command": "seed"}, {"content": "{}"}, "ok")
    memory.record_action_event("req-1", "action_scheduled", {"id": "action-1", "name": "run_read_only_command"})
    memory.record_model_call(
        request_id="req-2",
        subturn=1,
        model="deepseek-v4-flash",
        messages_count=3,
        tools=["web_search"],
        status="ok",
        finish_reason="stop",
        usage={"total_tokens": 12},
        response={"content_preview": "hi"},
    )

    assert memory.recent_tool_calls("req-1")[0]["tool_name"] == "run_read_only_command"
    assert memory.recent_action_events("req-1")[0]["action_name"] == "run_read_only_command"
    model = memory.recent_model_calls("req-2")[0]
    assert model["model"] == "deepseek-v4-flash"
    assert "web_search" in model["tools_json"]


def test_schema_no_longer_creates_body_task_tables(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    with memory._connect() as conn:  # noqa: SLF001 - schema regression test.
        names = {
            row[0]
            for row in conn.execute("select name from sqlite_master where type='table'").fetchall()
        }

    assert "task_events" not in names
    assert "skill_reflections" not in names
