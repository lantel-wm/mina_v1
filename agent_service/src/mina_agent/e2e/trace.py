from __future__ import annotations

import hashlib
import json
from typing import Any


def compact_trace_payload(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    compact = dict(payload)
    snapshot = compact.pop("snapshot", None)
    if isinstance(snapshot, dict):
        compact["snapshot_hash"] = snapshot_hash(snapshot)
        compact["snapshot_summary"] = snapshot_summary(snapshot)
    return compact


def trace_records(trace_id: str, trace: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for call in trace.get("model_calls") or []:
        if not isinstance(call, dict):
            continue
        records.append(
            {
                "trace_id": trace_id,
                "request_id": call.get("request_id"),
                "event_type": "model_call",
                "subturn": call.get("subturn"),
                "model": call.get("model"),
                "status": call.get("status"),
                "finish_reason": call.get("finish_reason"),
                "tools": parse_json_field(call.get("tools_json")),
                "usage": parse_json_field(call.get("usage_json")),
                "response": parse_json_field(call.get("response_json")),
                "error": call.get("error"),
                "created_at": call.get("created_at"),
            }
        )
    for call in trace.get("tool_calls") or []:
        if not isinstance(call, dict):
            continue
        records.append(
            {
                "trace_id": trace_id,
                "request_id": call.get("request_id"),
                "event_type": "tool_call",
                "tool_name": call.get("tool_name"),
                "status": call.get("status"),
                "args": parse_json_field(call.get("args_json")),
                "result": parse_json_field(call.get("result_json")),
                "created_at": call.get("created_at"),
            }
        )
    for event in trace.get("action_events") or []:
        if not isinstance(event, dict):
            continue
        records.append(
            {
                "trace_id": trace_id,
                "request_id": event.get("request_id"),
                "task_id": event.get("task_id"),
                "step_id": event.get("step_id"),
                "action_id": event.get("action_id"),
                "action_name": event.get("action_name"),
                "event_type": event.get("event_type"),
                "payload": compact_trace_payload(parse_json_field(event.get("payload_json"))),
                "created_at": event.get("created_at"),
            }
        )
    records.sort(key=lambda item: float(item.get("created_at") or 0))
    return records


def compact_summary_action_events(events: Any) -> list[dict[str, Any]]:
    compact_events: list[dict[str, Any]] = []
    if not isinstance(events, list):
        return compact_events
    for event in events:
        if not isinstance(event, dict):
            continue
        compact = dict(event)
        payload = compact.pop("payload_json", None)
        compact["payload"] = compact_trace_payload(parse_json_field(payload))
        compact_events.append(compact)
    return compact_events


def compact_summary_tool_calls(calls: Any) -> list[dict[str, Any]]:
    compact_calls: list[dict[str, Any]] = []
    if not isinstance(calls, list):
        return compact_calls
    for call in calls:
        if not isinstance(call, dict):
            continue
        compact = dict(call)
        compact["args"] = parse_json_field(compact.pop("args_json", None))
        compact["result"] = parse_json_field(compact.pop("result_json", None))
        compact_calls.append(compact)
    return compact_calls


def compact_summary_model_calls(calls: Any) -> list[dict[str, Any]]:
    compact_calls: list[dict[str, Any]] = []
    if not isinstance(calls, list):
        return compact_calls
    for call in calls:
        if not isinstance(call, dict):
            continue
        compact = dict(call)
        compact["tools"] = parse_json_field(compact.pop("tools_json", None))
        compact["usage"] = parse_json_field(compact.pop("usage_json", None))
        compact["response"] = parse_json_field(compact.pop("response_json", None))
        compact_calls.append(compact)
    return compact_calls


def model_usage_summary(calls: Any) -> dict[str, int]:
    summary = {
        "model_call_count": 0,
        "ok_model_call_count": 0,
        "error_model_call_count": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cached_prompt_tokens": 0,
        "uncached_prompt_tokens": 0,
    }
    if not isinstance(calls, list):
        return summary
    for call in calls:
        if not isinstance(call, dict):
            continue
        summary["model_call_count"] += 1
        if call.get("status") == "ok":
            summary["ok_model_call_count"] += 1
        else:
            summary["error_model_call_count"] += 1
        usage = call.get("usage") if isinstance(call.get("usage"), dict) else {}
        summary["prompt_tokens"] += _int_value(usage.get("prompt_tokens"))
        summary["completion_tokens"] += _int_value(usage.get("completion_tokens"))
        summary["total_tokens"] += _int_value(usage.get("total_tokens"))
        summary["cached_prompt_tokens"] += _int_value(usage.get("prompt_cache_hit_tokens"))
        summary["uncached_prompt_tokens"] += _int_value(usage.get("prompt_cache_miss_tokens"))
    return summary


def parse_json_field(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def snapshot_hash(snapshot: dict[str, Any]) -> str:
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def snapshot_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    player = snapshot.get("player_state") if isinstance(snapshot.get("player_state"), dict) else {}
    world = snapshot.get("world_state") if isinstance(snapshot.get("world_state"), dict) else {}
    blocks = flatten_blocks(snapshot.get("nearby_blocks"))
    entities = snapshot.get("nearby_entities") if isinstance(snapshot.get("nearby_entities"), list) else []
    return {
        "player": {
            "dimension": player.get("dimension"),
            "x": player.get("x"),
            "y": player.get("y"),
            "z": player.get("z"),
            "health": player.get("health"),
            "food": player.get("food"),
            "on_fire": player.get("on_fire"),
            "in_lava": player.get("in_lava"),
            "underwater": player.get("underwater"),
            "on_ground": player.get("on_ground"),
        },
        "world": {
            "day_time": world.get("day_time"),
            "difficulty": world.get("difficulty"),
            "weather": "thunder" if world.get("thundering") else "rain" if world.get("raining") else "clear",
            "spawn_x": world.get("spawn_x"),
            "spawn_y": world.get("spawn_y"),
            "spawn_z": world.get("spawn_z"),
            "player_distance_from_spawn": world.get("player_distance_from_spawn"),
        },
        "nearby": {
            "entities": len(entities),
            "blocks": len(blocks),
            "logs": sum(1 for block in blocks if block.get("category") == "log"),
        },
    }


def flatten_blocks(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        blocks: list[dict[str, Any]] = []
        for nested in value.values():
            blocks.extend(flatten_blocks(nested))
        return blocks
    return []
