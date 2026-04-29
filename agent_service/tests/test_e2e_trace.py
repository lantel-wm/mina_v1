from __future__ import annotations

from mina_agent.e2e.trace import compact_trace_payload, snapshot_summary, trace_records


def test_snapshot_summary_compacts_player_world_and_nearby_blocks_without_body() -> None:
    snapshot = {
        "player_state": {"dimension": "minecraft:overworld", "x": 0.5, "y": 80, "z": -2.5, "health": 20, "food": 20},
        "world_state": {
            "day_time": 1000,
            "difficulty": "peaceful",
            "raining": False,
            "thundering": False,
            "spawn_x": 0,
            "spawn_y": 72,
            "spawn_z": 0,
            "player_distance_from_spawn": 8.54,
        },
        "nearby_entities": [{"type": "minecraft:cow"}],
        "nearby_blocks": {"requester": [{"category": "log"}, {"category": "ore"}]},
    }

    summary = snapshot_summary(snapshot)

    assert summary["player"]["x"] == 0.5
    assert summary["world"]["weather"] == "clear"
    assert summary["world"]["spawn_y"] == 72
    assert summary["world"]["player_distance_from_spawn"] == 8.54
    assert summary["nearby"]["logs"] == 1
    assert "body" not in summary


def test_compact_trace_payload_replaces_snapshot_with_hash_and_summary() -> None:
    compact = compact_trace_payload(
        {
            "snapshot": {
                "player_state": {"x": 1},
                "world_state": {},
                "nearby_blocks": {"requester": [{"category": "log"}]},
            }
        }
    )

    assert "snapshot" not in compact
    assert "snapshot_hash" in compact
    assert compact["snapshot_summary"]["nearby"]["logs"] == 1


def test_trace_records_ignores_removed_task_events() -> None:
    records = trace_records(
        "req-1",
        {
            "task_events": [{"task_id": "task-1", "event_type": "started"}],
            "action_events": [
                {
                    "request_id": "req-1",
                    "action_id": "action-1",
                    "action_name": "run_read_only_command",
                    "event_type": "action_scheduled",
                    "payload_json": "{}",
                    "created_at": 1,
                }
            ],
        },
    )

    assert [record["event_type"] for record in records] == ["action_scheduled"]
