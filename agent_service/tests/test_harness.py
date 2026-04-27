from __future__ import annotations

from mina_agent.harness import _parse_args


def test_parse_args_accepts_deepseek_json_string() -> None:
    raw = '{"x": 10.5, "y": 69, "z": -7.5, "sprint": true, "jump": true}'

    parsed = _parse_args(raw)

    assert parsed == {"x": 10.5, "y": 69, "z": -7.5, "sprint": True, "jump": True}


def test_parse_args_rejects_non_object_json() -> None:
    assert _parse_args("[1, 2, 3]") == {}


def test_parse_args_rejects_invalid_json() -> None:
    assert _parse_args("{bad") == {}
