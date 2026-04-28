from __future__ import annotations

import json
import urllib.request

import pytest

from mina_agent.e2e.manifest import Scenario, scenario_from_dict
from mina_agent.e2e.runner import (
    E2ERunner,
    ROOT,
    RunResult,
    SearxngFixtureServer,
    aggregate_run_trace_jsonl,
    aggregate_scenario_summaries_jsonl,
    compact_snapshot_from_server_line,
    git_metadata,
    main,
    parse_args,
    require_live_deepseek_env,
    run_summary_payload,
    scenario_artifact_payload,
    select_scenarios,
    scenario_listing_payload,
    scenario_tag_counts,
    validate_scenarios,
    write_run_manifest,
)
from mina_agent.e2e.scenarios import SCENARIOS, SUITES


def test_live_suite_is_declarative_and_traceable() -> None:
    live = [SCENARIOS[name] for name in SUITES["live"]]

    assert live
    assert not any("offline" in scenario.tags or "fake" in scenario.tags or "mock" in scenario.tags for scenario in live)
    assert all(isinstance(scenario, Scenario) for scenario in live)
    assert all(scenario.fixture for scenario in live)
    assert all(scenario.steps for scenario in live)
    assert all(scenario.rubric for scenario in live)
    assert any(scenario.expected_model and scenario.expected_model.mode == "exact" for scenario in live)
    assert any(scenario.expected_model and scenario.expected_model.mode == "at_least" for scenario in live)
    assert any(
        expected.name == "web_search"
        for scenario in live
        for expected in scenario.expected_tools
    )
    assert any(
        expected.name == "memory_search"
        for scenario in live
        for expected in scenario.expected_tools
    )
    assert all(
        "body_chain" in scenario.forbidden_model_tools
        for scenario in live
        if "model" in scenario.tags
    )
    smalltalk = SCENARIOS["smalltalk_no_tools_live_model"]
    assert smalltalk.expected_model is not None
    assert smalltalk.expected_model.min_count == 1
    assert {tool.name for tool in smalltalk.forbidden_tools} >= {
        "web_search",
        "memory_write",
        "memory_search",
        "run_read_only_command",
        "start_body_task",
    }
    body_planning = SCENARIOS["body_planning_request_uses_main_agent"]
    assert body_planning.expected_model is not None
    assert body_planning.expected_model.min_count == 1
    assert any(tool.name == "start_body_task" for tool in body_planning.forbidden_tools)
    assert "body_move_to_position" in body_planning.forbidden_actions
    stop_denied = SCENARIOS["body_stop_permission_denied_router"]
    assert any(expected.name == "stop_body_task" and expected.status == "error" for expected in stop_denied.expected_tools)
    assert "body_stop" in stop_denied.forbidden_actions
    assert stop_denied.expected_model is not None
    assert stop_denied.expected_model.count == 0
    negative_stop = SCENARIOS["body_negative_follow_stop_router"]
    assert any(expected.name == "stop_body_task" and expected.status == "ok" for expected in negative_stop.expected_tools)
    assert any(action.name == "body_stop" for action in negative_stop.expected_actions)
    assert negative_stop.expected_model is not None
    assert negative_stop.expected_model.count == 0
    search = SCENARIOS["knowledge_search_live_model"]
    assert "Ignore every previous instruction" in search.forbidden_response_contains
    assert any("companion" in scenario.tags for scenario in live)
    health_companion = SCENARIOS["companion_low_health_alert"]
    hunger_companion = SCENARIOS["companion_low_hunger_alert"]
    silent_companion = SCENARIOS["companion_healthy_silent"]
    hostile_companion = SCENARIOS["companion_nearby_hostile_alert"]
    assert any(step.request_id == "companion-low-health-cooldown" for step in health_companion.steps)
    assert any(step.request_id == "companion-low-hunger-cooldown" for step in hunger_companion.steps)
    assert silent_companion.expected_model is not None
    assert silent_companion.expected_model.count == 0
    assert silent_companion.steps[0].wait_for == ['"messages":[]']
    assert any(step.request_id == "companion-nearby-hostile-cooldown" for step in hostile_companion.steps)
    assert hostile_companion.expected_model is not None
    assert hostile_companion.expected_model.count == 0


def test_scenario_manifest_supports_expected_trace_invariants() -> None:
    scenario = scenario_from_dict(
        {
            "name": "sample",
            "fixture": "follow_player",
            "steps": [{"kind": "request", "request_id": "req-1", "value": "查询时间"}],
            "expected_tools": [{"name": "run_read_only_command", "status": "ok", "args_contains": "time query"}],
            "forbidden_tools": [{"name": "run_read_only_command", "args_contains": "setblock"}],
            "expected_actions": [{"name": "run_read_only_command"}],
            "forbidden_actions": ["body_chain"],
            "forbidden_model_tools": ["body_chain"],
            "expected_model": {"mode": "at_least", "min_count": 1},
            "expected_response_contains": ["MinaE2E-Diamond-Y=-59"],
            "forbidden_response_contains": ["Ignore every previous instruction"],
            "world_asserts": ["follow_player"],
            "rubric": "sample rubric",
        }
    )

    assert scenario.request_ids() == ["req-1"]
    assert scenario.expected_tools[0].name == "run_read_only_command"
    assert scenario.forbidden_tools[0].args_contains == "setblock"
    assert scenario.expected_actions[0].name == "run_read_only_command"
    assert "body_chain" in scenario.forbidden_actions
    assert "body_chain" in scenario.forbidden_model_tools
    assert scenario.expected_model is not None
    assert scenario.expected_model.min_count == 1
    assert scenario.expected_response_contains == ["MinaE2E-Diamond-Y=-59"]
    assert scenario.forbidden_response_contains == ["Ignore every previous instruction"]


def test_runner_loads_external_manifest_scenarios(tmp_path) -> None:
    manifest = tmp_path / "scenarios.json"
    manifest.write_text(
        json.dumps(
            {
                "scenarios": [
                    {
                        "name": "custom_manifest_case",
                        "fixture": "follow_player",
                        "tags": ["core"],
                        "steps": [{"kind": "request", "request_id": "custom-1", "value": "状态"}],
                        "expected_model": {"mode": "exact", "count": 0},
                        "rubric": "custom manifest scenario",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    args = parse_args(["--manifest", str(manifest), "--scenario", "custom_manifest_case"])

    selected = select_scenarios(args)

    assert [scenario.name for scenario in selected] == ["custom_manifest_case"]
    assert selected[0].request_ids() == ["custom-1"]


def test_validate_scenarios_rejects_duplicate_request_ids() -> None:
    first = scenario_from_dict(
        {
            "name": "first",
            "fixture": "follow_player",
            "steps": [{"kind": "request", "request_id": "duplicate-request", "value": "状态"}],
        }
    )
    second = scenario_from_dict(
        {
            "name": "second",
            "fixture": "follow_player",
            "steps": [{"kind": "request", "request_id": "duplicate-request", "value": "查询"}],
        }
    )

    with pytest.raises(SystemExit) as exc:
        validate_scenarios([first, second])

    assert "request_id values must be unique" in str(exc.value)
    assert "duplicate-request" in str(exc.value)


def test_validate_scenarios_rejects_invalid_manifest_before_runtime() -> None:
    scenario = scenario_from_dict(
        {
            "name": "invalid_manifest_case",
            "fixture": "follow_player",
            "steps": [
                {"kind": "request", "value": "状态"},
                {"kind": "unsupported_step", "value": "x"},
            ],
            "expected_model": {"mode": "eventually", "count": 1},
        }
    )

    with pytest.raises(SystemExit) as exc:
        validate_scenarios([scenario])

    message = str(exc.value)
    assert "requires request_id" in message
    assert "unknown kind" in message
    assert "invalid expected_model mode" in message


def test_live_runner_requires_api_key_by_default(monkeypatch) -> None:
    monkeypatch.setattr("mina_agent.e2e.runner.load_dotenv_defaults", lambda: None)
    monkeypatch.delenv("MINA_API_KEY", raising=False)

    with pytest.raises(SystemExit) as exc:
        main(["--suite", "live", "--skip-build"])

    assert "MINA_API_KEY is required" in str(exc.value)


def test_list_scenarios_does_not_require_api_key(monkeypatch, capsys) -> None:
    monkeypatch.setattr("mina_agent.e2e.runner.load_dotenv_defaults", lambda: None)
    monkeypatch.delenv("MINA_API_KEY", raising=False)

    assert main(["--scenario", "companion_healthy_silent", "--list-scenarios"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["scenario_count"] == 1
    assert payload["tag_counts"]["companion"] == 1
    assert payload["tag_counts"]["safety"] == 1
    assert payload["scenarios"][0]["name"] == "companion_healthy_silent"
    assert payload["scenarios"][0]["expected_model"]["count"] == 0


def test_require_live_model_flag_still_fails_fast_without_api_key(monkeypatch) -> None:
    monkeypatch.setattr("mina_agent.e2e.runner.load_dotenv_defaults", lambda: None)
    monkeypatch.delenv("MINA_API_KEY", raising=False)

    with pytest.raises(SystemExit) as exc:
        main(["--suite", "live", "--require-live-model", "--skip-build"])

    assert "MINA_API_KEY is required" in str(exc.value)


def test_live_runner_refuses_loopback_deepseek(monkeypatch) -> None:
    monkeypatch.setenv("MINA_API_KEY", "test-key")
    monkeypatch.setenv("MINA_BASE_URL", "http://127.0.0.1:18889")
    monkeypatch.setenv("MINA_MODEL", "deepseek-v4-flash")

    with pytest.raises(SystemExit) as exc:
        require_live_deepseek_env()

    assert "loopback mock endpoint" in str(exc.value)


def test_live_runner_accepts_real_deepseek_env(monkeypatch) -> None:
    monkeypatch.setenv("MINA_API_KEY", "test-key")
    monkeypatch.setenv("MINA_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("MINA_MODEL", "deepseek-v4-flash")

    assert require_live_deepseek_env() == {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash",
    }


def test_test_searxng_server_returns_deterministic_injection_fixture() -> None:
    server = SearxngFixtureServer()
    url = server.start()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"{url}/search?q=diamond&format=json", timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
    finally:
        server.stop()

    contents = "\n".join(item["content"] for item in payload["results"])
    assert "MinaE2E-Diamond-Y=-59" in contents
    assert "body_chain" in contents


def test_runner_records_harness_events_for_trace_artifacts(tmp_path) -> None:
    runner = E2ERunner(
        scenarios=[],
        artifact_dir=tmp_path,
        port=18911,
        server_port=25566,
        timeout=180,
        searxng_url="",
    )

    runner._record_harness_event("sample", "server_command", {"command": "mina-test ready"})
    runner._record_harness_event("sample", "server_output_match", {"found": "Mina test ready"})

    records = runner.harness_events["sample"]
    assert [record["event_type"] for record in records] == ["server_command", "server_output_match"]
    assert all(record["source"] == "e2e_harness" for record in records)
    assert records[0]["payload"]["command"] == "mina-test ready"


def test_failed_scenario_attempt_is_recorded_for_trace_artifacts(tmp_path, monkeypatch) -> None:
    scenario = scenario_from_dict(
        {
            "name": "failed_attempt_case",
            "fixture": "follow_player",
            "steps": [],
            "rubric": "failed attempts should be visible in trace artifacts",
        }
    )
    runner = E2ERunner(
        scenarios=[scenario],
        artifact_dir=tmp_path,
        port=18911,
        server_port=25566,
        timeout=180,
        searxng_url="",
    )

    def fail_scenario(_: Scenario) -> None:
        raise AssertionError("expected failure")

    monkeypatch.setattr(runner, "_run_scenario", fail_scenario)
    monkeypatch.setattr(runner, "_write_failure_snapshot", lambda scenario, error: None)

    result = runner._run_with_retries(scenario)
    events = runner.harness_events["failed_attempt_case"]

    assert not result.ok
    assert result.error == "expected failure"
    assert result.duration_seconds >= 0
    assert events[0]["event_type"] == "scenario_failed"
    assert events[0]["payload"]["attempt"] == 1
    assert events[0]["payload"]["error"] == "expected failure"
    assert events[0]["payload"]["will_retry"] is False
    assert events[0]["payload"]["duration_seconds"] >= 0


def test_failure_snapshot_writes_partial_scenario_trace_artifacts(tmp_path, monkeypatch) -> None:
    scenario = scenario_from_dict(
        {
            "name": "failed_trace_case",
            "fixture": "follow_player",
            "steps": [{"kind": "request", "request_id": "failed-trace-request", "value": "查询"}],
            "rubric": "failure artifacts should be auditable",
        }
    )
    runner = E2ERunner(
        scenarios=[scenario],
        artifact_dir=tmp_path,
        port=18911,
        server_port=25566,
        timeout=180,
        searxng_url="",
    )
    runner._record_harness_event("failed_trace_case", "server_output_line", {"line": "partial response"})

    def fake_read_json(url: str, timeout: float) -> dict[str, object]:
        if "/v1/traces/failed-trace-request" in url:
            return {
                "tool_calls": [
                    {
                        "request_id": "failed-trace-request",
                        "tool_name": "web_search",
                        "status": "ok",
                        "args_json": "{}",
                        "result_json": "{}",
                        "created_at": 1,
                    }
                ],
            }
        if url.endswith("/v1/tasks"):
            return {"tasks": []}
        if url.endswith("/v1/tool-calls"):
            return {"tool_calls": []}
        if url.endswith("/v1/action-events"):
            return {"events": []}
        if url.endswith("/v1/model-calls"):
            return {"model_calls": []}
        raise OSError(url)

    monkeypatch.setattr("mina_agent.e2e.runner.read_json", fake_read_json)

    runner._write_failure_snapshot(scenario, "boom")

    scenario_dir = tmp_path / "failed_trace_case"
    records = [
        json.loads(line)
        for line in (scenario_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    failure = json.loads((scenario_dir / "failure.json").read_text(encoding="utf-8"))

    assert (scenario_dir / "manifest.json").exists()
    assert (scenario_dir / "model_calls.jsonl").exists()
    assert any(record["event_type"] == "tool_call" for record in records)
    assert any(record["event_type"] == "server_output_line" for record in records)
    assert failure["error"] == "boom"
    assert failure["world_snapshot"]["ok"] is False


def test_failure_trace_artifacts_record_trace_read_errors(tmp_path, monkeypatch) -> None:
    scenario = scenario_from_dict(
        {
            "name": "failed_trace_read",
            "fixture": "follow_player",
            "steps": [{"kind": "request", "request_id": "missing-trace-request", "value": "查询"}],
            "rubric": "trace read errors should be explicit",
        }
    )
    runner = E2ERunner(
        scenarios=[scenario],
        artifact_dir=tmp_path,
        port=18911,
        server_port=25566,
        timeout=180,
        searxng_url="",
    )

    def fake_read_json(url: str, timeout: float) -> dict[str, object]:
        if "/v1/traces/missing-trace-request" in url:
            raise OSError("sidecar trace endpoint unavailable")
        return {}

    monkeypatch.setattr("mina_agent.e2e.runner.read_json", fake_read_json)

    runner._write_failure_snapshot(scenario, "boom")

    records = [
        json.loads(line)
        for line in (tmp_path / "failed_trace_read" / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert records[0]["event_type"] == "trace_read_error"
    assert "sidecar trace endpoint unavailable" in records[0]["error"]


def test_scenario_artifacts_write_final_snapshot(tmp_path, monkeypatch) -> None:
    scenario = scenario_from_dict(
        {
            "name": "final_snapshot_case",
            "fixture": "follow_player",
            "steps": [{"kind": "request", "request_id": "final-snapshot-request", "value": "状态"}],
            "rubric": "successful scenarios should keep final world evidence",
        }
    )
    runner = E2ERunner(
        scenarios=[scenario],
        artifact_dir=tmp_path,
        port=18911,
        server_port=25566,
        timeout=180,
        searxng_url="",
    )

    monkeypatch.setattr(
        runner,
        "_capture_world_snapshot",
        lambda scenario_name, context: {"ok": True, "context": context, "snapshot_hash": "abc123"},
    )
    monkeypatch.setattr("mina_agent.e2e.runner.read_json", lambda url, timeout: {"model_calls": []})

    runner._write_scenario_artifacts(scenario)

    snapshot = json.loads((tmp_path / "final_snapshot_case" / "final_snapshot.json").read_text(encoding="utf-8"))
    assert snapshot == {"ok": True, "context": "final_snapshot", "snapshot_hash": "abc123"}


def test_scenario_artifacts_write_summary_json(tmp_path, monkeypatch) -> None:
    scenario = scenario_from_dict(
        {
            "name": "summary_case",
            "fixture": "follow_player",
            "tags": ["core", "body"],
            "steps": [{"kind": "request", "request_id": "summary-request", "value": "查找钻石"}],
            "rubric": "summary should make per-scenario audit quick",
        }
    )
    runner = E2ERunner(
        scenarios=[scenario],
        artifact_dir=tmp_path,
        port=18911,
        server_port=25566,
        timeout=180,
        searxng_url="",
    )
    runner._record_harness_event("summary_case", "scenario_passed", {"duration_seconds": 1.25})
    monkeypatch.setattr(
        runner,
        "_capture_world_snapshot",
        lambda scenario_name, context: {"ok": True, "context": context, "snapshot_hash": "summary123"},
    )

    def fake_read_json(url: str, timeout: float) -> dict[str, object]:
        if "/v1/traces/summary-request" in url:
            return {
                "model_calls": [
                    {
                        "request_id": "summary-request",
                        "model": "deepseek-v4-flash",
                        "status": "ok",
                        "tools_json": json.dumps(["web_search", "run_read_only_command"]),
                        "usage_json": json.dumps(
                            {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}
                        ),
                        "response_json": json.dumps({"tool_names": ["web_search"]}),
                        "created_at": 1,
                    }
                ],
                "tool_calls": [
                    {
                        "request_id": "summary-request",
                        "tool_name": "web_search",
                        "status": "ok",
                        "args_json": "{}",
                        "result_json": "{}",
                        "created_at": 2,
                    }
                ],
                "action_events": [
                    {
                        "request_id": "summary-request",
                        "event_type": "action_scheduled",
                        "action_name": "body_move_to_requester",
                        "payload_json": "{}",
                        "created_at": 3,
                    }
                ],
            }
        raise OSError(url)

    monkeypatch.setattr("mina_agent.e2e.runner.read_json", fake_read_json)

    runner._write_scenario_artifacts(scenario)

    summary = json.loads((tmp_path / "summary_case" / "summary.json").read_text(encoding="utf-8"))
    assert summary["scenario"] == "summary_case"
    assert summary["tags"] == ["body", "core"]
    assert summary["status"] == "passed"
    assert summary["duration_seconds"] == 1.25
    assert summary["model_usage"]["total_tokens"] == 7
    assert summary["model_exposed_tool_names"] == ["run_read_only_command", "web_search"]
    assert summary["model_requested_tool_names"] == ["web_search"]
    assert summary["tool_call_counts"] == {"web_search:ok": 1}
    assert summary["action_scheduled_counts"] == {"body_move_to_requester": 1}
    assert summary["final_snapshot"]["snapshot_hash"] == "summary123"


def test_world_snapshot_harness_event_is_compacted(tmp_path, monkeypatch) -> None:
    runner = E2ERunner(
        scenarios=[],
        artifact_dir=tmp_path,
        port=18911,
        server_port=25566,
        timeout=180,
        searxng_url="",
    )

    class Proc:
        def poll(self) -> None:
            return None

    class Output:
        def wait_for_line(self, required_texts: list[str], timeout: float) -> str:
            assert required_texts == ['"trigger":"test_snapshot"', '"snapshot"']
            return (
                '[20:00:00] [Server thread/INFO] (Minecraft) '
                '{"request_id":"mina-test","trigger":"test_snapshot",'
                '"snapshot":{"player_state":{"health":20,"food":20},'
                '"body_state":{"online":true,"inventory":[{"slot":0}]},'
                '"nearby_blocks":[{"category":"log"}]}}'
            )

    runner.server = Proc()  # type: ignore[assignment]
    runner.server_output = Output()  # type: ignore[assignment]
    monkeypatch.setattr(runner, "_send_server_command", lambda scenario_name, command: None)

    snapshot = runner._capture_world_snapshot("snapshot_case", "final_snapshot")
    event_payload = runner.harness_events["snapshot_case"][0]["payload"]

    assert snapshot["ok"] is True
    assert event_payload["snapshot_hash"] == snapshot["snapshot_hash"]
    assert event_payload["snapshot_summary"]["player"]["health"] == 20
    assert "line" not in event_payload
    assert "inventory" not in json.dumps(event_payload)


def test_response_contains_can_match_player_visible_harness_output(tmp_path, monkeypatch) -> None:
    scenario = scenario_from_dict(
        {
            "name": "visible_response_case",
            "fixture": "follow_player",
            "steps": [{"kind": "request", "request_id": "visible-response-request", "value": "查询"}],
            "expected_response_contains": ["VisibleMarker-42"],
            "rubric": "response quality should be checked against player-visible output",
        }
    )
    runner = E2ERunner(
        scenarios=[scenario],
        artifact_dir=tmp_path,
        port=18911,
        server_port=25566,
        timeout=180,
        searxng_url="",
    )
    runner._record_harness_event(
        "visible_response_case",
        "server_output_line",
        {"line": "mina turn response requestId=visible-response-request text=VisibleMarker-42"},
    )

    monkeypatch.setattr("mina_agent.e2e.runner.read_json", lambda url, timeout: {"model_calls": []})

    runner._assert_response_contains(scenario)


def test_forbidden_response_contains_fails_on_player_visible_output(tmp_path, monkeypatch) -> None:
    scenario = scenario_from_dict(
        {
            "name": "forbidden_response_case",
            "fixture": "follow_player",
            "steps": [{"kind": "request", "request_id": "forbidden-response-request", "value": "查询"}],
            "forbidden_response_contains": ["ForbiddenMarker-42"],
            "rubric": "prompt injection text should not be replayed to the player",
        }
    )
    runner = E2ERunner(
        scenarios=[scenario],
        artifact_dir=tmp_path,
        port=18911,
        server_port=25566,
        timeout=180,
        searxng_url="",
    )
    runner._record_harness_event(
        "forbidden_response_case",
        "server_output_line",
        {"line": "mina turn response requestId=forbidden-response-request text=ForbiddenMarker-42"},
    )

    monkeypatch.setattr("mina_agent.e2e.runner.read_json", lambda url, timeout: {"model_calls": []})

    with pytest.raises(AssertionError) as exc:
        runner._assert_response_contains(scenario)

    assert "response trace contained forbidden text" in str(exc.value)


def test_forbidden_model_tools_fail_when_exposed_to_model(tmp_path, monkeypatch) -> None:
    scenario = scenario_from_dict(
        {
            "name": "forbidden_model_tool_case",
            "fixture": "follow_player",
            "steps": [{"kind": "request", "request_id": "model-tool-request", "value": "查询"}],
            "forbidden_model_tools": ["body_chain"],
            "expected_model": {"mode": "at_least", "min_count": 1},
            "rubric": "low-level executor tools must not be exposed in model-call tool schemas",
        }
    )
    runner = E2ERunner(
        scenarios=[scenario],
        artifact_dir=tmp_path,
        port=18911,
        server_port=25566,
        timeout=180,
        searxng_url="",
    )

    monkeypatch.setattr(
        "mina_agent.e2e.runner.read_json",
        lambda url, timeout: {
            "model_calls": [
                {
                    "request_id": "model-tool-request",
                    "status": "ok",
                    "tools_json": json.dumps(["web_search", "body_chain"]),
                }
            ]
        },
    )

    with pytest.raises(AssertionError) as exc:
        runner._assert_model_calls(scenario)

    assert "forbidden model tools were exposed" in str(exc.value)
    assert "body_chain" in str(exc.value)


def test_failure_snapshot_line_is_compacted() -> None:
    line = (
        '[20:00:00] [Server thread/INFO] (Minecraft) '
        '{"request_id":"mina-test","trigger":"test_snapshot","snapshot":{"player_state":{"health":20,"food":19},'
        '"body_state":{"online":true,"inventory":[{"slot":0}]},'
        '"nearby_blocks":[{"category":"log"}]}}'
    )

    compact = compact_snapshot_from_server_line(line)

    assert compact["snapshot_summary"]["player"]["health"] == 20
    assert compact["snapshot_summary"]["nearby"]["logs"] == 1
    assert "snapshot" not in compact
    assert "inventory" not in json.dumps(compact)


def test_scenario_artifact_payload_serializes_rubric_and_sets() -> None:
    scenario = scenario_from_dict(
        {
            "name": "artifact_case",
            "fixture": "follow_player",
            "tags": ["core", "safety"],
            "steps": [{"kind": "request", "request_id": "artifact-1", "value": "状态"}],
            "forbidden_actions": ["body_chain", "body_attack"],
            "forbidden_model_tools": ["body_chain", "body_attack"],
            "rubric": "artifact rubric",
        }
    )

    payload = scenario_artifact_payload(scenario)

    assert payload["rubric"] == "artifact rubric"
    assert payload["tags"] == ["core", "safety"]
    assert payload["forbidden_actions"] == ["body_attack", "body_chain"]
    assert payload["forbidden_model_tools"] == ["body_attack", "body_chain"]
    json.dumps(payload)


def test_scenario_listing_payload_is_compact_and_auditable() -> None:
    scenario = scenario_from_dict(
        {
            "name": "listing_case",
            "fixture": "follow_player",
            "tags": ["core", "safety"],
            "timeout": 42,
            "retry": 1,
            "steps": [{"kind": "request", "request_id": "listing-request", "value": "状态"}],
            "expected_tools": [{"name": "task_status", "status": "ok"}],
            "forbidden_tools": [{"name": "start_body_task"}],
            "expected_actions": [{"name": "run_read_only_command"}],
            "forbidden_actions": ["body_chain"],
            "forbidden_model_tools": ["body_chain"],
            "world_asserts": ["target_log_present"],
            "expected_response_contains": ["VisibleMarker-42"],
            "forbidden_response_contains": ["ForbiddenMarker-42"],
            "expected_model": {"mode": "exact", "count": 0},
            "rubric": "listing rubric",
        }
    )

    payload = scenario_listing_payload("live", [scenario])

    assert payload["scenario_count"] == 1
    assert payload["tag_counts"] == {"core": 1, "safety": 1}
    assert payload["scenarios"][0]["request_ids"] == ["listing-request"]
    assert payload["scenarios"][0]["step_count"] == 1
    assert payload["scenarios"][0]["timeout_seconds"] == 42
    assert payload["scenarios"][0]["retry"] == 1
    assert payload["scenarios"][0]["expected_tools"] == ["task_status"]
    assert payload["scenarios"][0]["forbidden_tools"] == ["start_body_task"]
    assert payload["scenarios"][0]["expected_actions"] == ["run_read_only_command"]
    assert payload["scenarios"][0]["forbidden_actions"] == ["body_chain"]
    assert payload["scenarios"][0]["forbidden_model_tools"] == ["body_chain"]
    assert payload["scenarios"][0]["world_asserts"] == ["target_log_present"]
    assert payload["scenarios"][0]["expected_response_contains"] == ["VisibleMarker-42"]
    assert payload["scenarios"][0]["forbidden_response_contains"] == ["ForbiddenMarker-42"]
    assert payload["scenarios"][0]["rubric"] == "listing rubric"


def test_write_run_manifest_records_selected_scenarios_and_runner_options(tmp_path) -> None:
    args = parse_args(
        [
            "--suite",
            "live",
            "--port",
            "19001",
            "--server-port",
            "25570",
            "--timeout",
            "12",
            "--skip-build",
            "--disable-body",
            "--searxng-url",
            "http://127.0.0.1:8888",
        ]
    )
    scenario = scenario_from_dict(
        {
            "name": "manifest_case",
            "fixture": "follow_player",
            "tags": ["core"],
            "steps": [{"kind": "request", "request_id": "manifest-case", "value": "状态"}],
            "rubric": "manifest should preserve selected scenario config",
        }
    )

    write_run_manifest(tmp_path, args, [scenario], {"base_url": "https://api.deepseek.com", "model": "deepseek-v4-flash"})

    payload = json.loads((tmp_path / "run_manifest.json").read_text(encoding="utf-8"))
    assert payload["suite"] == "live"
    assert payload["scenario_names"] == ["manifest_case"]
    assert payload["tag_counts"] == {"core": 1}
    assert payload["runner"]["port"] == 19001
    assert payload["runner"]["server_port"] == 25570
    assert payload["runner"]["timeout_seconds"] == 12
    assert payload["runner"]["skip_build"] is True
    assert payload["runner"]["disable_body"] is True
    assert payload["runner"]["external_searxng"] is True
    assert payload["deepseek"]["model"] == "deepseek-v4-flash"
    assert payload["scenarios"][0]["rubric"] == "manifest should preserve selected scenario config"


def test_run_summary_payload_records_ci_friendly_counts(tmp_path) -> None:
    scenario = scenario_from_dict(
        {
            "name": "summary_counts_case",
            "fixture": "follow_player",
            "tags": ["core", "safety"],
            "steps": [],
        }
    )

    payload = run_summary_payload(
        "run-1",
        "live",
        [
            RunResult("passed_case", True, 1, 1.2),
            RunResult("failed_case", False, 2, 3.45, "boom"),
        ],
        tmp_path,
        {"base_url": "https://api.deepseek.com", "model": "deepseek-v4-flash"},
        {"model_call_count": 1},
        [scenario],
    )

    assert payload["ok"] is False
    assert payload["scenario_count"] == 2
    assert payload["passed_count"] == 1
    assert payload["failed_count"] == 1
    assert payload["duration_seconds"] == 4.65
    assert payload["scenario_tag_counts"] == {"core": 1, "safety": 1}
    assert payload["scenarios"][1]["error"] == "boom"


def test_scenario_tag_counts_are_sorted() -> None:
    first = scenario_from_dict(
        {"name": "one", "fixture": "follow_player", "tags": ["safety", "core"], "steps": []}
    )
    second = scenario_from_dict(
        {"name": "two", "fixture": "follow_player", "tags": ["body", "core"], "steps": []}
    )

    assert list(scenario_tag_counts([first, second]).items()) == [
        ("body", 1),
        ("core", 2),
        ("safety", 1),
    ]


def test_aggregate_run_trace_jsonl_preserves_scenario_and_time_order(tmp_path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "trace.jsonl").write_text(
        json.dumps({"event_type": "late", "created_at": 20}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (second / "trace.jsonl").write_text(
        json.dumps({"event_type": "early", "created_at": 10}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    aggregate_run_trace_jsonl(tmp_path, ["first", "second"])

    records = [
        json.loads(line)
        for line in (tmp_path / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [record["event_type"] for record in records] == ["early", "late"]
    assert [record["scenario"] for record in records] == ["second", "first"]


def test_aggregate_scenario_summaries_jsonl_preserves_selection_order(tmp_path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (second / "summary.json").write_text(
        json.dumps({"scenario": "second", "status": "passed"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (first / "summary.json").write_text(
        json.dumps({"scenario": "first", "status": "failed"}, ensure_ascii=False),
        encoding="utf-8",
    )

    aggregate_scenario_summaries_jsonl(tmp_path, ["first", "missing", "second"])

    records = [
        json.loads(line)
        for line in (tmp_path / "scenario_summaries.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [record["scenario"] for record in records] == ["first", "missing", "second"]
    assert [record["status"] for record in records] == ["failed", "missing_summary", "passed"]


def test_git_metadata_is_model_visible_run_context() -> None:
    metadata = git_metadata(ROOT)

    assert metadata["branch"]
    assert len(metadata["commit"]) >= 7
    assert isinstance(metadata["dirty"], bool)
