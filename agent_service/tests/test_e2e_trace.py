from __future__ import annotations

import json

from mina_agent.e2e.trace import compact_summary_action_events, compact_summary_tool_calls, compact_trace_payload


def test_compact_trace_payload_replaces_raw_snapshot_with_hash_and_summary() -> None:
    payload = {
        "status": "success",
        "snapshot": {
            "player_state": {"dimension": "minecraft:overworld", "x": 1, "y": 80, "z": 2, "health": 20, "food": 20},
            "body_state": {
                "online": True,
                "x": 3,
                "y": 80,
                "z": 4,
                "yaw": 90,
                "pitch": 10,
                "distance_to_requester": 2.5,
                "inventory": [{"slot": 0, "item": "minecraft:stone_axe"}],
            },
            "world_state": {"day_time": 1000, "difficulty": "peaceful", "raining": False, "thundering": False},
            "nearby_entities": [{"type": "minecraft:pig"}],
            "nearby_blocks": {"requester": [{"category": "log"}, {"category": "leaves"}]},
        },
    }

    compact = compact_trace_payload(payload)

    assert "snapshot" not in compact
    assert len(compact["snapshot_hash"]) == 16
    assert compact["snapshot_summary"]["body"]["online"] is True
    assert compact["snapshot_summary"]["nearby"]["logs"] == 1
    assert "inventory" not in json.dumps(compact)


def test_trace_summary_compacts_action_event_payload_json() -> None:
    events = [
        {
            "event_type": "action_result",
            "payload_json": json.dumps(
                {
                    "status": "success",
                    "snapshot": {
                        "body_state": {"online": True, "inventory": [{"slot": 0}]},
                        "nearby_blocks": [{"category": "log"}],
                    },
                }
            ),
        }
    ]

    compact = compact_summary_action_events(events)

    assert "payload_json" not in compact[0]
    assert compact[0]["payload"]["snapshot_summary"]["nearby"]["logs"] == 1
    assert "inventory" not in json.dumps(compact)


def test_trace_summary_parses_tool_call_json_fields() -> None:
    calls = [
        {
            "tool_name": "web_search",
            "args_json": '{"query":"Minecraft Wiki"}',
            "result_json": '{"content":"ok"}',
        }
    ]

    compact = compact_summary_tool_calls(calls)

    assert compact[0]["args"] == {"query": "Minecraft Wiki"}
    assert compact[0]["result"] == {"content": "ok"}
    assert "args_json" not in compact[0]
    assert "result_json" not in compact[0]
