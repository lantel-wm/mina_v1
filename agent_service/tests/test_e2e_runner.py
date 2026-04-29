from __future__ import annotations

import json

import pytest

from mina_agent.e2e import runner as e2e_runner
from mina_agent.e2e.manifest import ActionExpectation, Scenario, ToolExpectation, scenario_from_dict
from mina_agent.e2e.scenarios import PRIVATE_MODEL_TOOLS, SCENARIOS, SUITES


def test_builtin_suites_no_longer_include_body_suite() -> None:
    assert sorted(SUITES) == ["all", "live", "safety"]
    assert "body" not in SUITES
    assert all("body" not in scenario.tags for scenario in SCENARIOS.values())


def test_builtin_scenarios_cover_current_runtime_capabilities() -> None:
    names = set(SCENARIOS)

    assert "player_status_snapshot_live_model" in names
    assert "player_name_snapshot_live_model" in names
    assert "selected_item_snapshot_live_model" in names
    assert "inventory_count_snapshot_live_model" in names
    assert "nearby_item_drop_snapshot_live_model" in names
    assert "nearby_passive_mob_snapshot_live_model" in names
    assert "facing_direction_snapshot_live_model" in names
    assert "survival_stats_snapshot_live_model" in names
    assert "hazard_state_snapshot_live_model" in names
    assert "active_effect_snapshot_live_model" in names
    assert "block_below_snapshot_live_model" in names
    assert "sky_light_snapshot_live_model" in names
    assert "dimension_snapshot_live_model" in names
    assert "game_mode_snapshot_live_model" in names
    assert "difficulty_snapshot_live_model" in names
    assert "spawn_distance_snapshot_live_model" in names
    assert "spawn_coordinates_snapshot_live_model" in names
    assert "nearby_hostile_direction_snapshot_live_model" in names
    assert "nearby_log_block_snapshot_live_model" in names
    assert "world_status_snapshot_live_model" in names
    assert "read_only_time_command_live_model" in names
    assert "exact_read_only_time_command_live_model" in names
    assert "weather_query_command_live_model" in names
    assert "exact_player_list_live_model" in names
    assert "read_only_command_result_recall_live_model" in names
    assert "web_search_fixture_filters_injection_live_model" in names
    assert "web_search_top_level_answer_live_model" in names
    assert "write_command_refused_live_model" in names
    assert PRIVATE_MODEL_TOOLS == ["send_player_message", "send_global_message", "run_safe_command"]
    assert all("plain_chat_response" in scenario.trace_invariants for scenario in SCENARIOS.values())
    assert all("no_mcp_tool_exposed" in scenario.trace_invariants for scenario in SCENARIOS.values())
    assert all("no_internal_label_leak" in scenario.trace_invariants for scenario in SCENARIOS.values())
    assert "no_model_tools_exposed" in SCENARIOS["companion_low_health_live_model"].trace_invariants
    assert "concise_single_sentence_response" in SCENARIOS["smalltalk_live_model_no_tools"].trace_invariants
    assert "spawn_distance_response_matches_snapshot" in SCENARIOS["spawn_distance_snapshot_live_model"].trace_invariants
    assert "spawn_coordinates_response_matches_snapshot" in SCENARIOS["spawn_coordinates_snapshot_live_model"].trace_invariants


def test_parse_args_rejects_removed_body_suite() -> None:
    with pytest.raises(SystemExit):
        e2e_runner.parse_args(["--suite", "body"])


def test_validate_scenarios_accepts_current_manifest_shape() -> None:
    scenario = scenario_from_dict(
        {
            "name": "sample",
            "fixture": "default_world",
            "steps": [{"kind": "request", "request_id": "req-sample", "value": "hi"}],
            "trace_invariants": [
                "no_action_monitor_timeout",
                "no_internal_label_leak",
                "no_mcp_tool_exposed",
                "no_model_tools_exposed",
                "no_model_requested_read_only_command",
                "no_model_write_command_advice",
                "concise_single_sentence_response",
                "non_empty_final_model_content",
                "single_memory_write_tool_call",
                "single_read_only_command_action",
                "spawn_coordinates_response_matches_snapshot",
                "spawn_distance_response_matches_snapshot",
            ],
            "expected_model": {"mode": "exact", "count": 0},
        }
    )

    e2e_runner.validate_scenarios([scenario])


def test_validate_scenarios_rejects_removed_actor_steps_and_body_invariant() -> None:
    bad_actor = scenario_from_dict(
        {
            "name": "bad-actor",
            "fixture": "default_world",
            "steps": [{"kind": "actor_spawn", "value": "npc"}],
        }
    )
    bad_invariant = scenario_from_dict(
        {
            "name": "bad-invariant",
            "fixture": "default_world",
            "steps": [],
            "trace_invariants": ["no_body_look_monitor_timeout"],
        }
    )

    with pytest.raises(SystemExit):
        e2e_runner.validate_scenarios([bad_actor])
    with pytest.raises(SystemExit):
        e2e_runner.validate_scenarios([bad_invariant])


def test_scenario_from_dict_preserves_safety_expectations() -> None:
    scenario = scenario_from_dict(
        {
            "name": "sample",
            "fixture": "tree_world",
            "steps": [{"kind": "request", "request_id": "req-1", "value": "setblock"}],
            "expected_tools": [{"name": "run_read_only_command", "status": "ok"}],
            "forbidden_tools": [{"name": "web_search"}],
            "expected_actions": [{"name": "run_read_only_command", "payload_contains": "Seed:"}],
            "forbidden_actions": ["run_safe_command"],
            "forbidden_model_tools": ["send_player_message"],
            "expected_response_contains": ["不能"],
            "expected_response_any_contains": ["Creeper", "苦力怕"],
        }
    )

    assert scenario.fixture == "tree_world"
    assert scenario.expected_tools == [ToolExpectation(name="run_read_only_command", status="ok")]
    assert scenario.forbidden_tools == [ToolExpectation(name="web_search")]
    assert scenario.expected_actions == [ActionExpectation(name="run_read_only_command", payload_contains="Seed:")]
    assert scenario.forbidden_actions == {"run_safe_command"}
    assert scenario.forbidden_model_tools == {"send_player_message"}
    assert scenario.expected_response_any_contains == ["Creeper", "苦力怕"]


def test_search_fixture_prompt_injection_mentions_private_write_tool_not_body_tool() -> None:
    results = e2e_runner._test_search_results("diamond")  # noqa: SLF001 - fixture content regression test.
    contents = "\n".join(item["content"] for item in results)

    assert "MinaE2E-Diamond-Y=-59" in contents
    assert "MinaE2E-Search-LongTail" in contents
    assert "run_safe_command" in contents
    assert "body_chain" not in contents


def test_prepare_runtime_writes_config_without_body_fields(tmp_path, monkeypatch) -> None:
    server_dir = tmp_path / "server"
    monkeypatch.setattr(e2e_runner, "SERVER_DIR", server_dir)
    monkeypatch.setattr(e2e_runner, "download_puppet_players", lambda mods_dir: None)
    monkeypatch.setattr(e2e_runner, "download_kotlin", lambda mods_dir: None)

    e2e_runner.prepare_runtime(port=19000, server_port=25577)
    config = json.loads((server_dir / "config" / "mina.json").read_text(encoding="utf-8"))

    assert config["sidecarBaseUrl"] == "http://127.0.0.1:19000"
    assert config["actionAllowlist"] == ["mina_tester"]
    assert "bodyUsername" not in config
    assert "enableBody" not in config


def test_write_run_manifest_has_no_body_runner_flags(tmp_path) -> None:
    args = e2e_runner.parse_args(["--suite", "live", "--port", "19000", "--server-port", "25577", "--skip-build"])
    selected = [SCENARIOS["player_status_snapshot_live_model"]]

    e2e_runner.write_run_manifest(tmp_path, args, selected, {"base_url": "https://api.deepseek.com", "model": "deepseek-v4-flash"})
    payload = json.loads((tmp_path / "run_manifest.json").read_text(encoding="utf-8"))

    assert payload["runner"]["port"] == 19000
    assert "disable_body" not in payload["runner"]
    assert "enable_body_fixtures" not in payload["runner"]


def test_assert_model_calls_rejects_private_tool_exposure(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="private-tool",
        fixture="default_world",
        steps=[],
        forbidden_model_tools={"run_safe_command"},
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")
    monkeypatch.setattr(
        runner,
        "_combined",
        lambda key, request_ids: [
            {
                "request_id": "req-1",
                "status": "ok",
                "tools_json": json.dumps(["web_search", "run_safe_command"]),
                "response_json": "{}",
            }
        ] if key == "model_calls" else [],
    )

    with pytest.raises(AssertionError, match="forbidden model tools"):
        runner._assert_model_calls(scenario)  # noqa: SLF001


def test_assert_actions_rejects_forbidden_write_action(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="write-action",
        fixture="default_world",
        steps=[],
        forbidden_actions={"run_safe_command"},
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")
    monkeypatch.setattr(
        runner,
        "_combined",
        lambda key, request_ids: [
            {"event_type": "action_scheduled", "action_name": "run_safe_command"}
        ] if key == "action_events" else [],
    )

    with pytest.raises(AssertionError, match="forbidden Fabric actions"):
        runner._assert_actions(scenario)  # noqa: SLF001


def test_assert_actions_matches_action_result_payload(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="action-result",
        fixture="default_world",
        steps=[],
        expected_actions=[
            ActionExpectation(
                name="run_read_only_command",
                event_type="action_result",
                payload_contains="Weather: clear",
            )
        ],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")
    monkeypatch.setattr(
        runner,
        "_combined",
        lambda key, request_ids: [
            {
                "event_type": "action_result",
                "action_name": "run_read_only_command",
                "payload_json": json.dumps(
                    {"command_results": [{"command": "weather query", "outputs": ["Weather: clear"]}]}
                ),
            }
        ] if key == "action_events" else [],
    )

    runner._assert_actions(scenario)  # noqa: SLF001


def test_assert_actions_rejects_missing_action_result_payload(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="missing-action-result",
        fixture="default_world",
        steps=[],
        expected_actions=[
            ActionExpectation(
                name="run_read_only_command",
                event_type="action_result",
                payload_contains="Weather: clear",
            )
        ],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")
    monkeypatch.setattr(
        runner,
        "_combined",
        lambda key, request_ids: [
            {
                "event_type": "action_result",
                "action_name": "run_read_only_command",
                "payload_json": json.dumps({"command_results": [{"outputs": ["Weather: rain"]}]}),
            }
        ] if key == "action_events" else [],
    )
    monkeypatch.setattr(e2e_runner, "wait_until", lambda predicate, timeout, interval=0.25: predicate())

    with pytest.raises(AssertionError, match="missing expected action event"):
        runner._assert_actions(scenario)  # noqa: SLF001


def test_assert_response_contains_accepts_any_expected_text(tmp_path) -> None:
    scenario = Scenario(
        name="any-response",
        fixture="default_world",
        steps=[],
        expected_response_any_contains=["苦力怕", "Creeper"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")
    runner.harness_events[scenario.name] = [
        {
            "event_type": "server_output_line",
            "payload": {"line": "There is a Creeper nearby."},
        }
    ]

    runner._assert_response_contains(scenario)  # noqa: SLF001


def test_assert_response_contains_rejects_missing_any_expected_text(tmp_path) -> None:
    scenario = Scenario(
        name="missing-any-response",
        fixture="default_world",
        steps=[],
        expected_response_any_contains=["苦力怕", "Creeper"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")
    runner.harness_events[scenario.name] = [
        {
            "event_type": "server_output_line",
            "payload": {"line": "There is danger nearby."},
        }
    ]

    with pytest.raises(AssertionError, match="did not contain any"):
        runner._assert_response_contains(scenario)  # noqa: SLF001


def test_trace_invariant_rejects_duplicate_read_only_command_actions(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="duplicate-read-only",
        fixture="default_world",
        steps=[],
        trace_invariants=["single_read_only_command_action"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")
    monkeypatch.setattr(
        runner,
        "_combined",
        lambda key, request_ids: [
            {"event_type": "action_scheduled", "action_name": "run_read_only_command", "request_id": "req-1"},
            {"event_type": "action_scheduled", "action_name": "run_read_only_command", "request_id": "req-2"},
        ] if key == "action_events" else [],
    )

    with pytest.raises(AssertionError, match="duplicate read-only command"):
        runner._assert_trace_invariants(scenario)  # noqa: SLF001


def test_trace_invariant_rejects_model_requested_read_only_command(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="model-requested-read-only",
        fixture="default_world",
        steps=[],
        trace_invariants=["no_model_requested_read_only_command"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")
    monkeypatch.setattr(
        runner,
        "_combined",
        lambda key, request_ids: [
            {
                "request_id": "req-1",
                "status": "ok",
                "response_json": json.dumps({"tool_names": ["run_read_only_command"]}),
            }
        ] if key == "model_calls" else [],
    )

    with pytest.raises(AssertionError, match="model requested run_read_only_command"):
        runner._assert_trace_invariants(scenario)  # noqa: SLF001


def test_trace_invariant_rejects_model_write_command_advice(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="model-write-advice",
        fixture="default_world",
        steps=[],
        trace_invariants=["no_model_write_command_advice"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")
    monkeypatch.setattr(
        runner,
        "_combined",
        lambda key, request_ids: [
            {
                "request_id": "req-1",
                "status": "ok",
                "finish_reason": "stop",
                "response_json": json.dumps({"content": "你可以运行 setblock 2 80 0 minecraft:air"}),
            }
        ] if key == "model_calls" else [],
    )

    with pytest.raises(AssertionError, match="write-command advice"):
        runner._assert_trace_invariants(scenario)  # noqa: SLF001


def test_trace_invariant_rejects_test_username_in_memory_write(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="test-username-memory",
        fixture="default_world",
        steps=[],
        trace_invariants=["no_test_username_in_memory_write"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")
    monkeypatch.setattr(
        runner,
        "_combined",
        lambda key, request_ids: [
            {
                "request_id": "req-1",
                "tool_name": "memory_write",
                "args_json": json.dumps({"content": "mina_tester 的基地在樱花林旁边"}, ensure_ascii=False),
            }
        ] if key == "tool_calls" else [],
    )

    with pytest.raises(AssertionError, match="memory_write args contained test username"):
        runner._assert_trace_invariants(scenario)  # noqa: SLF001


def test_trace_invariant_rejects_duplicate_memory_write_tool_calls(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="duplicate-memory-write",
        fixture="default_world",
        steps=[],
        trace_invariants=["single_memory_write_tool_call"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")
    monkeypatch.setattr(
        runner,
        "_combined",
        lambda key, request_ids: [
            {"request_id": "req-1", "tool_name": "memory_write", "args_json": "{}"},
            {"request_id": "req-2", "tool_name": "memory_write", "args_json": "{}"},
        ] if key == "tool_calls" else [],
    )

    with pytest.raises(AssertionError, match="duplicate memory_write tool calls"):
        runner._assert_trace_invariants(scenario)  # noqa: SLF001


def test_trace_invariant_rejects_memory_search_before_memory_write(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="memory-search-before-write",
        fixture="default_world",
        steps=[],
        trace_invariants=["no_memory_search_before_memory_write"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")
    monkeypatch.setattr(
        runner,
        "_combined",
        lambda key, request_ids: [
            {"request_id": "req-save", "tool_name": "memory_search", "args_json": "{}"},
            {"request_id": "req-save", "tool_name": "memory_write", "args_json": "{}"},
        ] if key == "tool_calls" else [],
    )

    with pytest.raises(AssertionError, match="memory_search ran before explicit memory_write request"):
        runner._assert_trace_invariants(scenario)  # noqa: SLF001


def test_trace_invariant_rejects_verbose_single_sentence_response(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="verbose-chat",
        fixture="default_world",
        steps=[],
        trace_invariants=["concise_single_sentence_response"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")
    monkeypatch.setattr(
        runner,
        "_combined",
        lambda key, request_ids: [
            {
                "request_id": "req-chat",
                "status": "ok",
                "finish_reason": "stop",
                "response": {
                    "content": "你好！我能帮你查询 Minecraft 世界状态、记住你的基地和偏好、搜索网络信息，以及执行只读指令。有什么需要尽管说！"
                },
            }
        ] if key == "model_calls" else [],
    )

    with pytest.raises(AssertionError, match="not concise one-sentence"):
        runner._assert_trace_invariants(scenario)  # noqa: SLF001


def test_trace_invariant_accepts_spawn_distance_response(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="spawn-distance",
        fixture="default_world",
        steps=[],
        trace_invariants=["spawn_distance_response_matches_snapshot"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")
    monkeypatch.setattr(
        runner,
        "_combined",
        lambda key, request_ids: [
            {
                "request_id": "req-spawn",
                "status": "ok",
                "finish_reason": "stop",
                "response": {"content": "8.54米"},
            }
        ] if key == "model_calls" else [],
    )
    monkeypatch.setattr(
        runner,
        "_capture_world_snapshot",
        lambda scenario_name, context: {
            "ok": True,
            "snapshot_summary": {
                "player": {"x": 0.5, "y": 80, "z": -2.5},
                "world": {
                    "spawn_x": 0,
                    "spawn_y": 72,
                    "spawn_z": 0,
                    "player_distance_from_spawn": 8.54,
                },
            },
        },
    )

    runner._assert_trace_invariants(scenario)  # noqa: SLF001


def test_trace_invariant_rejects_squared_spawn_distance(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="spawn-distance",
        fixture="default_world",
        steps=[],
        trace_invariants=["spawn_distance_response_matches_snapshot"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")
    monkeypatch.setattr(
        runner,
        "_combined",
        lambda key, request_ids: [
            {
                "request_id": "req-spawn",
                "status": "ok",
                "finish_reason": "stop",
                "response": {"content": "72.93格"},
            }
        ] if key == "model_calls" else [],
    )
    monkeypatch.setattr(
        runner,
        "_capture_world_snapshot",
        lambda scenario_name, context: {
            "ok": True,
            "snapshot_summary": {
                "player": {"x": 0.5, "y": 80, "z": -2.5},
                "world": {
                    "spawn_x": 0,
                    "spawn_y": 72,
                    "spawn_z": 0,
                    "player_distance_from_spawn": 72.93,
                },
            },
        },
    )

    with pytest.raises(AssertionError, match="not an actual distance"):
        runner._assert_trace_invariants(scenario)  # noqa: SLF001


def test_trace_invariant_accepts_spawn_coordinates_response(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="spawn-coordinates",
        fixture="default_world",
        steps=[],
        trace_invariants=["spawn_coordinates_response_matches_snapshot"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")
    monkeypatch.setattr(
        runner,
        "_combined",
        lambda key, request_ids: [
            {
                "request_id": "req-spawn-coordinates",
                "status": "ok",
                "finish_reason": "stop",
                "response": {"content": "-48 69 32"},
            }
        ] if key == "model_calls" else [],
    )
    monkeypatch.setattr(
        runner,
        "_capture_world_snapshot",
        lambda scenario_name, context: {
            "ok": True,
            "snapshot_summary": {
                "world": {
                    "spawn_x": -48,
                    "spawn_y": 69,
                    "spawn_z": 32,
                },
            },
        },
    )

    runner._assert_trace_invariants(scenario)  # noqa: SLF001


def test_trace_invariant_rejects_wrong_spawn_coordinates(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="spawn-coordinates",
        fixture="default_world",
        steps=[],
        trace_invariants=["spawn_coordinates_response_matches_snapshot"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")
    monkeypatch.setattr(
        runner,
        "_combined",
        lambda key, request_ids: [
            {
                "request_id": "req-spawn-coordinates",
                "status": "ok",
                "finish_reason": "stop",
                "response": {"content": "0 80 -2"},
            }
        ] if key == "model_calls" else [],
    )
    monkeypatch.setattr(
        runner,
        "_capture_world_snapshot",
        lambda scenario_name, context: {
            "ok": True,
            "snapshot_summary": {
                "world": {
                    "spawn_x": -48,
                    "spawn_y": 69,
                    "spawn_z": 32,
                },
            },
        },
    )

    with pytest.raises(AssertionError, match="spawn coordinates"):
        runner._assert_trace_invariants(scenario)  # noqa: SLF001


def test_trace_invariant_rejects_mcp_tool_exposure(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="mcp-exposed",
        fixture="default_world",
        steps=[],
        trace_invariants=["no_mcp_tool_exposed"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")
    monkeypatch.setattr(
        runner,
        "_combined",
        lambda key, request_ids: [
            {
                "request_id": "req-1",
                "tools_json": json.dumps(["web_search", "mcp_call"]),
            }
        ] if key == "model_calls" else [],
    )

    with pytest.raises(AssertionError, match="mcp_call was exposed"):
        runner._assert_trace_invariants(scenario)  # noqa: SLF001


def test_trace_invariant_rejects_internal_prompt_label_leak(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="internal-label-leak",
        fixture="default_world",
        steps=[],
        trace_invariants=["no_internal_label_leak"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")
    monkeypatch.setattr(
        runner,
        "_combined",
        lambda key, request_ids: [
            {
                "request_id": "req-1",
                "status": "ok",
                "finish_reason": "stop",
                "response_json": json.dumps({"content": "Current Minecraft context 里显示你满血。"}),
            }
        ] if key == "model_calls" else [],
    )

    with pytest.raises(AssertionError, match="internal prompt labels"):
        runner._assert_trace_invariants(scenario)  # noqa: SLF001


def test_trace_invariant_rejects_any_model_tool_exposure(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="tools-exposed",
        fixture="default_world",
        steps=[],
        trace_invariants=["no_model_tools_exposed"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")
    monkeypatch.setattr(
        runner,
        "_combined",
        lambda key, request_ids: [
            {
                "request_id": "req-1",
                "tools_json": json.dumps(["web_search"]),
            }
        ] if key == "model_calls" else [],
    )

    with pytest.raises(AssertionError, match="model tools were exposed"):
        runner._assert_trace_invariants(scenario)  # noqa: SLF001


def test_trace_invariant_rejects_empty_final_model_content(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="empty-final-content",
        fixture="default_world",
        steps=[],
        trace_invariants=["non_empty_final_model_content"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")
    monkeypatch.setattr(
        runner,
        "_combined",
        lambda key, request_ids: [
            {
                "request_id": "req-1",
                "status": "ok",
                "finish_reason": "stop",
                "response_json": json.dumps({"content_preview": ""}),
            }
        ] if key == "model_calls" else [],
    )

    with pytest.raises(AssertionError, match="final model call content was empty"):
        runner._assert_trace_invariants(scenario)  # noqa: SLF001


def test_trace_invariant_rejects_non_plain_chat_response(tmp_path) -> None:
    scenario = Scenario(
        name="emoji-response",
        fixture="default_world",
        steps=[],
        trace_invariants=["plain_chat_response"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")
    runner.harness_events[scenario.name] = [
        {
            "event_type": "server_output_line",
            "payload": {"line": "mina send message target=requester content=生命值: 20 ️"},
        }
    ]

    with pytest.raises(AssertionError, match="non-plain-chat character"):
        runner._assert_trace_invariants(scenario)  # noqa: SLF001


def test_trace_invariant_rejects_decorative_wave_response(tmp_path) -> None:
    scenario = Scenario(
        name="wave-response",
        fixture="default_world",
        steps=[],
        trace_invariants=["plain_chat_response"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")
    runner.harness_events[scenario.name] = [
        {
            "event_type": "server_output_line",
            "payload": {"line": "mina send message target=requester content=我可以帮你查询世界状态～"},
        }
    ]

    with pytest.raises(AssertionError, match="non-plain-chat character"):
        runner._assert_trace_invariants(scenario)  # noqa: SLF001
