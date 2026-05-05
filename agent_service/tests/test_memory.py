from __future__ import annotations

import json
import sqlite3

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

    loaded = memory.agent_context("player-1", world_id="minecraft:overworld", query="村庄在哪里？", limit=10)
    rendered = "\n".join(item["content"] for item in loaded)

    assert "玩家基地在樱花林旁边" in rendered
    assert "村庄在出生点东侧" in rendered
    assert "回答要简洁" in rendered
    assert "其他玩家基地" not in rendered
    assert loaded[0]["label"] == "base"


def test_memory_search_does_not_return_unrelated_world_memories(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    memory.upsert_player({"uuid": "player-1", "name": "zzy"})
    memory.upsert_player({"uuid": "player-2", "name": "__Yan__Yan__"})
    memory.add_agent_memory(
        "world",
        "world",
        "__yan__yan__ 的家",
        "__Yan__Yan__ 的家坐标是 (-17.9, 67, 17.8)，位于主世界出生点附近。",
        importance=4,
    )
    memory.add_agent_memory("player", "player-1", "玩家身份", "你是 zzy，不是 YanYan__。YanYan__ 是另一个玩家。")

    unrelated = memory.search("player-1", "zzy 之前的对话 讨论过什么", limit=8, world_id="world")
    explicit = memory.search("player-1", "YanYan 的家", limit=8, world_id="world")

    assert not any("__Yan__Yan__ 的家坐标" in result.get("content", "") for result in unrelated)
    assert any("__Yan__Yan__ 的家坐标" in result.get("content", "") for result in explicit)


def test_agent_context_loads_world_memory_only_when_relevant(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    memory.upsert_player({"uuid": "player-1", "name": "zzy"})
    memory.add_agent_memory("world", "world", "meeting_point", "这个世界的集合点在南边海滩", importance=4)
    memory.add_agent_memory("player", "player-1", "preference", "回答坐标要简短", importance=3)

    greeting = memory.agent_context("player-1", world_id="world", query="hi", limit=10)
    recall = memory.agent_context("player-1", world_id="world", query="集合点在哪里？", limit=10)

    assert any("回答坐标要简短" in item["content"] for item in greeting)
    assert not any("集合点在南边海滩" in item["content"] for item in greeting)
    assert any("集合点在南边海滩" in item["content"] for item in recall)


def test_agent_memory_rewrite_updates_existing_fact(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    first = memory.add_agent_memory("player", "player-1", "base", "基地在樱花林旁边", importance=2)
    second = memory.add_agent_memory("player", "player-1", "base", "基地在樱花林旁边", importance=5)

    loaded = memory.agent_context("player-1", limit=10)
    matches = [item for item in loaded if item["content"] == "基地在樱花林旁边"]

    assert len(matches) == 1
    assert matches[0]["importance"] == 5
    assert first["operation"] == "inserted"
    assert second["operation"] == "deduplicated"
    assert second["updated_existing"] is True


def test_memory_search_deduplicates_fts_and_like_matches(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    memory.add_agent_memory("player", "player-1", "base", "基地在樱花林旁边", importance=4)

    results = memory.search("player-1", "基地", limit=10)
    matches = [item for item in results if item["content"] == "基地在樱花林旁边"]

    assert len(matches) == 1


def test_specific_agent_memory_label_replaces_stale_fact(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    first = memory.add_agent_memory("player", "player-1", "基地位置", "你的基地在樱花林旁边", importance=2)
    second = memory.add_agent_memory("player", "player-1", "基地位置", "你的基地在沙漠神殿旁边", importance=4)

    loaded = memory.agent_context("player-1", limit=10)
    rendered = "\n".join(item["content"] for item in loaded)

    assert "你的基地在沙漠神殿旁边" in rendered
    assert "你的基地在樱花林旁边" not in rendered
    assert memory.search("player-1", "沙漠神殿", limit=10)
    assert memory.search("player-1", "樱花林", limit=10) == []
    assert first["operation"] == "inserted"
    assert second["operation"] == "replaced"
    assert second["updated_existing"] is True


def test_equivalent_base_location_labels_replace_stale_fact(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    first = memory.add_agent_memory("player", "player-1", "基地位置", "你的基地在樱花林旁边", importance=2)
    second = memory.add_agent_memory("player", "player-1", "base_location", "你的基地在沙漠神殿旁边", importance=4)

    loaded = memory.agent_context("player-1", limit=10)
    rendered = "\n".join(item["content"] for item in loaded)

    assert "你的基地在沙漠神殿旁边" in rendered
    assert "你的基地在樱花林旁边" not in rendered
    assert first["operation"] == "inserted"
    assert second["operation"] == "replaced"
    assert second["updated_existing"] is True


def test_generic_agent_memory_label_remains_append_only(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    memory.add_agent_memory("player", "player-1", "note", "你喜欢云杉木基地", importance=3)
    memory.add_agent_memory("player", "player-1", "note", "你喜欢海边仓库", importance=3)

    loaded = memory.agent_context("player-1", limit=10)
    rendered = "\n".join(item["content"] for item in loaded)

    assert "你喜欢云杉木基地" in rendered
    assert "你喜欢海边仓库" in rendered


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
        messages=[
            {"role": "system", "content": "Observed Minecraft state:\n{}"},
            {"role": "user", "content": "查询种子"},
        ],
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
    messages = json.loads(model["messages_summary_json"])
    assert [message["role"] for message in messages] == ["system", "user"]
    assert messages[1]["content_preview"] == "查询种子"
    assert messages[1]["content_length"] == 4


def test_model_call_schema_migrates_prompt_summary_column(tmp_path) -> None:
    db_path = tmp_path / "mina.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            create table model_calls (
                id integer primary key autoincrement,
                request_id text not null,
                subturn integer not null,
                model text not null,
                messages_count integer not null,
                tools_json text not null,
                status text not null,
                finish_reason text not null,
                usage_json text not null,
                response_json text not null,
                error text not null,
                created_at real not null
            )
            """
        )

    memory = MemoryStore(db_path)
    memory.record_model_call(
        request_id="req-migrated",
        subturn=1,
        model="deepseek-v4-flash",
        messages_count=1,
        tools=[],
        status="ok",
        messages=[{"role": "user", "content": "你好"}],
    )

    call = memory.recent_model_calls("req-migrated")[0]
    assert json.loads(call["messages_summary_json"])[0]["content_preview"] == "你好"


def test_schema_no_longer_creates_body_task_tables(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    with memory._connect() as conn:  # noqa: SLF001 - schema regression test.
        names = {
            row[0]
            for row in conn.execute("select name from sqlite_master where type='table'").fetchall()
        }

    assert "task_events" not in names
    assert "skill_reflections" not in names
