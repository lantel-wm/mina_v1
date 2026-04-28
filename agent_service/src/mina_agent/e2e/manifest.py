from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ToolExpectation:
    name: str
    status: str | None = None
    args_contains: str = ""
    result_contains: str = ""


@dataclass(frozen=True)
class ActionExpectation:
    name: str
    step_id: str = ""
    event_type: str = "action_scheduled"


@dataclass(frozen=True)
class ModelExpectation:
    mode: str
    count: int | None = None
    min_count: int | None = None


@dataclass(frozen=True)
class ScenarioStep:
    kind: str
    value: str = ""
    request_id: str = ""
    wait_for: list[str] = field(default_factory=list)
    timeout: float = 30.0


@dataclass(frozen=True)
class Scenario:
    name: str
    fixture: str
    steps: list[ScenarioStep]
    tags: set[str] = field(default_factory=set)
    timeout: float = 180.0
    retry: int = 0
    expected_tools: list[ToolExpectation] = field(default_factory=list)
    forbidden_tools: list[ToolExpectation] = field(default_factory=list)
    expected_actions: list[ActionExpectation] = field(default_factory=list)
    forbidden_actions: set[str] = field(default_factory=set)
    forbidden_model_tools: set[str] = field(default_factory=set)
    expected_model: ModelExpectation | None = None
    expected_response_contains: list[str] = field(default_factory=list)
    forbidden_response_contains: list[str] = field(default_factory=list)
    world_asserts: list[str] = field(default_factory=list)
    rubric: str = ""
    keep_artifacts: str = "on_failure"

    def request_ids(self) -> list[str]:
        return [step.request_id for step in self.steps if step.request_id]


def scenario_from_dict(payload: dict[str, Any]) -> Scenario:
    return Scenario(
        name=str(payload["name"]),
        fixture=str(payload["fixture"]),
        steps=[
            ScenarioStep(
                kind=str(step["kind"]),
                value=str(step.get("value") or ""),
                request_id=str(step.get("request_id") or ""),
                wait_for=[str(item) for item in step.get("wait_for", [])],
                timeout=float(step.get("timeout", 30.0)),
            )
            for step in payload.get("steps", [])
        ],
        tags={str(item) for item in payload.get("tags", [])},
        timeout=float(payload.get("timeout", 180.0)),
        retry=int(payload.get("retry", 0)),
        expected_tools=[
            ToolExpectation(
                name=str(item["name"]),
                status=str(item["status"]) if item.get("status") is not None else None,
                args_contains=str(item.get("args_contains") or ""),
                result_contains=str(item.get("result_contains") or ""),
            )
            for item in payload.get("expected_tools", [])
        ],
        forbidden_tools=[
            ToolExpectation(
                name=str(item["name"]),
                status=str(item["status"]) if item.get("status") is not None else None,
                args_contains=str(item.get("args_contains") or ""),
                result_contains=str(item.get("result_contains") or ""),
            )
            for item in payload.get("forbidden_tools", [])
        ],
        expected_actions=[
            ActionExpectation(
                name=str(item["name"]),
                step_id=str(item.get("step_id") or ""),
                event_type=str(item.get("event_type") or "action_scheduled"),
            )
            for item in payload.get("expected_actions", [])
        ],
        forbidden_actions={str(item) for item in payload.get("forbidden_actions", [])},
        forbidden_model_tools={str(item) for item in payload.get("forbidden_model_tools", [])},
        expected_model=(
            ModelExpectation(
                mode=str(payload["expected_model"].get("mode") or ""),
                count=payload["expected_model"].get("count"),
                min_count=payload["expected_model"].get("min_count"),
            )
            if isinstance(payload.get("expected_model"), dict)
            else None
        ),
        expected_response_contains=[str(item) for item in payload.get("expected_response_contains", [])],
        forbidden_response_contains=[str(item) for item in payload.get("forbidden_response_contains", [])],
        world_asserts=[str(item) for item in payload.get("world_asserts", [])],
        rubric=str(payload.get("rubric") or ""),
        keep_artifacts=str(payload.get("keep_artifacts") or "on_failure"),
    )


def load_scenarios_from_file(path: Path) -> dict[str, Scenario]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_scenarios = payload.get("scenarios") if isinstance(payload, dict) else payload
    if not isinstance(raw_scenarios, list):
        raise ValueError("E2E manifest must be a scenario list or an object with a scenarios list")
    scenarios = [scenario_from_dict(item) for item in raw_scenarios if isinstance(item, dict)]
    return {scenario.name: scenario for scenario in scenarios}
