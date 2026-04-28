from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Any

from .memory import MemoryStore
from .schemas import TurnResponse


class SkillRuntime:
    """Durable-enough in-process runtime for Minecraft body tasks.

    The sidecar owns task state and emits one observable Fabric action at a time.
    Fabric reports command callbacks and monitor verdicts back through
    /v1/action-results; this runtime advances the task only from those results.
    """

    def __init__(self, memory: MemoryStore):
        self.memory = memory
        self._lock = threading.RLock()
        self._tasks: dict[str, dict[str, Any]] = {}
        self._active_by_player: dict[str, str] = {}

    def start_task(self, task_type: str, args: dict[str, Any], turn: dict[str, Any]) -> TurnResponse:
        if task_type not in {"chop_tree", "follow_player"}:
            return TurnResponse(messages=[{"target": "requester", "content": f"Unsupported body task: {task_type}"}])

        player = turn.get("player") or {}
        player_id = str(player.get("uuid") or player.get("id") or "unknown")
        with self._lock:
            preamble_actions: list[dict[str, Any]] = []
            old_task_id = self._active_by_player.get(player_id)
            if old_task_id and old_task_id in self._tasks:
                old_task = self._tasks[old_task_id]
                if old_task.get("status") == "active":
                    old_task["status"] = "cancelled"
                    old_task["stage"] = "cancelled"
                    old_task["updated_at"] = time.time()
                    self.memory.record_task_event(old_task_id, "cancelled_by_new_task", {"player_id": player_id, "replacement_type": task_type})
                    preamble_actions.append(_action(old_task, "body_stop", {}, step="stop:replaced", monitor=None))

            task_id = str(uuid.uuid4())
            task = {
                "task_id": task_id,
                "player_id": player_id,
                "type": task_type,
                "status": "active",
                "stage": "new",
                "attempts": 0,
                "target": None,
                "last_error": None,
                "active_action_id": None,
                "cycles": 0,
                "latest_snapshot": turn.get("snapshot") or {},
                "created_at": time.time(),
                "updated_at": time.time(),
            }
            self._tasks[task_id] = task
            self._active_by_player[player_id] = task_id
            self.memory.record_task_event(task_id, "started", {"task_type": task_type, "args": args})
            response = self._advance(task, turn.get("snapshot") or {})
            self._clear_current_if_terminal(task)
            if preamble_actions:
                response.actions = preamble_actions + response.actions
            if not response.messages:
                if task_type == "follow_player":
                    response.messages.append({"target": "requester", "content": "我开始跟随你，会根据距离变化继续调整。"})
                else:
                    response.messages.append({"target": "requester", "content": "我开始砍树，会根据实际执行结果继续调整。"})
            return response

    def stop_task(self, task_id: str | None, turn: dict[str, Any] | None = None) -> TurnResponse:
        with self._lock:
            task = self._find_task(task_id, turn)
            if task is None or task.get("status") != "active":
                return TurnResponse(messages=[{"target": "requester", "content": "当前没有正在执行的身体任务。"}])
            task["status"] = "cancelled"
            task["stage"] = "cancelled"
            task["updated_at"] = time.time()
            self.memory.record_task_event(task["task_id"], "cancelled", {})
            self._clear_current_if_terminal(task)
            return TurnResponse(
                messages=[{"target": "requester", "content": "我已经停止当前身体任务。"}],
                actions=[_action(task, "body_stop", {}, step="stop", monitor=None)],
            )

    def task_status(self, task_id: str | None, turn: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            task = self._find_task(task_id, turn)
            if task is None:
                return {"ok": False, "error": "task not found"}
            return _public_task(task)

    def handle_action_results(self, payload: dict[str, Any]) -> TurnResponse:
        results = payload.get("action_results")
        if not isinstance(results, list):
            single = payload.get("result") if isinstance(payload.get("result"), dict) else payload
            results = [single]

        response = TurnResponse()
        with self._lock:
            for result in results:
                if not isinstance(result, dict):
                    continue
                task_id = str(result.get("task_id") or "")
                task = self._tasks.get(task_id)
                if task is None:
                    continue
                snapshot = result.get("snapshot") or payload.get("snapshot")
                if isinstance(snapshot, dict):
                    task["latest_snapshot"] = snapshot
                self.memory.record_task_event(task_id, "action_result", result)
                advanced = self._handle_result(task, result)
                response.messages.extend(advanced.messages)
                response.actions.extend(advanced.actions)
                response.debug.update(advanced.debug)
        return response

    def handle_observation(self, payload: dict[str, Any]) -> TurnResponse:
        task_id = str(payload.get("task_id") or "")
        snapshot = payload.get("snapshot")
        response = TurnResponse()
        if not isinstance(snapshot, dict):
            return response
        with self._lock:
            tasks = [self._tasks[task_id]] if task_id in self._tasks else [
                task for task in self._tasks.values() if task.get("status") == "active"
            ]
            for task in tasks:
                task["latest_snapshot"] = snapshot
                task["updated_at"] = time.time()
                self.memory.record_task_event(task["task_id"], "observation", {"summary": _snapshot_summary(snapshot)})
                if task.get("stage") == "spawn_sent" and _body_online(snapshot):
                    advanced = self._advance(task, snapshot)
                    response.messages.extend(advanced.messages)
                    response.actions.extend(advanced.actions)
        return response

    def list_tasks(self) -> list[dict[str, Any]]:
        with self._lock:
            return [_public_task(task) for task in self._tasks.values()]

    def _find_task(self, task_id: str | None, turn: dict[str, Any] | None) -> dict[str, Any] | None:
        if task_id and task_id in self._tasks:
            return self._tasks[task_id]
        if turn:
            player = turn.get("player") or {}
            player_id = str(player.get("uuid") or player.get("id") or "")
            active = self._active_by_player.get(player_id)
            if active:
                task = self._tasks.get(active)
                if task is not None and task.get("status") == "active":
                    return task
        return None

    def _handle_result(self, task: dict[str, Any], result: dict[str, Any]) -> TurnResponse:
        if task.get("status") != "active":
            return TurnResponse(debug={"task_status": _public_task(task)})
        status = str(result.get("status") or "")
        monitor = result.get("monitor_result") if isinstance(result.get("monitor_result"), dict) else {}
        monitor_status = str(monitor.get("status") or "")
        command_success = result.get("command_success")

        if command_success is False or status in {"command_failed", "failed"}:
            return self._recover_or_fail(task, result.get("error") or "command failed")
        if monitor_status in {"failed", "timeout"} or status in {"monitor_failed", "timeout"}:
            return self._recover_or_fail(task, monitor.get("reason") or result.get("error") or "monitor failed")
        if task.get("type") == "follow_player":
            return self._handle_follow_result(task, result, status, monitor_status)
        if monitor_status != "success" and status not in {"completed", "success"}:
            return TurnResponse(debug={"task_status": _public_task(task)})

        step_id = str(result.get("step_id") or "")
        snapshot = task.get("latest_snapshot") or {}
        if step_id.startswith("spawn"):
            if not _body_online(snapshot):
                task["stage"] = "spawn_sent"
                return TurnResponse(debug={"task_status": _public_task(task)})
            return self._advance(task, snapshot)
        if step_id.startswith("move"):
            task["stage"] = "attack"
            return self._advance(task, snapshot)
        if step_id.startswith("attack"):
            task["status"] = "completed"
            task["stage"] = "done"
            task["updated_at"] = time.time()
            self.memory.record_task_event(task["task_id"], "completed", {"target": task.get("target")})
            self._clear_current_if_terminal(task)
            self.memory.add_skill_reflection(
                "chop_tree",
                "Chop tree completed after observed block removal.",
                {"task_id": task["task_id"], "target": task.get("target")},
            )
            return TurnResponse(
                messages=[{"target": "requester", "content": "砍树完成。"}],
                debug={"task_status": _public_task(task)},
            )
        return self._advance(task, snapshot)

    def _handle_follow_result(self, task: dict[str, Any], result: dict[str, Any], status: str, monitor_status: str) -> TurnResponse:
        step_id = str(result.get("step_id") or "")
        snapshot = task.get("latest_snapshot") or {}
        if step_id.startswith("spawn"):
            if not _body_online(snapshot):
                task["stage"] = "spawn_sent"
                return TurnResponse(debug={"task_status": _public_task(task)})
            return self._advance(task, snapshot)
        if step_id.startswith("follow"):
            task["stage"] = "follow"
            if monitor_status == "reposition":
                task["last_error"] = "body drifted from requester"
                self.memory.record_task_event(task["task_id"], "follow_reposition", result.get("monitor_result") or {})
                return self._advance(task, snapshot)
            if monitor_status == "success" or status in {"completed", "success"}:
                task["last_error"] = None
                return self._advance(task, snapshot)
        return TurnResponse(debug={"task_status": _public_task(task)})

    def _advance(self, task: dict[str, Any], snapshot: dict[str, Any]) -> TurnResponse:
        if task.get("status") != "active":
            return TurnResponse(debug={"task_status": _public_task(task)})
        task["updated_at"] = time.time()

        if not _body_online(snapshot):
            task["stage"] = "spawn_sent"
            action = _action(
                task,
                "body_spawn",
                {},
                step="spawn:body",
                monitor={"type": "body_online", "deadline_ticks": 100},
            )
            self._mark_action(task, action)
            return TurnResponse(actions=[action], debug={"task_status": _public_task(task)})

        if task.get("type") == "follow_player":
            return self._advance_follow(task)

        if task.get("stage") in {"new", "spawn_sent"}:
            target = _choose_log_target(snapshot)
            if target is None:
                task["status"] = "failed"
                task["last_error"] = "no log target with approach position"
                self.memory.record_task_event(task["task_id"], "failed", {"reason": task["last_error"]})
                self._clear_current_if_terminal(task)
                return TurnResponse(
                    messages=[{"target": "requester", "content": "我附近没有找到可安全接近的原木，先停下。"}],
                    debug={"task_status": _public_task(task)},
                )
            task["target"] = target
            task["stage"] = "move"
            return self._advance(task, snapshot)

        if task.get("stage") == "move":
            target = task.get("target") or {}
            args = {
                "x": float(target["approach_x"]),
                "y": float(target["approach_y"]),
                "z": float(target["approach_z"]),
                "sprint": False,
                "jump": True,
            }
            action = _action(
                task,
                "body_move_to_position",
                args,
                step=f"move:{task.get('attempts', 0)}",
                monitor={
                    "type": "body_near",
                    "x": args["x"],
                    "y": args["y"],
                    "z": args["z"],
                    "radius": 2.25,
                    "deadline_ticks": 160,
                },
            )
            self._mark_action(task, action)
            task["stage"] = "move_sent"
            return TurnResponse(actions=[action], debug={"task_status": _public_task(task)})

        if task.get("stage") == "attack":
            target = task.get("target") or {}
            action = _action(
                task,
                "body_chain",
                {
                    "clear": True,
                    "loop": False,
                    "restart": True,
                    "actions": [
                        {
                            "type": "look_at_position",
                            "x": float(target["center_x"]),
                            "y": float(target["center_y"]),
                            "z": float(target["center_z"]),
                        },
                        {"type": "attack", "mode": "hold"},
                        {"type": "delay", "seconds": 5.5},
                        {"type": "attack", "mode": "release"},
                    ],
                },
                step=f"attack:{task.get('attempts', 0)}",
                monitor={
                    "type": "block_absent",
                    "x": int(target["x"]),
                    "y": int(target["y"]),
                    "z": int(target["z"]),
                    "block": str(target.get("block") or ""),
                    "deadline_ticks": 180,
                },
                expected_effect={
                    "type": "block_removed",
                    "x": int(target["x"]),
                    "y": int(target["y"]),
                    "z": int(target["z"]),
                },
            )
            self._mark_action(task, action)
            task["stage"] = "attack_sent"
            return TurnResponse(actions=[action], debug={"task_status": _public_task(task)})

        return TurnResponse(debug={"task_status": _public_task(task)})

    def _advance_follow(self, task: dict[str, Any]) -> TurnResponse:
        cycle = int(task.get("cycles") or 0) + 1
        task["cycles"] = cycle
        action = _action(
            task,
            "body_move_to_requester",
            {"sprint": False, "jump": True},
            step=f"follow:{cycle}",
            monitor={
                "type": "follow_requester",
                "max_distance": 4.0,
                "grace_ticks": 80,
                "deadline_ticks": 160,
            },
        )
        self._mark_action(task, action)
        task["stage"] = "follow_sent"
        return TurnResponse(actions=[action], debug={"task_status": _public_task(task)})

    def _recover_or_fail(self, task: dict[str, Any], reason: Any) -> TurnResponse:
        task["attempts"] = int(task.get("attempts") or 0) + 1
        task["last_error"] = str(reason)
        self.memory.record_task_event(task["task_id"], "recovery", {"reason": task["last_error"], "attempts": task["attempts"]})
        if task["attempts"] > 3:
            task["status"] = "failed"
            task["stage"] = "failed"
            self._clear_current_if_terminal(task)
            self.memory.add_skill_reflection(
                str(task.get("type") or "unknown"),
                f"{task.get('type')} failed after repeated recovery: {task['last_error']}",
                {"task_id": task["task_id"], "target": task.get("target")},
            )
            content = "跟随连续失败，我先停下，避免反复误操作。" if task.get("type") == "follow_player" else "砍树连续失败，我先停下，避免反复误操作。"
            return TurnResponse(
                messages=[{"target": "requester", "content": content}],
                actions=[_action(task, "body_stop", {}, step="stop:failed", monitor=None)],
                debug={"task_status": _public_task(task)},
            )
        snapshot = task.get("latest_snapshot") or {}
        if task.get("type") == "follow_player":
            task["stage"] = "follow"
            return self._advance(task, snapshot)
        task["target"] = _choose_log_target(snapshot) or task.get("target")
        task["stage"] = "move" if task.get("target") else "new"
        return self._advance(task, snapshot)

    def _mark_action(self, task: dict[str, Any], action: dict[str, Any]) -> None:
        task["active_action_id"] = action["id"]
        self.memory.record_task_event(task["task_id"], "action_scheduled", action)

    def _clear_current_if_terminal(self, task: dict[str, Any]) -> None:
        if task.get("status") not in {"completed", "failed", "cancelled"}:
            return
        player_id = str(task.get("player_id") or "")
        if self._active_by_player.get(player_id) == task.get("task_id"):
            self._active_by_player.pop(player_id, None)


def _action(
    task: dict[str, Any],
    name: str,
    args: dict[str, Any],
    step: str,
    monitor: dict[str, Any] | None,
    expected_effect: dict[str, Any] | None = None,
) -> dict[str, Any]:
    action = {
        "id": str(uuid.uuid4()),
        "task_id": task["task_id"],
        "step_id": step,
        "name": name,
        "args": args,
        "requires_permission": name not in {"send_player_message", "send_global_message"},
        "deadline_ticks": (monitor or {}).get("deadline_ticks", 0),
    }
    if monitor:
        action["monitor"] = monitor
    if expected_effect:
        action["expected_effect"] = expected_effect
    return action


def _choose_log_target(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    blocks = _flatten_blocks(snapshot.get("nearby_blocks"))
    logs = [
        block for block in blocks
        if isinstance(block, dict)
        and block.get("category") == "log"
        and all(key in block for key in ("x", "y", "z", "center_x", "center_y", "center_z"))
    ]
    logs.sort(key=lambda block: float(block.get("distance") or 9999))
    for block in logs:
        if all(key in block for key in ("approach_x", "approach_y", "approach_z")):
            return dict(block)
    return None


def _flatten_blocks(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        blocks: list[dict[str, Any]] = []
        for nested in value.values():
            blocks.extend(_flatten_blocks(nested))
        return blocks
    return []


def _body_online(snapshot: dict[str, Any]) -> bool:
    body_state = snapshot.get("body_state")
    return bool(body_state.get("online")) if isinstance(body_state, dict) else False


def _public_task(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": task.get("task_id"),
        "type": task.get("type"),
        "status": task.get("status"),
        "stage": task.get("stage"),
        "attempts": task.get("attempts"),
        "target": task.get("target"),
        "last_error": task.get("last_error"),
        "active_action_id": task.get("active_action_id"),
        "cycles": task.get("cycles"),
        "updated_at": task.get("updated_at"),
    }


def _snapshot_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    body = snapshot.get("body_state") if isinstance(snapshot.get("body_state"), dict) else {}
    blocks = _flatten_blocks(snapshot.get("nearby_blocks"))
    return {
        "body_online": bool(body.get("online")),
        "body_x": body.get("x"),
        "body_y": body.get("y"),
        "body_z": body.get("z"),
        "distance_to_requester": body.get("distance_to_requester"),
        "interesting_blocks": len(blocks),
        "logs": sum(1 for block in blocks if block.get("category") == "log"),
    }


def dumps_tool_content(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)
