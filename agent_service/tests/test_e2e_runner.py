from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from mina_agent.e2e import runner as e2e_runner
from mina_agent.e2e import scenarios as e2e_scenarios
from mina_agent.e2e.manifest import ActionExpectation, Scenario, ScenarioStep, ToolExpectation, scenario_from_dict
from mina_agent.e2e.scenarios import PRIVATE_MODEL_TOOLS, SCENARIOS, SUITES


def test_builtin_suites_no_longer_include_body_suite() -> None:
    assert sorted(SUITES) == ["all", "live", "matrix", "safety", "stress"]
    assert "body" not in SUITES
    assert all("body" not in scenario.tags for scenario in SCENARIOS.values())
    assert len(SUITES["live"]) < len(SUITES["matrix"])
    assert all(name in SCENARIOS for name in SUITES["live"])
    assert all("live_gate" in SCENARIOS[name].tags for name in SUITES["live"])
    assert all("matrix" in SCENARIOS[name].tags for name in SUITES["matrix"])
    assert all("stress" in SCENARIOS[name].tags for name in SUITES["stress"])


def test_builtin_scenarios_cover_current_runtime_capabilities() -> None:
    names = set(SCENARIOS)

    assert "status_triage_realistic_live_model" in names
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
    assert "current_date_context_live_model" in names
    assert "current_weekday_context_live_model" in names
    assert "tomorrow_date_context_live_model" in names
    assert "current_time_context_live_model" in names
    assert "game_time_then_real_time_disambiguation_live_model" in names
    assert "read_only_time_command_live_model" in names
    assert "exact_read_only_time_command_live_model" in names
    assert "exact_gametime_command_live_model" in names
    assert "weather_query_command_live_model" in names
    assert "exact_player_list_live_model" in names
    assert "exact_player_list_uuids_live_model" in names
    assert "read_only_command_result_recall_live_model" in names
    assert "command_result_interpretation_followup_live_model" in names
    assert "web_search_fixture_filters_injection_live_model" in names
    assert "web_search_top_level_answer_live_model" in names
    assert "search_then_personalized_followup_live_model" in names
    assert "low_evidence_search_followup_live_model" in names
    assert "memory_preference_affects_later_answer_live_model" in names
    assert "uncertain_memory_not_saved_live_model" in names
    assert "confirm_then_accept_command_live_model" in names
    assert "confirm_then_decline_command_live_model" in names
    assert "dangerous_memory_instruction_refused_live_model" in names
    assert "plain_capability_no_internal_leak_live_model" in names
    assert "write_command_refused_live_model" in names
    assert PRIVATE_MODEL_TOOLS == ["send_player_message", "send_global_message", "run_safe_command"]
    assert all("plain_chat_response" in scenario.trace_invariants for scenario in SCENARIOS.values())
    assert all("no_mcp_tool_exposed" in scenario.trace_invariants for scenario in SCENARIOS.values())
    assert all("no_internal_label_leak" in scenario.trace_invariants for scenario in SCENARIOS.values())
    assert SCENARIOS["player_status_snapshot_live_model"].steps[0].kind == "assert"
    assert SCENARIOS["player_status_snapshot_live_model"].steps[0].value == "no_nearby_entities"
    assert "no_model_tools_exposed" in SCENARIOS["companion_low_health_live_model"].trace_invariants
    assert SCENARIOS["companion_low_health_live_model"].world_asserts == ["low_health"]
    assert "concise_single_sentence_response" in SCENARIOS["smalltalk_live_model_no_tools"].trace_invariants
    assert "spawn_distance_response_matches_snapshot" in SCENARIOS["spawn_distance_snapshot_live_model"].trace_invariants
    assert "spawn_coordinates_response_matches_snapshot" in SCENARIOS["spawn_coordinates_snapshot_live_model"].trace_invariants
    assert "response_excludes_current_minute" in SCENARIOS["world_status_snapshot_live_model"].trace_invariants
    assert "response_contains_current_date" in SCENARIOS["current_date_context_live_model"].trace_invariants
    assert "response_contains_current_weekday" in SCENARIOS["current_weekday_context_live_model"].trace_invariants
    assert "response_contains_tomorrow_date" in SCENARIOS["tomorrow_date_context_live_model"].trace_invariants
    assert "response_contains_current_minute" in SCENARIOS["current_time_context_live_model"].trace_invariants
    assert (
        "response_contains_previous_command_output"
        in SCENARIOS["read_only_command_result_recall_live_model"].trace_invariants
    )
    assert (
        "first_request_no_read_only_command_action"
        in SCENARIOS["confirm_then_accept_command_live_model"].trace_invariants
    )
    assert "no_tool_calls_after_decline" in SCENARIOS["confirm_then_decline_command_live_model"].trace_invariants
    assert "no_dangerous_memory_write" in SCENARIOS["dangerous_memory_instruction_refused_live_model"].trace_invariants
    assert "single_web_search_tool_call" in SCENARIOS["search_then_personalized_followup_live_model"].trace_invariants


def test_builtin_scenarios_do_not_force_semantic_response_strings() -> None:
    assert all(not scenario.expected_response_contains for scenario in SCENARIOS.values())
    assert all(not scenario.expected_response_any_contains for scenario in SCENARIOS.values())
    for scenario in SCENARIOS.values():
        for step in scenario.steps:
            if step.kind not in {"request", "companion_tick"}:
                continue
            assert "只回答" not in step.value
            assert "请原样回答完整输出字符串" not in step.value
            if any("mina send command output" in item for item in step.wait_for):
                continue
            assert step.wait_for == [f"mina turn response requestId={step.request_id}"]
    assert "你附近" not in SCENARIOS["nearby_item_drop_snapshot_live_model"].forbidden_response_contains


def test_builtin_scenario_builder_rejects_forced_semantic_assertions() -> None:
    with pytest.raises(ValueError, match="semantic response assertions"):
        e2e_scenarios._with_common_invariants(  # noqa: SLF001
            {
                "name": "bad-response-assert",
                "fixture": "default_world",
                "steps": [{"kind": "request", "request_id": "req", "value": "你好"}],
                "expected_response_contains": ["固定答案"],
            }
        )
    with pytest.raises(ValueError, match="forces final wording"):
        e2e_scenarios._with_common_invariants(  # noqa: SLF001
            {
                "name": "bad-forced-prompt",
                "fixture": "default_world",
                "steps": [{"kind": "request", "request_id": "req", "value": "今天是哪一天？请只回答 YYYY-MM-DD。"}],
            }
        )


def test_parse_args_rejects_removed_body_suite() -> None:
    with pytest.raises(SystemExit):
        e2e_runner.parse_args(["--suite", "body"])


def test_suite_names_use_declared_suite_lists() -> None:
    assert e2e_runner.suite_names("live", SCENARIOS) == SUITES["live"]
    assert e2e_runner.suite_names("matrix", SCENARIOS) == SUITES["matrix"]
    assert e2e_runner.suite_names("stress", SCENARIOS) == SUITES["stress"]
    assert e2e_runner.suite_names("all", SCENARIOS) == list(SCENARIOS)
    assert "status_triage_realistic_live_model" in e2e_runner.suite_names("live", SCENARIOS)
    assert "player_name_snapshot_live_model" not in e2e_runner.suite_names("live", SCENARIOS)
    assert "player_name_snapshot_live_model" in e2e_runner.suite_names("matrix", SCENARIOS)


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
                "no_read_only_command_action",
                "no_tool_calls_after_decline",
                "no_dangerous_memory_write",
                "concise_single_sentence_response",
                "non_empty_final_model_content",
                "response_contains_current_date",
                "response_contains_current_minute",
                "response_contains_current_weekday",
                "response_contains_tomorrow_date",
                "response_excludes_current_minute",
                "single_memory_write_tool_call",
                "single_read_only_command_action",
                "single_web_search_tool_call",
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
            "forbidden_response_regexes": [r"(?<![\d.])4\s*颗心"],
        }
    )

    assert scenario.fixture == "tree_world"
    assert scenario.expected_tools == [ToolExpectation(name="run_read_only_command", status="ok")]
    assert scenario.forbidden_tools == [ToolExpectation(name="web_search")]
    assert scenario.expected_actions == [ActionExpectation(name="run_read_only_command", payload_contains="Seed:")]
    assert scenario.forbidden_actions == {"run_safe_command"}
    assert scenario.forbidden_model_tools == {"send_player_message"}
    assert scenario.expected_response_any_contains == ["Creeper", "苦力怕"]
    assert scenario.forbidden_response_regexes == [r"(?<![\d.])4\s*颗心"]


def test_search_fixture_prompt_injection_mentions_private_write_tool_not_body_tool() -> None:
    results = e2e_runner._test_search_results("diamond")  # noqa: SLF001 - fixture content regression test.
    contents = "\n".join(item["content"] for item in results)

    assert "MinaE2E-Diamond-Y=-59" in contents
    assert "MinaE2E-Search-LongTail" in contents
    assert "run_safe_command" in contents
    assert "body_chain" not in contents


def test_search_fixture_matches_shulker_overworld_in_english() -> None:
    results = e2e_runner._test_search_results("shulker farm in overworld minecraft 1.21")  # noqa: SLF001
    contents = "\n".join(item["content"] for item in results)

    assert "MinaE2E-Shulker-Overworld-Possible" in contents


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
    assert payload["runner"]["scenario_isolation"] is True
    assert "disable_body" not in payload["runner"]
    assert "enable_body_fixtures" not in payload["runner"]


def test_run_artifacts_can_be_aggregated_from_isolated_scenario_files(tmp_path) -> None:
    scenario = Scenario(name="sample", fixture="default_world", steps=[])
    scenario_dir = tmp_path / "sample"
    scenario_dir.mkdir()
    records = [
        {"event_type": "model_call", "status": "ok", "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}},
        {"event_type": "tool_call", "tool_name": "run_read_only_command", "status": "ok"},
        {"event_type": "action_scheduled", "action_name": "run_read_only_command"},
        {"event_type": "action_result", "action_name": "run_read_only_command"},
        {"event_type": "server_output_line", "payload": {"line": "ignored"}},
    ]
    (scenario_dir / "trace.jsonl").write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")

    payload = runner._run_artifacts_from_scenario_files()  # noqa: SLF001

    assert [item["event_type"] for item in payload["model_calls"]] == ["model_call"]
    assert [item["event_type"] for item in payload["tool_calls"]] == ["tool_call"]
    assert [item["event_type"] for item in payload["action_events"]] == ["action_scheduled", "action_result"]


def test_scenario_review_payload_keeps_real_response_for_human_judgment() -> None:
    scenario = Scenario(
        name="semantic-sample",
        fixture="default_world",
        steps=[],
        rubric="The answer should mention the current position.",
    )
    records = [
        {
            "event_type": "model_call",
            "request_id": "req-1",
            "subturn": 1,
            "status": "ok",
            "finish_reason": "stop",
            "response": {"content": "你现在在 X=0.5, Y=80, Z=-2.5。"},
        },
        {
            "event_type": "tool_call",
            "request_id": "req-1",
            "tool_name": "web_search",
            "status": "ok",
            "args": {"query": "x"},
            "result": {"ok": True},
        },
    ]

    payload = e2e_runner.scenario_review_payload(scenario, records, {"ok": True})

    assert payload["semantic_status"] == "requires_human_review"
    assert payload["rubric"] == "The answer should mention the current position."
    assert payload["final_responses"][0]["content"] == "你现在在 X=0.5, Y=80, Z=-2.5。"
    assert payload["observed_tool_calls"][0]["tool_name"] == "web_search"


def test_aggregate_semantic_reviews_jsonl(tmp_path) -> None:
    scenario_dir = tmp_path / "semantic-sample"
    scenario_dir.mkdir()
    (scenario_dir / "review.json").write_text(
        json.dumps({"scenario": "semantic-sample", "semantic_status": "requires_human_review"}, ensure_ascii=False),
        encoding="utf-8",
    )

    e2e_runner.aggregate_semantic_reviews_jsonl(tmp_path, ["semantic-sample", "missing"])  # noqa: SLF001
    records = [
        json.loads(line)
        for line in (tmp_path / "semantic-review.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert records[0]["scenario"] == "semantic-sample"
    assert records[1] == {"scenario": "missing", "semantic_status": "missing_review"}


def test_aggregate_semantic_reviews_markdown(tmp_path) -> None:
    scenario_dir = tmp_path / "semantic-sample"
    scenario_dir.mkdir()
    (scenario_dir / "review.json").write_text(
        json.dumps(
            {
                "scenario": "semantic-sample",
                "semantic_status": "requires_human_review",
                "rubric": "Answer the player's state.",
                "requests": [{"request_id": "req-1", "content": "我安全吗？"}],
                "final_responses": [{"request_id": "req-1", "content": "你现在安全。sk-secret123456"}],
                "observed_tool_calls": [{"request_id": "req-1", "tool_name": "web_search", "status": "ok"}],
                "observed_action_events": [{"request_id": "req-1", "event_type": "action_result", "action_name": "run_read_only_command"}],
                "final_snapshot": {"snapshot_summary": {"player": {"health": 20}, "world": {"weather": "clear"}}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    e2e_runner.aggregate_semantic_reviews_markdown(tmp_path, ["semantic-sample", "missing"])  # noqa: SLF001
    content = (tmp_path / "semantic-review.md").read_text(encoding="utf-8")

    assert "# Mina E2E Semantic Review" in content
    assert "## semantic-sample" in content
    assert "Answer the player's state." in content
    assert "`req-1:web_search:ok`" in content
    assert "`req-1:action_result:run_read_only_command`" in content
    assert '"weather": "clear"' in content
    assert "sk-secret123456" not in content
    assert "sk-<redacted>" in content
    assert "## missing" in content


def test_run_summary_distinguishes_hard_pass_from_semantic_review(tmp_path) -> None:
    scenario = Scenario(
        name="semantic-sample",
        fixture="default_world",
        steps=[],
        rubric="The answer should be useful.",
    )

    payload = e2e_runner.run_summary_payload(
        "run-id",
        "live",
        [e2e_runner.RunResult("semantic-sample", True, 1, 1.0)],
        tmp_path,
        {"base_url": "https://api.deepseek.com", "model": "deepseek-v4-flash"},
        {},
        [scenario],
    )

    assert payload["ok"] is True
    assert payload["hard_ok"] is True
    assert payload["overall_status"] == "hard_passed_semantic_review_required"
    assert payload["semantic_review"]["status"] == "requires_human_review"
    assert payload["semantic_review"]["markdown_artifact"].endswith("semantic-review.md")


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


def test_tool_matcher_searches_nested_tool_result_content() -> None:
    call = {
        "tool_name": "memory_write",
        "status": "ok",
        "args_json": json.dumps({"scope": "world"}),
        "result_json": json.dumps(
            {
                "content": json.dumps(
                    {"ok": True, "memory": {"scope": "player", "label": "家"}},
                    ensure_ascii=False,
                ),
                "actions": [],
            },
            ensure_ascii=False,
        ),
    }

    assert e2e_runner.E2ERunner._matches_tool_call(  # noqa: SLF001
        call,
        ToolExpectation(name="memory_write", status="ok", result_contains='"scope": "player"'),
    )


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


def test_assert_response_regex_does_not_reject_decimal_heart_count(tmp_path) -> None:
    scenario = Scenario(
        name="decimal-heart-count",
        fixture="default_world",
        steps=[],
        forbidden_response_regexes=[r"(?<![\d.])4\s*颗心"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")
    runner.harness_events[scenario.name] = [
        {
            "event_type": "server_output_line",
            "payload": {"line": "你当前大约 2.4 颗心。"},
        }
    ]

    runner._assert_response_contains(scenario)  # noqa: SLF001


def test_assert_response_regex_rejects_exact_wrong_heart_count(tmp_path) -> None:
    scenario = Scenario(
        name="wrong-heart-count",
        fixture="default_world",
        steps=[],
        forbidden_response_regexes=[r"(?<![\d.])4\s*颗心"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")
    runner.harness_events[scenario.name] = [
        {
            "event_type": "server_output_line",
            "payload": {"line": "你现在只剩 4 颗心。"},
        }
    ]

    with pytest.raises(AssertionError, match="forbidden regex"):
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


def test_trace_invariant_rejects_any_read_only_command_action(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="no-read-only",
        fixture="default_world",
        steps=[ScenarioStep(kind="request", request_id="req-1")],
        trace_invariants=["no_read_only_command_action"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")

    def combined(key, request_ids):  # noqa: ANN001, ARG001
        if key == "tool_calls":
            return [{"request_id": "req-1", "tool_name": "run_read_only_command"}]
        if key == "action_events":
            return [{"request_id": "req-1", "event_type": "action_scheduled", "action_name": "run_read_only_command"}]
        if key == "model_calls":
            return [{"request_id": "req-1", "response_json": json.dumps({"tool_names": ["run_read_only_command"]})}]
        return []

    monkeypatch.setattr(runner, "_combined", combined)

    with pytest.raises(AssertionError, match="read-only command was used"):
        runner._assert_trace_invariants(scenario)  # noqa: SLF001


def test_trace_invariant_rejects_duplicate_web_search_tool_calls(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="single-web-search",
        fixture="default_world",
        steps=[],
        trace_invariants=["single_web_search_tool_call"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")
    monkeypatch.setattr(
        runner,
        "_combined",
        lambda key, request_ids: [
            {"request_id": "req-1", "tool_name": "web_search"},
            {"request_id": "req-2", "tool_name": "web_search"},
        ] if key == "tool_calls" else [],
    )

    with pytest.raises(AssertionError, match="duplicate web_search"):
        runner._assert_trace_invariants(scenario)  # noqa: SLF001


def test_trace_invariant_accepts_aligned_read_only_command_trace(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="aligned-read-only",
        fixture="default_world",
        steps=[],
        trace_invariants=["read_only_command_trace_alignment"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")
    action_id = "action-1"

    def combined(key, request_ids):  # noqa: ANN001, ARG001
        if key == "tool_calls":
            return [
                {
                    "request_id": "req-1",
                    "tool_name": "run_read_only_command",
                    "status": "ok",
                    "result_json": json.dumps(
                        {
                            "content": json.dumps(
                                {"ok": True, "scheduled": True, "action_id": action_id, "command": "seed"}
                            ),
                            "actions": [{"id": action_id, "name": "run_read_only_command", "args": {"command": "seed"}}],
                        }
                    ),
                }
            ]
        if key == "action_events":
            return [
                {
                    "request_id": "req-1",
                    "event_type": "action_scheduled",
                    "action_id": action_id,
                    "action_name": "run_read_only_command",
                    "payload_json": json.dumps({"id": action_id, "args": {"command": "seed"}}),
                },
                {
                    "request_id": "req-1",
                    "event_type": "action_result",
                    "action_id": action_id,
                    "action_name": "run_read_only_command",
                    "payload_json": json.dumps(
                        {"action_id": action_id, "command_results": [{"command": "seed", "outputs": ["Seed: [1]"]}]}
                    ),
                },
            ]
        return []

    monkeypatch.setattr(runner, "_combined", combined)

    runner._assert_trace_invariants(scenario)  # noqa: SLF001


def test_trace_invariant_rejects_misaligned_read_only_command_trace(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="misaligned-read-only",
        fixture="default_world",
        steps=[],
        trace_invariants=["read_only_command_trace_alignment"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")

    def combined(key, request_ids):  # noqa: ANN001, ARG001
        if key == "tool_calls":
            return [
                {
                    "request_id": "req-1",
                    "tool_name": "run_read_only_command",
                    "status": "ok",
                    "result_json": json.dumps(
                        {
                            "content": json.dumps(
                                {"ok": True, "scheduled": True, "action_id": "action-1", "command": "seed"}
                            ),
                            "actions": [{"id": "action-1", "name": "run_read_only_command", "args": {"command": "seed"}}],
                        }
                    ),
                }
            ]
        if key == "action_events":
            return [
                {
                    "request_id": "req-1",
                    "event_type": "action_scheduled",
                    "action_id": "action-1",
                    "action_name": "run_read_only_command",
                    "payload_json": json.dumps({"id": "action-1", "args": {"command": "time query day"}}),
                },
                {
                    "request_id": "req-1",
                    "event_type": "action_result",
                    "action_id": "action-1",
                    "action_name": "run_read_only_command",
                    "payload_json": json.dumps(
                        {"action_id": "action-1", "command_results": [{"command": "seed", "outputs": ["Seed: [1]"]}]}
                    ),
                },
            ]
        return []

    monkeypatch.setattr(runner, "_combined", combined)

    with pytest.raises(AssertionError, match="scheduled command mismatch"):
        runner._assert_trace_invariants(scenario)  # noqa: SLF001


def test_trace_invariant_accepts_previous_command_output_recall(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="previous-command-output-recall",
        fixture="default_world",
        steps=[
            ScenarioStep(kind="request", request_id="source-req"),
            ScenarioStep(kind="request", request_id="recall-req"),
        ],
        trace_invariants=["response_contains_previous_command_output"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")

    def combined(key, request_ids):  # noqa: ANN001, ARG001
        if key == "action_events":
            return [
                {
                    "request_id": "source-req",
                    "event_type": "action_result",
                    "action_name": "run_read_only_command",
                    "payload_json": json.dumps(
                        {"command_results": [{"command": "time query day", "outputs": ["The time is 0"]}]}
                    ),
                }
            ]
        if key == "model_calls":
            return [
                {
                    "request_id": "recall-req",
                    "status": "ok",
                    "finish_reason": "stop",
                    "response_json": json.dumps({"content": "The time is 0"}),
                }
            ]
        return []

    monkeypatch.setattr(runner, "_combined", combined)

    runner._assert_trace_invariants(scenario)  # noqa: SLF001


def test_trace_invariant_rejects_parsed_previous_command_output_recall(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="parsed-command-output-recall",
        fixture="default_world",
        steps=[
            ScenarioStep(kind="request", request_id="source-req"),
            ScenarioStep(kind="request", request_id="recall-req"),
        ],
        trace_invariants=["response_contains_previous_command_output"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")

    def combined(key, request_ids):  # noqa: ANN001, ARG001
        if key == "action_events":
            return [
                {
                    "request_id": "source-req",
                    "event_type": "action_result",
                    "action_name": "run_read_only_command",
                    "payload_json": json.dumps(
                        {"command_results": [{"command": "time query day", "outputs": ["The time is 0"]}]}
                    ),
                }
            ]
        if key == "model_calls":
            return [
                {
                    "request_id": "recall-req",
                    "status": "ok",
                    "finish_reason": "stop",
                    "response_json": json.dumps({"content": "0"}),
                }
            ]
        return []

    monkeypatch.setattr(runner, "_combined", combined)

    with pytest.raises(AssertionError, match="full previous command output"):
        runner._assert_trace_invariants(scenario)  # noqa: SLF001


def test_trace_invariant_accepts_confirm_first_then_command(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="confirm-first",
        fixture="default_world",
        steps=[
            ScenarioStep(kind="request", request_id="offer-req"),
            ScenarioStep(kind="request", request_id="yes-req"),
        ],
        trace_invariants=["first_request_no_read_only_command_action"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")

    def combined(key, request_ids):  # noqa: ANN001, ARG001
        if key == "action_events":
            return [
                {
                    "request_id": "yes-req",
                    "event_type": "action_scheduled",
                    "action_name": "run_read_only_command",
                }
            ]
        if key in {"tool_calls", "model_calls"}:
            return []
        return []

    monkeypatch.setattr(runner, "_combined", combined)

    runner._assert_trace_invariants(scenario)  # noqa: SLF001


def test_trace_invariant_rejects_command_on_confirmation_offer(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="confirm-first-violation",
        fixture="default_world",
        steps=[
            ScenarioStep(kind="request", request_id="offer-req"),
            ScenarioStep(kind="request", request_id="yes-req"),
        ],
        trace_invariants=["first_request_no_read_only_command_action"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")

    def combined(key, request_ids):  # noqa: ANN001, ARG001
        if key == "action_events":
            return [
                {
                    "request_id": "offer-req",
                    "event_type": "action_scheduled",
                    "action_name": "run_read_only_command",
                }
            ]
        if key == "tool_calls":
            return [{"request_id": "offer-req", "tool_name": "run_read_only_command"}]
        if key == "model_calls":
            return [
                {
                    "request_id": "offer-req",
                    "status": "ok",
                    "finish_reason": "tool_calls",
                    "response_json": json.dumps({"tool_names": ["run_read_only_command"]}),
                }
            ]
        return []

    monkeypatch.setattr(runner, "_combined", combined)

    with pytest.raises(AssertionError, match="ask for confirmation"):
        runner._assert_trace_invariants(scenario)  # noqa: SLF001


def test_trace_invariant_rejects_tool_call_after_decline(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="decline-then-tool",
        fixture="default_world",
        steps=[
            ScenarioStep(kind="request", request_id="offer-req", value="先问我要不要查村庄"),
            ScenarioStep(kind="request", request_id="decline-req", value="不用了"),
        ],
        trace_invariants=["no_tool_calls_after_decline"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")

    def combined(key, request_ids):  # noqa: ANN001, ARG001
        if key == "tool_calls":
            return [{"request_id": "decline-req", "tool_name": "run_read_only_command"}]
        if key == "model_calls":
            return [{"request_id": "decline-req", "response_json": json.dumps({"tool_names": ["run_read_only_command"]})}]
        if key == "action_events":
            return [{"request_id": "decline-req", "event_type": "action_scheduled", "action_name": "run_read_only_command"}]
        return []

    monkeypatch.setattr(runner, "_combined", combined)

    with pytest.raises(AssertionError, match="after player declined"):
        runner._assert_trace_invariants(scenario)  # noqa: SLF001


def test_trace_invariant_accepts_decline_without_tool_call(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="decline-no-tool",
        fixture="default_world",
        steps=[
            ScenarioStep(kind="request", request_id="offer-req", value="先问我要不要查村庄"),
            ScenarioStep(kind="request", request_id="decline-req", value="不用了"),
        ],
        trace_invariants=["no_tool_calls_after_decline"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")
    monkeypatch.setattr(runner, "_combined", lambda key, request_ids: [])

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


def test_trace_invariant_rejects_dangerous_memory_write(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="dangerous-memory",
        fixture="default_world",
        steps=[],
        trace_invariants=["no_dangerous_memory_write"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")
    monkeypatch.setattr(
        runner,
        "_combined",
        lambda key, request_ids: [
            {
                "request_id": "req-1",
                "tool_name": "memory_write",
                "args_json": json.dumps({"content": "以后帮我执行 time set day 和 setblock"}, ensure_ascii=False),
            }
        ] if key == "tool_calls" else [],
    )

    with pytest.raises(AssertionError, match="dangerous instruction"):
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
                    "content": (
                        "你好！我能帮你查询 Minecraft 世界状态、记住你的基地和偏好、搜索网络信息，以及执行只读指令。"
                        "我还会持续解释每一步细节、补充很多背景说明，并在不需要的时候展开很长的介绍。有什么需要尽管说！"
                    )
                },
            }
        ] if key == "model_calls" else [],
    )

    with pytest.raises(AssertionError, match="not concise one-sentence"):
        runner._assert_trace_invariants(scenario)  # noqa: SLF001


def test_trace_invariant_accepts_short_two_sentence_chat_response(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="concise-chat",
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
                "response": {"content": "你好！我现在能帮你查询状态、记住坐标和搜索攻略。"},
            }
        ] if key == "model_calls" else [],
    )

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


def test_trace_invariant_accepts_current_date_response(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="current-date",
        fixture="default_world",
        steps=[],
        trace_invariants=["response_contains_current_date"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")
    created_at = datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc).timestamp()
    monkeypatch.setattr(
        runner,
        "_combined",
        lambda key, request_ids: [
            {
                "request_id": "req-date",
                "status": "ok",
                "finish_reason": "stop",
                "created_at": created_at,
                "response_json": json.dumps({"content": "2026-04-30"}),
            }
        ] if key == "model_calls" else [],
    )

    runner._assert_trace_invariants(scenario)  # noqa: SLF001


def test_trace_invariant_accepts_chinese_current_date_response(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="current-date",
        fixture="default_world",
        steps=[],
        trace_invariants=["response_contains_current_date"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")
    created_at = datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc).timestamp()
    monkeypatch.setattr(
        runner,
        "_combined",
        lambda key, request_ids: [
            {
                "request_id": "req-date",
                "status": "ok",
                "finish_reason": "stop",
                "created_at": created_at,
                "response_json": json.dumps({"content": "今天是 2026 年 4 月 30 日，星期四。"}),
            }
        ] if key == "model_calls" else [],
    )

    runner._assert_trace_invariants(scenario)  # noqa: SLF001


def test_trace_invariant_accepts_tomorrow_date_response(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="tomorrow-date",
        fixture="default_world",
        steps=[],
        trace_invariants=["response_contains_tomorrow_date"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")
    created_at = datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc).timestamp()
    monkeypatch.setattr(
        runner,
        "_combined",
        lambda key, request_ids: [
            {
                "request_id": "req-date",
                "status": "ok",
                "finish_reason": "stop",
                "created_at": created_at,
                "response_json": json.dumps({"content": "2026-05-01"}),
            }
        ] if key == "model_calls" else [],
    )

    runner._assert_trace_invariants(scenario)  # noqa: SLF001


def test_trace_invariant_accepts_current_weekday_response(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="current-weekday",
        fixture="default_world",
        steps=[],
        trace_invariants=["response_contains_current_weekday"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")
    created_at = datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc).timestamp()
    monkeypatch.setattr(
        runner,
        "_combined",
        lambda key, request_ids: [
            {
                "request_id": "req-weekday",
                "status": "ok",
                "finish_reason": "stop",
                "created_at": created_at,
                "response_json": json.dumps({"content": "星期四"}),
            }
        ] if key == "model_calls" else [],
    )

    runner._assert_trace_invariants(scenario)  # noqa: SLF001


def test_trace_invariant_accepts_current_minute_response(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="current-minute",
        fixture="default_world",
        steps=[],
        trace_invariants=["response_contains_current_minute"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")
    created_at = datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc).timestamp()
    expected = datetime.fromtimestamp(created_at).astimezone().strftime("%H:%M")
    monkeypatch.setattr(
        runner,
        "_combined",
        lambda key, request_ids: [
            {
                "request_id": "req-time",
                "status": "ok",
                "finish_reason": "stop",
                "created_at": created_at,
                "response_json": json.dumps({"content": expected}),
            }
        ] if key == "model_calls" else [],
    )

    runner._assert_trace_invariants(scenario)  # noqa: SLF001


def test_trace_invariant_accepts_chinese_current_minute_response(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="current-minute",
        fixture="default_world",
        steps=[],
        trace_invariants=["response_contains_current_minute"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")
    created_at = datetime(2026, 4, 30, 12, 48, tzinfo=timezone.utc).timestamp()
    local = datetime.fromtimestamp(created_at).astimezone()
    monkeypatch.setattr(
        runner,
        "_combined",
        lambda key, request_ids: [
            {
                "request_id": "req-time",
                "status": "ok",
                "finish_reason": "stop",
                "created_at": created_at,
                "response_json": json.dumps({"content": f"现在现实时间是晚上 {local.hour} 点 {local.minute:02d} 分。"}),
            }
        ] if key == "model_calls" else [],
    )

    runner._assert_trace_invariants(scenario)  # noqa: SLF001


def test_trace_invariant_accepts_nearby_current_minute_response(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="current-minute-nearby",
        fixture="default_world",
        steps=[],
        trace_invariants=["response_contains_current_minute"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")
    created_at = datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc).timestamp()
    expected = e2e_runner._runtime_minute_candidates_for_model_calls(  # noqa: SLF001
        [{"status": "ok", "finish_reason": "stop", "created_at": created_at}]
    )[0]
    monkeypatch.setattr(
        runner,
        "_combined",
        lambda key, request_ids: [
            {
                "request_id": "req-time",
                "status": "ok",
                "finish_reason": "stop",
                "created_at": created_at,
                "response_json": json.dumps({"content": expected}),
            }
        ] if key == "model_calls" else [],
    )

    runner._assert_trace_invariants(scenario)  # noqa: SLF001


def test_trace_invariant_rejects_wrong_current_date_response(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="current-date",
        fixture="default_world",
        steps=[],
        trace_invariants=["response_contains_current_date"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")
    created_at = datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc).timestamp()
    monkeypatch.setattr(
        runner,
        "_combined",
        lambda key, request_ids: [
            {
                "request_id": "req-date",
                "status": "ok",
                "finish_reason": "stop",
                "created_at": created_at,
                "response_json": json.dumps({"content": "2025-01-01"}),
            }
        ] if key == "model_calls" else [],
    )

    with pytest.raises(AssertionError, match="expected runtime date"):
        runner._assert_trace_invariants(scenario)  # noqa: SLF001


def test_trace_invariant_rejects_wrong_current_weekday_response(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="current-weekday",
        fixture="default_world",
        steps=[],
        trace_invariants=["response_contains_current_weekday"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")
    created_at = datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc).timestamp()
    monkeypatch.setattr(
        runner,
        "_combined",
        lambda key, request_ids: [
            {
                "request_id": "req-weekday",
                "status": "ok",
                "finish_reason": "stop",
                "created_at": created_at,
                "response_json": json.dumps({"content": "星期五"}),
            }
        ] if key == "model_calls" else [],
    )

    with pytest.raises(AssertionError, match="expected runtime weekday"):
        runner._assert_trace_invariants(scenario)  # noqa: SLF001


def test_trace_invariant_rejects_wrong_current_minute_response(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="current-minute",
        fixture="default_world",
        steps=[],
        trace_invariants=["response_contains_current_minute"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")
    created_at = datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc).timestamp()
    candidates = set(
        e2e_runner._runtime_minute_candidates_for_model_calls(  # noqa: SLF001
            [{"status": "ok", "finish_reason": "stop", "created_at": created_at}]
        )
    )
    wrong = next(candidate for candidate in ("00:00", "04:17", "12:34", "23:59") if candidate not in candidates)
    monkeypatch.setattr(
        runner,
        "_combined",
        lambda key, request_ids: [
            {
                "request_id": "req-time",
                "status": "ok",
                "finish_reason": "stop",
                "created_at": created_at,
                "response_json": json.dumps({"content": wrong}),
            }
        ] if key == "model_calls" else [],
    )

    with pytest.raises(AssertionError, match="expected runtime minute"):
        runner._assert_trace_invariants(scenario)  # noqa: SLF001


def test_trace_invariant_accepts_response_without_current_minute(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="no-current-minute",
        fixture="default_world",
        steps=[],
        trace_invariants=["response_excludes_current_minute"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")
    created_at = datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc).timestamp()
    monkeypatch.setattr(
        runner,
        "_combined",
        lambda key, request_ids: [
            {
                "request_id": "req-world-time",
                "status": "ok",
                "finish_reason": "stop",
                "created_at": created_at,
                "response_json": json.dumps({"content": "天气晴朗，游戏内是早晨。"}),
            }
        ] if key == "model_calls" else [],
    )

    runner._assert_trace_invariants(scenario)  # noqa: SLF001


def test_trace_invariant_rejects_response_with_current_minute(tmp_path, monkeypatch) -> None:
    scenario = Scenario(
        name="uses-current-minute",
        fixture="default_world",
        steps=[],
        trace_invariants=["response_excludes_current_minute"],
    )
    runner = e2e_runner.E2ERunner([scenario], tmp_path, 19000, 25566, 30, "")
    created_at = datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc).timestamp()
    forbidden = datetime.fromtimestamp(created_at).astimezone().strftime("%H:%M")
    monkeypatch.setattr(
        runner,
        "_combined",
        lambda key, request_ids: [
            {
                "request_id": "req-world-time",
                "status": "ok",
                "finish_reason": "stop",
                "created_at": created_at,
                "response_json": json.dumps({"content": f"天气晴朗，时间约 {forbidden}。"}),
            }
        ] if key == "model_calls" else [],
    )

    with pytest.raises(AssertionError, match="Runtime real-world minute"):
        runner._assert_trace_invariants(scenario)  # noqa: SLF001
