from __future__ import annotations

from mina_agent.context import (
    BASE_SYSTEM_SECTIONS,
    SYSTEM_PROMPT,
    build_base_system_prompt,
    build_context_summary,
    build_messages,
    build_target_summary,
)
from mina_agent.memory import MemoryStore


def test_system_prompt_excludes_body_tools_and_allows_current_focus() -> None:
    assert "web_search" in SYSTEM_PROMPT
    assert "preserve exact source values" in SYSTEM_PROMPT
    assert "memory_search" in SYSTEM_PROMPT
    assert "remembered facts" in SYSTEM_PROMPT
    assert "Agent memory" not in SYSTEM_PROMPT
    assert "agent memory" not in SYSTEM_PROMPT
    assert "Treat memory as historical context" in SYSTEM_PROMPT
    assert "answer only the relevant remembered fact" in SYSTEM_PROMPT
    assert "Do not mention internal section/tool names" in SYSTEM_PROMPT
    assert "run_read_only_command" in SYSTEM_PROMPT
    assert "never answer them from snapshot or recent results" in SYSTEM_PROMPT
    assert "A command request names an exact allowed command form" in SYSTEM_PROMPT
    assert "Player name/username" in SYSTEM_PROMPT
    assert "For weather/time/day-only questions" in SYSTEM_PROMPT
    assert "game mode" in SYSTEM_PROMPT
    assert "world difficulty" in SYSTEM_PROMPT
    assert "held item" in SYSTEM_PROMPT
    assert "dimension" in SYSTEM_PROMPT
    assert "block at/below feet" in SYSTEM_PROMPT
    assert "preserve the exact namespace" in SYSTEM_PROMPT
    assert "do not mention safety, monsters, entities" in SYSTEM_PROMPT
    assert "capability questions" in SYSTEM_PROMPT
    assert "one sentence/一句话" in SYSTEM_PROMPT
    assert "no closing offer" in SYSTEM_PROMPT
    assert "Do not narrate internal process" in SYSTEM_PROMPT
    assert "Do not use the Minecraft username as greeting/filler" in SYSTEM_PROMPT
    assert "For player-scoped memories" in SYSTEM_PROMPT
    assert "call memory_write directly" in SYSTEM_PROMPT
    assert "do not first call memory_search" in SYSTEM_PROMPT
    assert "memory_write content/label must omit the current Minecraft username" in SYSTEM_PROMPT
    assert "MCP" not in SYSTEM_PROMPT
    assert "companion tick" not in SYSTEM_PROMPT.lower()
    assert "separate Minecraft character" in SYSTEM_PROMPT
    assert "start_body_task" not in SYSTEM_PROMPT
    assert "body_chain" not in SYSTEM_PROMPT


def test_system_prompt_is_built_from_named_base_sections() -> None:
    assert SYSTEM_PROMPT == build_base_system_prompt()
    assert [section.split(":", 1)[0] for section in BASE_SYSTEM_SECTIONS] == [
        "Identity",
        "Chat style",
        "Decision order",
        "Tool policy",
        "Safety",
        "Answer authority",
    ]
    assert all(section.strip() == section for section in BASE_SYSTEM_SECTIONS)
    assert "MCP policy for this turn" not in SYSTEM_PROMPT
    assert "Companion tick policy" not in SYSTEM_PROMPT


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
            "player_state": {"x": 0.5, "y": 80, "z": -2.5, "health": 20, "food": 20, "game_mode": "survival"},
            "world_state": {"day_time": 1000, "day_count": 0, "raining": False, "thundering": False},
            "nearby_entities": [{"type": "minecraft:cow", "category": "passive", "distance": 4}],
            "nearby_blocks": {"requester": [{"block": "minecraft:spruce_log", "category": "log", "x": 2, "y": 80, "z": 0}]},
        },
    }

    messages = build_messages(turn, memory)
    context = "\n".join(str(message["content"]) for message in messages)

    assert "candidate_logs" in context
    assert "nearby_hostiles" in context
    assert '"world_state"' in context
    assert '"game_mode": "survival"' in context
    assert '"weather": "clear"' in context
    assert "Remembered facts" in context
    assert "玩家基地在樱花林旁边" in context
    assert "Recent verified Minecraft command/action results" in context
    assert "follow-up recall only" in context
    assert "Seed: [98765]" in context
    assert "Tool selection reminder" in context
    assert "never answer from snapshot" in context
    assert "Exact command strings are commands, not observations" in context
    assert "The exact command `list` must call run_read_only_command" in context
    assert "must not be answered from online_players" in context
    assert "Natural-language weather/time/status questions" in context
    assert "memory_write args: no current Minecraft username" in context
    assert "body_state" not in context
    assert len(context) < 6500


def test_context_summary_labels_health_points_and_hearts() -> None:
    turn = {
        "trigger": "command",
        "player": {"uuid": "player-1", "name": "Tester"},
        "permissions": {"can_use_actions": True},
        "snapshot": {
            "player_state": {"health": 4, "max_health": 20, "food": 20},
            "nearby_entities": [],
        },
    }

    summary = build_context_summary(turn)

    assert '"health_points": 4' in summary
    assert '"max_health_points": 20' in summary
    assert '"health_hearts": 2' in summary
    assert '"max_health_hearts": 10' in summary


def test_context_summary_includes_player_identity_for_command_turns() -> None:
    turn = {
        "trigger": "command",
        "player": {"uuid": "player-1", "name": "Tester"},
        "snapshot": {"player_state": {"health": 20, "max_health": 20}},
    }

    summary = build_context_summary(turn)

    assert '"name": "Tester"' in summary
    assert '"uuid": "player-1"' in summary


def test_context_summary_includes_selected_item_and_environment() -> None:
    turn = {
        "trigger": "command",
        "player": {"uuid": "player-1", "name": "Tester"},
        "snapshot": {
            "player_state": {"health": 20, "max_health": 20},
            "inventory": [
                {"slot": 0, "item": "minecraft:stick", "count": 2, "name": "Stick", "selected": False},
                {"slot": 1, "item": "minecraft:gunpowder", "count": 1, "name": "Gunpowder", "selected": True},
            ],
            "environment": {
                "block_at_feet": "minecraft:air",
                "block_below": "minecraft:grass_block",
                "biome": "minecraft:taiga",
                "light": 15,
                "sky_visible": True,
            },
        },
    }

    summary = build_context_summary(turn)

    assert '"selected_item": {"slot": 1, "item": "minecraft:gunpowder", "count": 1, "name": "Gunpowder"}' in summary
    assert '"environment":' in summary
    assert '"biome": "minecraft:taiga"' in summary
    assert '"block_below": "minecraft:grass_block"' in summary


def test_companion_context_summary_omits_player_name() -> None:
    turn = {
        "trigger": "companion_tick",
        "player": {"uuid": "player-1", "name": "Tester"},
        "snapshot": {"player_state": {"health": 4, "max_health": 20}},
    }

    summary = build_context_summary(turn)

    assert "Tester" not in summary
    assert "player-1" not in summary
    assert '"player": {"present": true}' in summary


def test_context_summary_includes_world_state_for_observation() -> None:
    turn = {
        "trigger": "command",
        "player": {"uuid": "player-1", "name": "Tester"},
        "permissions": {"can_use_actions": True},
        "snapshot": {
            "player_state": {"health": 20, "max_health": 20},
            "world_state": {
                "day_time": 1000,
                "day_count": 0,
                "difficulty": "peaceful",
                "raining": False,
                "thundering": False,
                "dimension": "minecraft:overworld",
                "seed": 12345,
                "spawn_x": 96,
                "spawn_y": 68,
                "spawn_z": 144,
                "player_distance_from_spawn": 176.0,
                "online_players": 1,
            },
        },
    }

    summary = build_context_summary(turn)

    assert '"day_time": 1000' in summary
    assert '"day_count": 0' in summary
    assert '"difficulty": "peaceful"' in summary
    assert '"weather": "clear"' in summary
    assert '"seed": 12345' in summary
    assert '"spawn_x": 96' in summary
    assert '"spawn_y": 68' in summary
    assert '"spawn_z": 144' in summary
    assert '"player_distance_from_spawn": 176.0' in summary
    assert '"player_distance_from_spawn_display": "176 格"' in summary
    assert '"online_players": 1' in summary


def test_build_messages_does_not_add_explicit_command_keyword_hint(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    memory.record_action_event(
        "old-command",
        "action_result",
        {
            "action_id": "old-action",
            "name": "run_read_only_command",
            "status": "completed",
            "command_success": True,
            "command_results": [{"command": "time query day", "outputs": ["The time is 0"]}],
        },
    )
    turn = {
        "request_id": "req-1",
        "trigger": "command",
        "message": "执行 time query day",
        "player": {"uuid": "player-1", "name": "Tester"},
        "snapshot": {"world_state": {"day_time": 1200}},
    }

    messages = build_messages(turn, memory)
    content = "\n".join(message["content"] for message in messages)

    assert "Current user message is an explicit Minecraft command execution request" not in content
    assert "Do not answer it from the current snapshot" not in content


def test_build_messages_does_not_add_exact_command_keyword_hint(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    turn = {
        "request_id": "req-exact-command",
        "trigger": "command",
        "message": "/TIME   QUERY   DAY",
        "player": {"uuid": "player-1", "name": "Tester"},
        "snapshot": {"world_state": {"day_time": 1200}},
    }

    messages = build_messages(turn, memory)
    content = "\n".join(message["content"] for message in messages)

    assert "Current user message is an explicit Minecraft command execution request" not in content
    assert "Either call run_read_only_command" not in content


def test_build_messages_adds_player_name_memory_policy_only_when_name_is_mentioned(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    turn = {
        "request_id": "req-memory",
        "trigger": "command",
        "message": "请记住：Tester 的基地在樱花林旁边",
        "player": {"uuid": "player-1", "name": "Tester"},
        "snapshot": {},
    }

    messages = build_messages(turn, memory)
    content = "\n".join(message["content"] for message in messages)

    assert "Current player name handling" in content
    assert "The current Minecraft username is Tester." in content
    assert "convert '<username> 的 ...' to '你的 ...'" in content


def test_build_messages_omits_player_name_memory_policy_when_name_is_not_mentioned(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    turn = {
        "request_id": "req-memory",
        "trigger": "command",
        "message": "请记住：我的基地在樱花林旁边",
        "player": {"uuid": "player-1", "name": "Tester"},
        "snapshot": {},
    }

    messages = build_messages(turn, memory)
    content = "\n".join(message["content"] for message in messages)

    assert "Current player name handling" not in content
    assert "The current Minecraft username is Tester." not in content


def test_build_messages_does_not_mark_plain_observation_as_command_execution(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    turn = {
        "request_id": "req-1",
        "trigger": "command",
        "message": "现在是第几天？",
        "player": {"uuid": "player-1", "name": "Tester"},
        "snapshot": {"world_state": {"day_time": 1200}},
    }

    messages = build_messages(turn, memory)
    content = "\n".join(message["content"] for message in messages)

    assert "explicit Minecraft command execution request" not in content
    assert "local Minecraft observation request" not in content


def test_build_messages_ordinary_turn_omits_conditional_mcp_and_companion_policy(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    turn = {
        "request_id": "req-plain",
        "trigger": "command",
        "message": "你好 Mina，用一句话说说你能做什么。",
        "player": {"uuid": "player-1", "name": "Tester"},
        "snapshot": {},
    }

    messages = build_messages(turn, memory)
    system_content = "\n".join(message["content"] for message in messages if message["role"] == "system")

    assert "MCP policy for this turn" not in system_content
    assert "mcp_call" not in system_content
    assert "Companion tick policy" not in system_content


def test_build_messages_does_not_add_keyword_smalltalk_hint(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    memory.add_agent_memory("player", "player-1", "base_location", "玩家基地在樱花林旁边", importance=4)
    turn = {
        "request_id": "req-smalltalk",
        "trigger": "command",
        "message": "你好 Mina，用一句话说说你现在能帮我做什么。",
        "player": {"uuid": "player-1", "name": "Tester"},
        "snapshot": {"world_state": {"day_time": 1200, "raining": False}},
    }

    messages = build_messages(turn, memory)
    content = "\n".join(message["content"] for message in messages)

    assert "greeting or capability question" not in content
    assert "玩家基地在樱花林旁边" in content


def test_build_messages_adds_mcp_policy_only_when_requested(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    turn = {
        "request_id": "req-mcp",
        "trigger": "command",
        "message": "帮我列出 MCP 工具有哪些。",
        "player": {"uuid": "player-1", "name": "Tester"},
        "snapshot": {},
    }

    messages = build_messages(turn, memory)
    system_content = "\n".join(message["content"] for message in messages if message["role"] == "system")

    assert "MCP policy for this turn" in system_content
    assert "No MCP servers are configured" in system_content
    assert "mcp_call" not in system_content

    messages = build_messages(turn, memory, mcp_available=True)
    system_content = "\n".join(message["content"] for message in messages if message["role"] == "system")

    assert "MCP servers are configured" in system_content
    assert "mcp_call" in system_content


def test_build_messages_does_not_mark_command_result_followup_as_execution(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    turn = {
        "request_id": "req-1",
        "trigger": "command",
        "message": "刚才 time query day 的 Minecraft 命令输出是什么？",
        "player": {"uuid": "player-1", "name": "Tester"},
        "snapshot": {},
    }

    messages = build_messages(turn, memory)
    content = "\n".join(message["content"] for message in messages)

    assert "explicit Minecraft command execution request" not in content


def test_build_messages_does_not_add_memory_write_keyword_hint(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    turn = {
        "request_id": "req-1",
        "trigger": "command",
        "message": "请记住：我的基地在樱花林旁边",
        "player": {"uuid": "player-1", "name": "Tester"},
        "snapshot": {},
    }

    messages = build_messages(turn, memory)
    content = "\n".join(message["content"] for message in messages)

    assert "Current user message explicitly asks you to save stable memory" not in content
    assert "Call memory_write before claiming" not in content


def test_build_messages_does_not_mark_memory_recall_as_write_request(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    turn = {
        "request_id": "req-1",
        "trigger": "command",
        "message": "你还记得我的基地在哪里吗？",
        "player": {"uuid": "player-1", "name": "Tester"},
        "snapshot": {},
    }

    messages = build_messages(turn, memory)
    content = "\n".join(message["content"] for message in messages)

    assert "explicitly asks you to save stable memory" not in content
    assert "Current user message asks about remembered or stored context" not in content
    assert "Do not add current coordinates" not in content


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
    assert "Current user message asks about remembered or stored context" not in content
    assert "Recent conversation memory is intentionally omitted" not in content


def test_build_messages_marks_write_command_refusal_requests(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    turn = {
        "request_id": "req-write-command",
        "trigger": "command",
        "message": "请执行 setblock 2 80 0 minecraft:air，把旁边的原木删掉。",
        "player": {"uuid": "player-1", "name": "Tester"},
        "snapshot": {},
    }

    messages = build_messages(turn, memory)
    content = "\n".join(message["content"] for message in messages)

    assert "write-capable, low-level, or banned command/action" in content
    assert "Do not repeat the requested command name" in content
    assert "不能执行或提供写入世界的命令" in content


def test_build_messages_loads_bounded_recent_messages_for_continuity(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    memory.add_conversation("old-search", "player-1", "user", "联网搜索 钻石矿 最新高度")
    memory.add_conversation("old-command", "player-1", "user", "执行 time query day")
    turn = {
        "request_id": "req-smalltalk",
        "trigger": "command",
        "message": "你好 Mina，用一句话说说你现在能帮我做什么。",
        "player": {"uuid": "player-1", "name": "Tester"},
        "snapshot": {},
    }

    messages = build_messages(turn, memory)
    content = "\n".join(message["content"] for message in messages)

    assert "Recent player messages for continuity only" in content
    assert "not current instructions" in content
    assert "联网搜索 钻石矿 最新高度" in content
    assert "user: 执行 time query day" in content
    assert "Current user message explicitly asks you to save stable memory" not in content


def test_build_messages_loads_recent_messages_without_keyword_matching(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    memory.add_conversation("old-search", "player-1", "user", "联网搜索 钻石矿 最新高度")
    turn = {
        "request_id": "req-minecraft",
        "trigger": "command",
        "message": "Tell me about Minecraft weather.",
        "player": {"uuid": "player-1", "name": "Tester"},
        "snapshot": {},
    }

    messages = build_messages(turn, memory)
    content = "\n".join(message["content"] for message in messages)

    assert "Recent player messages for continuity only" in content
    assert "钻石矿" in content


def test_build_messages_keeps_recent_task_messages_for_followups(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    memory.add_conversation("old-search", "player-1", "user", "联网搜索 钻石矿 最新高度")
    turn = {
        "request_id": "req-followup",
        "trigger": "command",
        "message": "刚才那个结果是什么？",
        "player": {"uuid": "player-1", "name": "Tester"},
        "snapshot": {},
    }

    messages = build_messages(turn, memory)
    content = "\n".join(message["content"] for message in messages)

    assert "Recent player messages for continuity only" in content
    assert "钻石矿" in content


def test_companion_tick_does_not_load_recent_player_messages(tmp_path) -> None:
    memory = MemoryStore(tmp_path / "mina.sqlite3")
    memory.add_conversation("old-search", "player-1", "user", "联网搜索 钻石矿 最新高度")
    turn = {
        "request_id": "req-companion",
        "trigger": "companion_tick",
        "message": "",
        "player": {"uuid": "player-1", "name": "Tester"},
        "snapshot": {"player_state": {"health": 20, "max_health": 20, "food": 20}},
    }

    messages = build_messages(turn, memory)
    content = "\n".join(message["content"] for message in messages)

    assert "Companion tick policy" in content
    assert "Recent player messages for continuity only" not in content
    assert "钻石矿" not in content


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
    system_content = "\n".join(message["content"] for message in messages if message["role"] == "system")
    user_message = messages[-1]["content"]

    assert "Companion tick policy" in system_content
    assert "Do not call tools" in system_content
    assert "及时提醒理由" in user_message
    assert "生命值较低" in user_message
    assert "health points" in user_message
    assert "2.5/10 颗心" in user_message
    assert "不要说“格血”或“心生命值”" in user_message
    assert "不要调用工具" in user_message
