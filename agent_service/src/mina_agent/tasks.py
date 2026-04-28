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
        self._active_body_task_id: str | None = None

    def start_task(self, task_type: str, args: dict[str, Any], turn: dict[str, Any]) -> TurnResponse:
        if task_type not in {"chop_tree", "follow_player"}:
            return TurnResponse(messages=[{"target": "requester", "content": f"Unsupported body task: {task_type}"}])

        player = turn.get("player") or {}
        player_id = str(player.get("uuid") or player.get("id") or "unknown")
        with self._lock:
            preamble_actions: list[dict[str, Any]] = []
            for old_task_id in self._active_task_ids():
                old_task = self._tasks[old_task_id]
                old_task["status"] = "cancelled"
                old_task["stage"] = "cancelled"
                old_task["updated_at"] = time.time()
                self.memory.record_task_event(
                    old_task_id,
                    "cancelled_by_new_task",
                    {
                        "player_id": old_task.get("player_id"),
                        "replacement_type": task_type,
                        "replacement_player_id": player_id,
                    },
                )
                self._clear_current_if_terminal(old_task)
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
                "target_ordinal": 0,
                "last_error": None,
                "active_action_id": None,
                "active_step_id": None,
                "cycles": 0,
                "latest_snapshot": turn.get("snapshot") or {},
                "created_at": time.time(),
                "updated_at": time.time(),
            }
            self._tasks[task_id] = task
            self._active_by_player[player_id] = task_id
            self._active_body_task_id = task_id
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
            if task_id:
                task = self._tasks.get(task_id)
                if task is None:
                    return response
                tasks = [task]
            else:
                tasks = [task for task in self._tasks.values() if task.get("status") == "active"]
            for task in tasks:
                task["latest_snapshot"] = snapshot
                task["updated_at"] = time.time()
                self.memory.record_task_event(task["task_id"], "observation", {"summary": _snapshot_summary(snapshot)})
                if task.get("status") == "active" and task.get("stage") == "spawn_sent" and _body_online(snapshot):
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
        if self._active_body_task_id:
            task = self._tasks.get(self._active_body_task_id)
            if task is not None and task.get("status") == "active":
                return task
        return None

    def _active_task_ids(self) -> list[str]:
        task_ids: list[str] = []
        if self._active_body_task_id:
            task_ids.append(self._active_body_task_id)
        for task_id, task in self._tasks.items():
            if task.get("status") == "active" and task_id not in task_ids:
                task_ids.append(task_id)
        return task_ids

    def _handle_result(self, task: dict[str, Any], result: dict[str, Any]) -> TurnResponse:
        if task.get("status") != "active":
            return TurnResponse(debug={"task_status": _public_task(task)})
        action_id = str(result.get("action_id") or "")
        active_action_id = str(task.get("active_action_id") or "")
        step_id = str(result.get("step_id") or "")
        active_step_id = str(task.get("active_step_id") or "")
        stale_reason = ""
        if active_action_id and action_id and action_id != active_action_id:
            stale_reason = "action_id_mismatch"
        elif active_step_id and step_id and step_id != active_step_id:
            stale_reason = "step_id_mismatch"
        elif active_action_id and not action_id and not step_id:
            stale_reason = "missing_action_and_step"
        if stale_reason:
            self.memory.record_task_event(
                task["task_id"],
                "stale_action_result",
                {
                    "reason": stale_reason,
                    "action_id": action_id,
                    "active_action_id": active_action_id,
                    "step_id": step_id,
                    "active_step_id": active_step_id,
                },
            )
            return TurnResponse(debug={"task_status": _public_task(task)})
        status = str(result.get("status") or "")
        monitor = result.get("monitor_result") if isinstance(result.get("monitor_result"), dict) else {}
        monitor_status = str(monitor.get("status") or "")
        command_success = result.get("command_success")

        if command_success is False or status in {"command_failed", "failed"}:
            return self._recover_or_fail(task, result.get("error") or "command failed")
        if monitor_status in {"failed", "timeout"} or status in {"monitor_failed", "timeout"}:
            if task.get("type") == "chop_tree" and step_id.startswith("look"):
                snapshot = task.get("latest_snapshot") or {}
                current_target = self._current_or_replacement_target(task, snapshot, task.get("target") or {})
                if isinstance(current_target, TurnResponse):
                    return current_target
            recovered = self._recover_or_fail(task, monitor.get("reason") or result.get("error") or "monitor failed")
            if task.get("type") == "chop_tree" and step_id.startswith("attack"):
                return _prepend_action(recovered, _attack_release_action(task, step_id))
            return recovered
        if task.get("type") == "follow_player":
            return self._handle_follow_result(task, result, status, monitor_status)
        if monitor_status != "success" and status not in {"completed", "success"}:
            return TurnResponse(debug={"task_status": _public_task(task)})

        snapshot = task.get("latest_snapshot") or {}
        if step_id.startswith("spawn"):
            if not _body_online(snapshot):
                task["stage"] = "spawn_sent"
                return TurnResponse(debug={"task_status": _public_task(task)})
            return self._advance(task, snapshot)
        if step_id.startswith("move"):
            task["stage"] = "look"
            return self._advance(task, snapshot)
        if step_id.startswith("look"):
            task["stage"] = "attack"
            return self._advance(task, snapshot)
        if step_id.startswith("attack"):
            next_target = _choose_stacked_log_target(snapshot, task.get("target") or {})
            if next_target is not None:
                previous_target = task.get("target")
                task["target"] = next_target
                task["target_ordinal"] = int(task.get("target_ordinal") or 0) + 1
                task["stage"] = "look"
                task["last_error"] = None
                self.memory.record_task_event(
                    task["task_id"],
                    "target_completed_continue",
                    {"old_target": previous_target, "next_target": next_target},
                )
                advanced = self._advance(task, snapshot)
                return _prepend_action(advanced, _attack_release_action(task, step_id))
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
                actions=[_attack_release_action(task, step_id)],
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
            step_suffix = _step_suffix(task)
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
                step=f"move:{step_suffix}",
                monitor={
                    "type": "body_near",
                    "x": args["x"],
                    "y": args["y"],
                    "z": args["z"],
                    "radius": 0.9,
                    "deadline_ticks": 160,
                },
            )
            self._mark_action(task, action)
            task["stage"] = "move_sent"
            return TurnResponse(actions=[action], debug={"task_status": _public_task(task)})

        if task.get("stage") == "look":
            target = task.get("target") or {}
            step_suffix = _step_suffix(task)
            current_target = self._current_or_replacement_target(task, snapshot, target)
            if isinstance(current_target, TurnResponse):
                return current_target
            target = current_target
            task["target"] = target
            action = _action(
                task,
                "body_look_at_position",
                {
                    "x": float(target["center_x"]),
                    "y": float(target["center_y"]),
                    "z": float(target["center_z"]),
                },
                step=f"look:{step_suffix}",
                monitor={
                    "type": "body_targeted_block",
                    "x": int(target["x"]),
                    "y": int(target["y"]),
                    "z": int(target["z"]),
                    "block": str(target.get("block") or ""),
                    "deadline_ticks": 50,
                },
            )
            self._mark_action(task, action)
            task["stage"] = "look_sent"
            return TurnResponse(actions=[action], debug={"task_status": _public_task(task)})

        if task.get("stage") == "attack":
            target = task.get("target") or {}
            step_suffix = _step_suffix(task)
            current_target = self._current_or_replacement_target(task, snapshot, target)
            if isinstance(current_target, TurnResponse):
                return current_target
            target = current_target
            task["target"] = target
            action = _action(
                task,
                "body_attack",
                {
                    "mode": "hold",
                },
                step=f"attack:{step_suffix}",
                monitor={
                    "type": "block_absent",
                    "x": int(target["x"]),
                    "y": int(target["y"]),
                    "z": int(target["z"]),
                    "block": str(target.get("block") or ""),
                    "deadline_ticks": 240,
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

    def _current_or_replacement_target(
        self,
        task: dict[str, Any],
        snapshot: dict[str, Any],
        target: dict[str, Any],
    ) -> dict[str, Any] | TurnResponse:
        current_target = _find_block(snapshot, target)
        if current_target is not None:
            return _with_previous_approach(current_target, target)
        replacement = _choose_replacement_log_target(snapshot, target)
        self.memory.record_task_event(
            task["task_id"],
            "target_disappeared",
            {"old_target": target, "replacement": replacement},
        )
        if replacement is None:
            task["status"] = "completed"
            task["stage"] = "done"
            task["last_error"] = "target disappeared before attack"
            task["updated_at"] = time.time()
            self._clear_current_if_terminal(task)
            self.memory.add_skill_reflection(
                "chop_tree",
                "If the selected log disappears before attack and no other log is available, stop without attacking empty space.",
                {"task_id": task["task_id"], "target": target},
            )
            return TurnResponse(
                messages=[{"target": "requester", "content": "目标原木已经不存在，附近没有其他可砍的原木，我先停下。"}],
                debug={"task_status": _public_task(task)},
            )
        task["attempts"] = int(task.get("attempts") or 0) + 1
        task["target"] = replacement
        task["last_error"] = "target disappeared before attack"
        task["stage"] = "move"
        return self._advance(task, snapshot)

    def _recover_or_fail(self, task: dict[str, Any], reason: Any) -> TurnResponse:
        task["attempts"] = int(task.get("attempts") or 0) + 1
        task["last_error"] = str(reason)
        self.memory.record_task_event(task["task_id"], "recovery", {"reason": task["last_error"], "attempts": task["attempts"]})
        if _body_unavailable_reason(task["last_error"]):
            task["status"] = "failed"
            task["stage"] = "failed"
            self._clear_current_if_terminal(task)
            self.memory.add_skill_reflection(
                str(task.get("type") or "unknown"),
                f"{task.get('type')} unavailable: {task['last_error']}",
                {"task_id": task["task_id"], "target": task.get("target")},
            )
            return TurnResponse(
                messages=[{"target": "requester", "content": "身体执行不可用：PuppetPlayers 未安装或 Mina body 已被禁用。"}],
                debug={"task_status": _public_task(task)},
            )
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
        target = task.get("target") if isinstance(task.get("target"), dict) else {}
        if target:
            task["stage"] = "move" if _has_approach(target) else "look"
        else:
            task["stage"] = "new"
        return self._advance(task, snapshot)

    def _mark_action(self, task: dict[str, Any], action: dict[str, Any]) -> None:
        task["active_action_id"] = action["id"]
        task["active_step_id"] = action["step_id"]
        self.memory.record_task_event(task["task_id"], "action_scheduled", action)

    def _clear_current_if_terminal(self, task: dict[str, Any]) -> None:
        if task.get("status") not in {"completed", "failed", "cancelled"}:
            return
        player_id = str(task.get("player_id") or "")
        if self._active_by_player.get(player_id) == task.get("task_id"):
            self._active_by_player.pop(player_id, None)
        if self._active_body_task_id == task.get("task_id"):
            self._active_body_task_id = None


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


def _attack_release_action(task: dict[str, Any], attack_step_id: str) -> dict[str, Any]:
    suffix = attack_step_id.split(":", 1)[1] if ":" in attack_step_id else _step_suffix(task)
    action = _action(task, "body_attack", {"mode": "release"}, step=f"attack_release:{suffix}", monitor=None)
    action["requires_permission"] = False
    return action


def _prepend_action(response: TurnResponse, action: dict[str, Any]) -> TurnResponse:
    response.actions = [action] + response.actions
    return response


def _choose_log_target(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    for block in _log_candidates(snapshot):
        if _is_reachable_log_candidate(block, snapshot):
            return dict(block)
    return None


def _has_approach(block: dict[str, Any]) -> bool:
    return all(key in block for key in ("approach_x", "approach_y", "approach_z"))


def _with_previous_approach(current: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    merged = dict(current)
    for key in ("approach_x", "approach_y", "approach_z"):
        if key not in merged and key in previous:
            merged[key] = previous[key]
    return merged


def _choose_replacement_log_target(snapshot: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any] | None:
    if not all(key in previous for key in ("x", "y", "z", "approach_x", "approach_y", "approach_z")):
        return _choose_log_target(snapshot)
    stacked = _choose_stacked_log_target(snapshot, previous)
    if stacked is not None:
        return stacked
    return _choose_log_target(snapshot)


def _choose_stacked_log_target(snapshot: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any] | None:
    if not all(key in previous for key in ("x", "y", "z", "approach_x", "approach_y", "approach_z")):
        return None
    previous_x = int(previous["x"])
    previous_z = int(previous["z"])
    previous_y = int(previous["y"])
    candidates: list[dict[str, Any]] = []
    for block in _log_candidates(snapshot):
        same_column = int(block["x"]) == previous_x and int(block["z"]) == previous_z
        vertical_delta = int(block["y"]) - previous_y
        if same_column and 0 < vertical_delta <= 4:
            candidates.append(dict(block))
    if not candidates:
        return None
    candidates.sort(key=lambda block: int(block["y"]))
    replacement = candidates[0]
    replacement["approach_x"] = previous["approach_x"]
    replacement["approach_y"] = previous["approach_y"]
    replacement["approach_z"] = previous["approach_z"]
    return replacement


def _step_suffix(task: dict[str, Any]) -> str:
    attempts = int(task.get("attempts") or 0)
    target_ordinal = int(task.get("target_ordinal") or 0)
    if target_ordinal <= 0:
        return str(attempts)
    return f"{target_ordinal}.{attempts}"


def _is_reachable_log_candidate(block: dict[str, Any], snapshot: dict[str, Any]) -> bool:
    if not _has_approach(block):
        return False
    approach_y = _float_value(block.get("approach_y"))
    target_y = _float_value(block.get("y"))
    if approach_y is None or target_y is None:
        return False
    anchor_ys = _snapshot_actor_ys(snapshot)
    if not anchor_ys:
        return True
    for actor_y in anchor_ys:
        approach_delta = approach_y - actor_y
        target_delta = target_y - actor_y
        if -4.0 <= approach_delta <= 2.25 and -4.0 <= target_delta <= 3.25:
            return True
    return False


def _snapshot_actor_ys(snapshot: dict[str, Any]) -> list[float]:
    values: list[float] = []
    for key in ("body_state", "player_state"):
        state = snapshot.get(key)
        if not isinstance(state, dict):
            continue
        y = _float_value(state.get("y"))
        if y is not None:
            values.append(y)
    return values


def _float_value(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _log_candidates(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = _flatten_blocks(snapshot.get("nearby_blocks"))
    logs = [
        block for block in blocks
        if isinstance(block, dict)
        and block.get("category") == "log"
        and all(key in block for key in ("x", "y", "z", "center_x", "center_y", "center_z"))
    ]
    logs.sort(key=lambda block: float(block.get("distance") or 9999))
    return logs


def _find_block(snapshot: dict[str, Any], target: dict[str, Any]) -> dict[str, Any] | None:
    if not all(key in target for key in ("x", "y", "z")):
        return None
    target_pos = (int(target["x"]), int(target["y"]), int(target["z"]))
    expected_block = str(target.get("block") or "")
    expected_category = str(target.get("category") or "log")
    for block in _flatten_blocks(snapshot.get("nearby_blocks")):
        if not isinstance(block, dict) or not all(key in block for key in ("x", "y", "z")):
            continue
        block_pos = (int(block["x"]), int(block["y"]), int(block["z"]))
        if block_pos == target_pos and block.get("category") == expected_category and (not expected_block or block.get("block") == expected_block):
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


def _body_unavailable_reason(reason: str) -> bool:
    normalized = reason.lower()
    return "body is unavailable" in normalized or "puppetplayers is not installed" in normalized or "body use is disabled" in normalized


def _public_task(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": task.get("task_id"),
        "type": task.get("type"),
        "status": task.get("status"),
        "stage": task.get("stage"),
        "attempts": task.get("attempts"),
        "target_ordinal": task.get("target_ordinal"),
        "target": task.get("target"),
        "last_error": task.get("last_error"),
        "active_action_id": task.get("active_action_id"),
        "active_step_id": task.get("active_step_id"),
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
