from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .schemas import ToolResult, TurnResponse
from .tools import ToolRunner


@dataclass(frozen=True)
class BodySubagentResult:
    response: TurnResponse
    tool_name: str
    args: dict[str, Any]
    tool_result: ToolResult


class BodySubagent:
    """Deterministic body-control subagent.

    The main agent handles conversation and knowledge. Explicit body-control
    intents are routed here so the model does not micromanage stop/move/attack
    sequencing or split task replacement across multiple turns.
    """

    def __init__(self, tools: ToolRunner):
        self.tools = tools

    def handle(self, turn: dict[str, Any]) -> BodySubagentResult | None:
        if turn.get("trigger") != "command":
            return None
        message = str(turn.get("message") or "").strip()
        normalized = message.lower()
        if not normalized:
            return None

        if is_body_task_status_request(normalized):
            return self._status(turn)
        if is_body_instructional_request(normalized):
            return None
        if _stop_intent(normalized):
            return self._tool_response(
                "stop_body_task",
                {},
                turn,
                intent="stop_body_task",
                fallback_message="我已经停止当前身体任务。",
            )
        if _follow_intent(normalized):
            return self._tool_response(
                "start_body_task",
                {"task_type": "follow_player", "target_hint": message},
                turn,
                intent="follow_player",
                fallback_message="我开始跟随你，会根据距离变化继续调整。",
            )
        if _chop_tree_intent(normalized):
            return self._tool_response(
                "start_body_task",
                {"task_type": "chop_tree", "target_hint": message},
                turn,
                intent="chop_tree",
                fallback_message="我开始砍树，会根据实际执行结果继续调整。",
            )
        return None

    def _status(self, turn: dict[str, Any]) -> BodySubagentResult:
        args: dict[str, Any] = {}
        result = self.tools.run("task_status", args, turn)
        status = _json_object(result.content)
        if status.get("ok") is False:
            content = "当前没有正在执行的身体任务。"
        else:
            content = f"当前任务：{status.get('type')}，状态：{status.get('status')}，阶段：{status.get('stage')}。"
        response = TurnResponse(
            messages=[{"target": "requester", "content": content}],
            debug={"body_subagent": True, "intent": "task_status", "task_status": status},
        )
        return BodySubagentResult(response=response, tool_name="task_status", args=args, tool_result=result)

    def _tool_response(
        self,
        name: str,
        args: dict[str, Any],
        turn: dict[str, Any],
        intent: str,
        fallback_message: str,
    ) -> BodySubagentResult:
        result = self.tools.run(name, args, turn)
        payload = _json_object(result.content)
        actions = _result_actions(result)
        messages = payload.get("messages") if isinstance(payload.get("messages"), list) else []
        if payload.get("ok") is False and not messages:
            messages = [
                {
                    "target": "requester",
                    "content": _permission_or_error_message(name, str(payload.get("error") or "tool unavailable")),
                }
            ]
        elif not messages and actions:
            messages = [{"target": "requester", "content": fallback_message}]
        response = TurnResponse(
            messages=messages,
            actions=actions,
            debug={"body_subagent": True, "intent": intent, "task_status": _task_status(payload)},
        )
        return BodySubagentResult(response=response, tool_name=name, args=args, tool_result=result)


def _result_actions(result: ToolResult) -> list[dict[str, Any]]:
    actions = []
    if result.action:
        actions.append(result.action)
    actions.extend(result.actions)
    return actions


def _json_object(content: str) -> dict[str, Any]:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _task_status(payload: dict[str, Any]) -> dict[str, Any]:
    debug = payload.get("debug") if isinstance(payload.get("debug"), dict) else {}
    task_status = debug.get("task_status") if isinstance(debug.get("task_status"), dict) else {}
    return task_status


def _permission_or_error_message(tool_name: str, error: str) -> str:
    if error == "permission denied":
        if tool_name == "stop_body_task":
            return "我没有权限停止身体任务。"
        return "我没有权限控制身体任务。"
    return f"身体任务无法执行：{error}"


def is_body_task_status_request(message: str) -> bool:
    normalized = message.strip().lower()
    if normalized in {"状态", "进度", "status", "task status"}:
        return True
    return any(
        token in normalized
        for token in (
            "当前任务",
            "任务状态",
            "任务进度",
            "身体任务",
            "body task",
            "task progress",
        )
    )


def _stop_intent(message: str) -> bool:
    return is_body_stop_request(message)


def _follow_intent(message: str) -> bool:
    return is_body_follow_request(message)


def _chop_tree_intent(message: str) -> bool:
    return is_body_chop_tree_request(message)


def is_body_stop_request(message: str) -> bool:
    return any(
        token in message for token in ("停止", "停下", "停一下", "暂停", "取消", "stop", "cancel")
    ) or is_body_negative_stop_request(message)


def is_body_follow_request(message: str) -> bool:
    if is_body_instructional_request(message):
        return False
    return any(
        token in message
        for token in (
            "跟随我",
            "跟着我",
            "跟我",
            "过来",
            "来我这",
            "来我这边",
            "到我这",
            "follow me",
            "follow player",
            "come here",
            "come to me",
        )
    )


def is_body_chop_tree_request(message: str) -> bool:
    if is_body_instructional_request(message):
        return False
    return _contains_chinese_tree_action(message) or _contains_english_tree_action(message) or any(
        token in message
        for token in (
            "砍树",
            "砍木头",
            "伐木",
            "chop tree",
            "chop a tree",
            "cut tree",
            "cut down tree",
            "cut down a tree",
            "chop wood",
            "break log",
            "break logs",
            "break wood",
            "harvest wood",
            "harvest logs",
        )
    )


def _contains_chinese_tree_action(message: str) -> bool:
    tree_terms = ("树", "木头", "原木", "树干")
    action_terms = ("砍", "伐", "采", "采集", "挖", "打", "撸")
    return any(tree in message for tree in tree_terms) and any(action in message for action in action_terms)


def _contains_english_tree_action(message: str) -> bool:
    tree_terms = ("tree", "trees", "log", "logs", "wood")
    action_terms = ("chop", "cut", "break", "harvest", "collect")
    return any(tree in message for tree in tree_terms) and any(action in message for action in action_terms)


def is_body_instructional_request(message: str) -> bool:
    return any(
        token in message
        for token in (
            "查",
            "怎么",
            "如何",
            "怎样",
            "教程",
            "攻略",
            "计划",
            "规划",
            "方案",
            "设计",
            "解释",
            "介绍",
            "知识",
            "查询",
            "问一下",
            "告诉我",
            "how to",
            "help me plan",
            "planning",
            "plan",
            "guide",
            "tutorial",
            "strategy",
            "explain",
            "tell me about",
            "what is",
            "should i",
            "tree farm",
            "farm design",
        )
    )


def is_body_negative_stop_request(message: str) -> bool:
    return any(
        token in message
        for token in (
            "别跟",
            "不要跟",
            "不用跟",
            "不必跟",
            "别过来",
            "不要过来",
            "不用过来",
            "不必过来",
            "别来我这",
            "不要来我这",
            "别砍",
            "不要砍",
            "不用砍",
            "不必砍",
            "别挖",
            "不要挖",
            "不用挖",
            "不必挖",
            "别打树",
            "不要打树",
            "别撸树",
            "不要撸树",
            "别伐木",
            "不要伐木",
            "别动身体",
            "不要动身体",
            "别控制身体",
            "不要控制身体",
            "don't follow",
            "do not follow",
            "dont follow",
            "stop following",
            "don't come",
            "do not come",
            "dont come",
            "don't chop",
            "do not chop",
            "dont chop",
            "stop chopping",
            "don't break logs",
            "do not break logs",
            "stop breaking logs",
            "stop harvesting wood",
            "don't control body",
            "do not control body",
        )
    )
