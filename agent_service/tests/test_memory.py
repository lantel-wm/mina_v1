from __future__ import annotations

from mina_agent.memory import MemoryStore


def test_memory_search_returns_agent_memories_only(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")

    memory.add_conversation("req-1", "player-1", "user", "我喜欢云杉木基地")
    memory.add_event("player-1", "world_fact", {"content": "基地入口在河边"}, importance=3)
    memory.add_agent_memory("player", "player-1", "base", "基地在樱花林旁边", importance=4)

    results = memory.search("player-1", "基地", limit=5)

    assert any(result.get("kind") == "agent_memory" for result in results)
    assert all(result.get("kind") == "agent_memory" for result in results)
    assert not any("云杉木" in result.get("content", "") for result in results)
    assert not any("河边" in result.get("content", "") for result in results)


def test_agent_context_loads_scoped_memory_by_importance(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    memory.add_agent_memory("global", "*", "style", "回答要简洁", importance=2)
    memory.add_agent_memory("world", "minecraft:overworld", "world", "村庄在出生点东侧", importance=3)
    memory.add_agent_memory("player", "player-1", "base", "玩家基地在樱花林旁边", importance=5)
    memory.add_agent_memory("player", "other-player", "base", "其他玩家基地在沙漠", importance=5)

    loaded = memory.agent_context("player-1", world_id="minecraft:overworld", limit=10)
    rendered = "\n".join(item["content"] for item in loaded)

    assert "玩家基地在樱花林旁边" in rendered
    assert "村庄在出生点东侧" in rendered
    assert "回答要简洁" in rendered
    assert "其他玩家基地" not in rendered
    assert loaded[0]["label"] == "base"


def test_action_tool_and_model_journals_round_trip(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")

    memory.add_conversation("req-1", "player-1", "user", "查询种子")
    memory.record_tool_call("req-1", "run_read_only_command", {"command": "seed"}, {"content": "{}"}, "ok")
    memory.record_action_event("req-1", "action_scheduled", {"id": "action-1", "name": "run_read_only_command"})
    memory.record_action_event(
        "req-1",
        "action_result",
        {
            "action_id": "action-1",
            "name": "run_read_only_command",
            "status": "completed",
            "command_success": True,
            "command_results": [{"command": "seed", "outputs": ["Seed: [12345]"]}],
        },
    )
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
    action_results = memory.recent_action_results_for_player("player-1")
    assert len(action_results) == 1
    assert "Seed: [12345]" in action_results[0]["payload_json"]
    search_results = memory.search("player-1", "12345", limit=5)
    assert search_results == []
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
