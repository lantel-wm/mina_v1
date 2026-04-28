from __future__ import annotations

import json
import urllib.request

import pytest

from mina_agent.e2e.manifest import Scenario, scenario_from_dict
from mina_agent.e2e.runner import (
    E2ERunner,
    SearxngFixtureServer,
    main,
    parse_args,
    require_live_deepseek_env,
    select_scenarios,
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
