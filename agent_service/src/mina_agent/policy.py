from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


UNSAFE_WRITE_REFUSAL = "抱歉，我不能执行或提供写入世界的命令。我可以帮你查询只读信息，或说明当前方块和世界状态。"
MEMORY_NOT_SAVED = "我还没有把这条信息保存进记忆。请再说一次要保存的内容。"


@dataclass(frozen=True)
class FinalContentReview:
    content: str
    repair_reason: str = ""
    repair_message: str = ""

    @property
    def needs_repair(self) -> bool:
        return bool(self.repair_message)


class ResponsePolicyRuntime:
    """Deterministic policy checks that run around the LLM/tool loop."""

    def __init__(self) -> None:
        self.unsafe_response_repairs = 0
        self.memory_claim_repairs = 0
        self.memory_write_seen = False

    def note_successful_tool_result(self, tool_name: str, content: str) -> None:
        if tool_name == "memory_write" and not is_tool_error(content):
            self.memory_write_seen = True

    def review_final_content(self, content: str, *, can_repair: bool) -> FinalContentReview:
        cleaned = minecraft_chat_text(content)
        if not cleaned:
            return FinalContentReview(content="")

        if contains_write_command_advice(cleaned):
            self.unsafe_response_repairs += 1
            return FinalContentReview(content=UNSAFE_WRITE_REFUSAL)

        if not self.memory_write_seen and claims_memory_saved(cleaned):
            self.memory_claim_repairs += 1
            if can_repair:
                return FinalContentReview(
                    content=cleaned,
                    repair_reason="memory_claim_without_write",
                    repair_message=(
                        "The previous assistant draft claimed that information was remembered or saved, "
                        "but no memory_write tool succeeded in this turn. If the information is stable "
                        "and useful for future Mina turns, you must call memory_write now. Otherwise "
                        f"rewrite without claiming it was saved and say exactly: {MEMORY_NOT_SAVED}"
                    ),
                )
            return FinalContentReview(content=MEMORY_NOT_SAVED)

        if self.memory_write_seen:
            return FinalContentReview(content=normalize_memory_write_ack(cleaned))

        return FinalContentReview(content=cleaned)


def minecraft_chat_text(content: str) -> str:
    text = content.strip()
    if not text:
        return ""
    text = re.sub(r"\*\*([^*\n]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_\n]+)__", r"\1", text)
    text = text.replace("`", "")
    text = _EMOJI_RE.sub("", text)
    text = _DECORATIVE_CHAT_RE.sub("", text)
    text = _PROCESS_PREAMBLE_RE.sub("", text)
    text = re.sub(r"(?m)^\s*[-*•]\s+", "", text)
    text = re.sub(r"[ \t]*\n+[ \t]*", " ", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def normalize_health_unit_claims(content: str, snapshot: dict[str, Any] | None) -> str:
    if not content or not isinstance(snapshot, dict):
        return content
    player_state = snapshot.get("player_state")
    if not isinstance(player_state, dict):
        return content

    replacements: dict[float, float] = {}
    for value in (player_state.get("health"), player_state.get("max_health")):
        health_points = _float_value(value)
        if health_points is None:
            continue
        hearts = health_points / 2.0
        if abs(health_points - hearts) > 0.001:
            replacements[health_points] = hearts
    if not replacements:
        return content

    def replace(match: re.Match[str]) -> str:
        value = _float_value(match.group("value"))
        unit = match.group("unit")
        if value is None:
            return match.group(0)
        for health_points, hearts in replacements.items():
            if abs(value - health_points) > 0.001:
                continue
            if unit.lower().startswith("heart"):
                return f"{_format_number(health_points)} health points (about {_format_number(hearts)} hearts)"
            return f"{_format_number(health_points)}点生命值（约{_format_number(hearts)}颗心）"
        return match.group(0)

    return _HEALTH_POINTS_AS_HEARTS_RE.sub(replace, content)


def contains_write_command_advice(content: str) -> bool:
    return bool(_WRITE_COMMAND_ADVICE_RE.search(content))


def claims_memory_saved(content: str) -> bool:
    normalized = content.lower()
    return any(
        token in normalized
        for token in (
            "记住了",
            "已记住",
            "已经记住",
            "我会记住",
            "记好了",
            "已记好",
            "已经记好",
            "记下了",
            "已记下",
            "保存好了",
            "我保存了",
            "i'll remember",
            "i will remember",
            "i've saved",
            "i saved",
            "saved this",
        )
    )


def normalize_memory_write_ack(content: str) -> str:
    if _CANONICAL_MEMORY_ACK_RE.search(content):
        return content
    return f"已记住。{content}"


def is_tool_error(content: str) -> bool:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return False
    return isinstance(payload, dict) and payload.get("ok") is False


def _float_value(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.1f}".rstrip("0").rstrip(".")


_EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\ufe0e\ufe0f\u200d\u20e3]")
_DECORATIVE_CHAT_RE = re.compile("[\u301c\uff5e]")
_PROCESS_PREAMBLE_RE = re.compile(
    r"(?is)^\s*(?:"
    r"(?:我(?:来|先)?(?:看[看下]?|查(?:看|一下)?|确认(?:一下)?)[^。！？!?]{0,40}[。！？!?]\s*)|"
    r"(?:let me (?:check|look|see)[^.!?]{0,80}[.!?]\s*)"
    r")+"
)
_HEALTH_POINTS_AS_HEARTS_RE = re.compile(r"(?<![\d.])(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>颗心|hearts|heart)")
_WRITE_COMMAND_ADVICE_RE = re.compile(
    r"(?im)(^|[^\w-])"
    r"(?:minecraft:)?"
    r"(setblock|fill|fillbiome|tp|teleport|gamemode|give|clear|summon|kill|execute|gamerule|op|deop|ban|stop)\b"
)
_CANONICAL_MEMORY_ACK_RE = re.compile(r"(?i)(记住|remember)")
