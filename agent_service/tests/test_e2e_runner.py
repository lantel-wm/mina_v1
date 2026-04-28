from __future__ import annotations

import json
import urllib.request

import pytest

from mina_agent.e2e.manifest import Scenario, scenario_from_dict
from mina_agent.e2e.runner import SearxngFixtureServer, main, require_live_deepseek_env
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


def test_live_runner_requires_api_key_by_default(monkeypatch) -> None:
    monkeypatch.setattr("mina_agent.e2e.runner.load_dotenv_defaults", lambda: None)
    monkeypatch.delenv("MINA_API_KEY", raising=False)

    with pytest.raises(SystemExit) as exc:
        main(["--suite", "live", "--skip-build"])

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
