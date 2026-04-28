from __future__ import annotations

import json
import urllib.request

import pytest

from mina_agent.e2e.manifest import Scenario, scenario_from_dict
from mina_agent.e2e.runner import (
    E2ERunner,
    ROOT,
    SearxngFixtureServer,
    aggregate_run_trace_jsonl,
    compact_snapshot_from_server_line,
    git_metadata,
    main,
    parse_args,
    require_live_deepseek_env,
    scenario_artifact_payload,
    select_scenarios,
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
    assert any("companion" in scenario.tags for scenario in live)
    health_companion = SCENARIOS["companion_low_health_alert"]
    hunger_companion = SCENARIOS["companion_low_hunger_alert"]
    silent_companion = SCENARIOS["companion_healthy_silent"]
    assert any(step.request_id == "companion-low-health-cooldown" for step in health_companion.steps)
    assert any(step.request_id == "companion-low-hunger-cooldown" for step in hunger_companion.steps)
    assert silent_companion.expected_model is not None
    assert silent_companion.expected_model.count == 0
    assert silent_companion.steps[0].wait_for == ['"messages":[]']


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
            "expected_model": {"mode": "at_least", "min_count": 1},
            "expected_response_contains": ["MinaE2E-Diamond-Y=-59"],
            "world_asserts": ["follow_player"],
            "rubric": "sample rubric",
        }
    )

    assert scenario.request_ids() == ["req-1"]
    assert scenario.expected_tools[0].name == "run_read_only_command"
    assert scenario.forbidden_tools[0].args_contains == "setblock"
    assert scenario.expected_actions[0].name == "run_read_only_command"
    assert "body_chain" in scenario.forbidden_actions
    assert scenario.expected_model is not None
    assert scenario.expected_model.min_count == 1
    assert scenario.expected_response_contains == ["MinaE2E-Diamond-Y=-59"]


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


def test_live_runner_requires_api_key_by_default(monkeypatch) -> None:
    monkeypatch.setattr("mina_agent.e2e.runner.load_dotenv_defaults", lambda: None)
    monkeypatch.delenv("MINA_API_KEY", raising=False)

    with pytest.raises(SystemExit) as exc:
        main(["--suite", "live", "--skip-build"])

    assert "MINA_API_KEY is required" in str(exc.value)


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
    assert events[0]["event_type"] == "scenario_failed"
    assert events[0]["payload"] == {"attempt": 1, "error": "expected failure", "will_retry": False}


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


def test_failure_snapshot_line_is_compacted() -> None:
    line = (
        '[20:00:00] [Server thread/INFO] (Minecraft) '
        '{"request_id":"test_snapshot","snapshot":{"player_state":{"health":20,"food":19},'
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
            "rubric": "artifact rubric",
        }
    )

    payload = scenario_artifact_payload(scenario)

    assert payload["rubric"] == "artifact rubric"
    assert payload["tags"] == ["core", "safety"]
    assert payload["forbidden_actions"] == ["body_attack", "body_chain"]
    json.dumps(payload)


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
    assert payload["runner"]["port"] == 19001
    assert payload["runner"]["server_port"] == 25570
    assert payload["runner"]["timeout_seconds"] == 12
    assert payload["runner"]["skip_build"] is True
    assert payload["runner"]["disable_body"] is True
    assert payload["runner"]["external_searxng"] is True
    assert payload["deepseek"]["model"] == "deepseek-v4-flash"
    assert payload["scenarios"][0]["rubric"] == "manifest should preserve selected scenario config"


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


def test_git_metadata_is_model_visible_run_context() -> None:
    metadata = git_metadata(ROOT)

    assert metadata["branch"]
    assert len(metadata["commit"]) >= 7
    assert isinstance(metadata["dirty"], bool)
