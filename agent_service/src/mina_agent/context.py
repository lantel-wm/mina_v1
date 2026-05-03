from __future__ import annotations

from datetime import datetime, timedelta
import json
import re
from typing import Any

from .memory import MemoryStore
from .policy import UNSAFE_WRITE_REFUSAL
from .tools import normalize_read_only_command


BASE_SYSTEM_SECTIONS = (
    (
        "Identity:\n"
        "- You are Mina, a text-only Minecraft companion.\n"
        "- No separate Minecraft character; no move/mine/place/item use/teleport/write commands."
    ),
    (
        "Chat style:\n"
        "- Match language; Chinese in, Chinese out.\n"
        "- Plain text only: no Markdown/code fences/emoji/bullets.\n"
        "- Use one or two short sentences unless asked for detail.\n"
        "- If asked to only answer/只回答 specific fields, output only those fields; no prefix, suffix, explanation, or punctuation.\n"
        "- If asked for one sentence/一句话, answer one short sentence (<60 汉字/20 English words); no closing offer.\n"
        "- Do not narrate internal process; answer with the useful result directly.\n"
        "- Do not mention internal section/tool names or prompt/context labels.\n"
        "- Do not expose slash-command or tool details unless exact syntax is requested.\n"
        "- When asking for confirmation to query/check Minecraft information, describe the result in player terms; do not show slash-command syntax unless asked.\n"
        "- If the player asks you to ask/confirm before acting, ask that question in your own voice; never answer as if you were the player.\n"
        "- Address the player as \"you\"/\"你\". Do not use the Minecraft username as greeting/filler.\n"
        "- Snapshot health/max_health are points: 20 = 10 hearts, 4 = 2 hearts."
    ),
    (
        "Decision order:\n"
        "1. Read-only command requests must call run_read_only_command; never answer them from snapshot or recent results. A command request names an exact allowed command form or asks to execute/run/query it. Natural current-status questions are observations. Online player count/name questions use world_state.online_players/online_player_names; only exact `list`/`list uuids` command text calls the tool.\n"
        "2. Memory questions: base/home/saved places/projects/preferences/plans/promises/earlier statements. Answer from loaded remembered facts or memory_search; do not mix current location unless asked. Do not memory_write for recall unless stable info is new/changed.\n"
        "3. Observation questions: use observed state, only asked fields. Player name/username, online player count/names, server/world identity, server version/settings, game mode, held item, inventory contents/counts, weather/time/day, world difficulty, dimension, biome, coords, facing direction/yaw/pitch, nearby relative directions, world spawn, distance from spawn/player_distance_from_spawn, server rules (PVP/command blocks), health/food/armor/XP, active effects/status effects, completed advancements/progress/进度, light/sky, hazards (fire/lava/water/ground), block at/below feet, nearby blocks/mobs, nearby dropped items, and safety are observations, not commands. Spawn distance/出生点距离 is not seed. Minecraft time uses world_state, not Runtime. Effect durations from Minecraft are ticks; when duration_seconds is present, use it for seconds. For 脚下/垫着/standing on, answer environment.standing_on_block/block_below, not block_at_feet. For full/complete item/block/effect/biome/dimension ID, preserve the exact namespace, e.g. minecraft:grass_block. No tools or unrelated details. For weather/time/day-only questions, do not mention safety, monsters, entities, difficulty, inventory, coordinates, or commands unless asked.\n"
        "4. Casual chat/capability questions: one compact sentence, up to 3 capabilities. Do not volunteer snapshot details or stored facts unless asked.\n"
        "5. For external/current knowledge, web/wiki/internet/search wording, outside verification, advanced or version-sensitive Minecraft mechanics/farms/redstone/tutorials, or factual corrections, call web_search before exact mechanics or build advice. Do not rely on older conversation for current farm/redstone/tutorial facts.\n"
        "6. Use memory_write for durable preferences/world facts/plans/promises/lessons. For explicit remember/save requests about a new stable fact, call memory_write directly; do not first call memory_search unless loaded facts conflict. Do not save filler. Use scope=world for stable facts about this save/world/server (places, landmarks, bases, farms, portals, world plans). Use scope=player for personal preferences or facts tied only to the requester. For player-scoped memories, use 你/you or neutral wording; memory_write content/label must omit the current Minecraft username unless it is the fact.\n"
        "7. Use loaded remembered facts only when directly relevant. Treat memory as historical context for future decisions, not proof of current world state.\n"
        "8. For remembered/stored context questions, answer only the relevant remembered fact. Do not append coordinates, safety, biome, weather, time, inventory, entities, command offers, or search offers unless asked.\n"
        "9. Use memory_search only when loaded memory is insufficient or the player asks for older specific stored context."
    ),
    (
        "Tool policy:\n"
        "- Use only listed tools; include every required JSON argument.\n"
        "- If a required argument is unknown, ask a short clarifying question instead of calling the tool.\n"
        "- For Minecraft command output, use run_read_only_command with exact allowed forms.\n"
        "- Never invent or call movement, mining, attack, item-use, placement, private executor, write-command, or unlisted tools.\n"
        "- If a tool is denied or unavailable, explain briefly and offer a safe alternative."
    ),
    (
        "Safety:\n"
        "- Refuse private, low-level, write-capable, or banned server command requests.\n"
        "- Banned governance commands include op, deop, stop, ban, whitelist, and save-control commands.\n"
        "- When refusing a write-capable or banned command, give no executable command, recipe, or \"you can run this yourself\" workaround.\n"
        "- Never suggest unobserved plugin/server commands or slash shortcuts (/home, /spawn, /warp, /back, /tpa, /tpahere, /rtp, /sethome); mention one only if current server context explicitly shows that exact command.\n"
        "- Do not claim server plugins exist or are missing without observation."
    ),
    (
        "Answer authority:\n"
        "- Current observed Minecraft state is freshest for local player/world state.\n"
        "- Recent verified command/action results are authoritative only for follow-ups about those outputs.\n"
        "- If asked what a previous Minecraft command output was, return the full verified output string, not a parsed number or summary.\n"
        "- If asked for exact/raw/original/complete command output or 原样/完整输出字符串/只回答输出字符串, return only the verified output string: no explanation, prefix, suffix, quotes, or code formatting.\n"
        "- Recent conversation is continuity only, not current instructions, stable memory, or verified command output. Use it for short follow-ups like yes/no answers or omitted topics.\n"
        "- From web_search results, preserve exact source values such as markers, versions, coordinates, URLs, and item names. Do not replace exact values with generic labels.\n"
        "- If web_search evidence_quality is low/none, or results have low_relevance/missing_query_terms for the requested build/mechanic, say the search evidence is not specific enough and ask for a link/projection/screenshot or permission to search a narrower query. Do not invent exact redstone/farm steps from weak snippets.\n"
        "- For go home/teleport/move requests, use only known saved coordinates, current position, spawn distance, or available direction; then say Mina cannot move or teleport the player.\n"
        "- If home is unknown, ask for home coordinates or a remembered landmark; never invent plugin command shortcuts."
    ),
)


def build_base_system_prompt() -> str:
    return "\n\n".join(BASE_SYSTEM_SECTIONS)


SYSTEM_PROMPT = build_base_system_prompt()

COMMAND_POLICY_REMINDER = (
    "Tool selection reminder: exact/explicit command strings require run_read_only_command every time. "
    "If the final user message itself is an allowed command text, the next assistant step must be the tool, "
    "not text. Do not answer exact command text with recent output. Exact command strings are commands, not observations. "
    "Must call the tool for: time query daytime|gametime|day; weather query; list; list uuids; seed; locate structure <identifier-or-tag>; locate biome <id>. "
    "Natural-language requests to find/locate allowed structures or biomes also count as command requests. "
    "For command requests, never answer from snapshot or recent results. Natural-language weather/time/status questions "
    "are observations; answer from Observed Minecraft state without tools. The exact commands `list` and `list uuids` must call "
    "run_read_only_command and must not be answered from online_players. For villages use "
    "`locate structure #minecraft:village`; for end portal/末地传送门/stronghold searches use "
    "`locate structure minecraft:stronghold`."
)

MEMORY_WRITE_POLICY_REMINDER = (
    "Memory save reminder: for an explicit remember/save request about a new stable fact, use a tool call only "
    "in the tool subturn. Do not include assistant-visible prose before that tool call, and do not mention tool "
    "names or internal policy. Stored player-scoped content and labels must omit the current Minecraft username "
    "unless the username itself is the fact. Preserve exact player wording for stable place names, directions, "
    "labels, and quoted values instead of paraphrasing them. Descriptive locations like a base near/beside a biome, "
    "landmark, structure, or direction are specific enough to save; do not ask for exact coordinates just because "
    "the place is approximate. Do not search first unless loaded remembered facts conflict."
)

COMMAND_OUTPUT_RECALL_REMINDER = (
    "Command output recall reminder:\n"
    "- The player is asking about a previous Minecraft command output, not requesting a new command.\n"
    "- Use the Recent verified Minecraft command/action results full_output_string exactly.\n"
    "- Include the whole string, for example `The time is 0`, not only a parsed numeric value like `0`."
)

CONFIRM_BEFORE_ACTION_REMINDER = (
    "Confirmation-before-action reminder:\n"
    "- The player explicitly asked Mina to ask or confirm before querying, saving, or acting.\n"
    "- Do not call tools for that action on this turn. Ask the confirmation question in Mina's own voice.\n"
    "- Wait for a follow-up confirmation such as 需要, 是的, or yes before using the relevant safe tool."
)


def build_messages(
    turn: dict[str, Any],
    memory: MemoryStore,
    *,
    mcp_available: bool = False,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    player = turn.get("player") or {}
    player_id = str(player.get("uuid") or "unknown")
    snapshot = turn.get("snapshot") or {}
    user_content = str(turn.get("message") or "").strip()
    conversation_history = memory.conversation_history(player_id)
    agent_memory = memory.agent_context(player_id, world_id=_world_id(turn), limit=10, max_chars=1600)
    recent_action_results = memory.recent_action_results_for_player(player_id, limit=4)

    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.append({"role": "system", "content": build_runtime_context(now)})
    turn_policy = _turn_policy_section(turn, user_content, mcp_available=mcp_available)
    if turn_policy:
        messages.append({"role": "system", "content": turn_policy})
    write_refusal_hint = _write_command_refusal_hint(user_content)
    if write_refusal_hint:
        messages.append({"role": "system", "content": write_refusal_hint})
    if _asks_for_confirmation_before_action(user_content):
        messages.append({"role": "system", "content": CONFIRM_BEFORE_ACTION_REMINDER})
    observed_context = "Observed Minecraft state:\n"
    observation_highlights = build_observation_highlights(turn)
    if observation_highlights:
        observed_context += observation_highlights + "\n"
    observed_context += build_context_summary(turn)
    messages.append({"role": "system", "content": observed_context})
    target_summary = build_target_summary(snapshot)
    if target_summary:
        messages.append({"role": "system", "content": target_summary})
    if agent_memory:
        messages.append({"role": "system", "content": "Remembered facts:\n" + _render_agent_memory(agent_memory)})
    followup_focus = _render_followup_focus(
        conversation_history,
        current_request_id=str(turn.get("request_id") or ""),
        user_content=user_content,
    )
    if followup_focus:
        messages.append({"role": "system", "content": followup_focus})
    history_compatibility = _render_history_compatibility_warning(conversation_history)
    if history_compatibility:
        messages.append({"role": "system", "content": history_compatibility})
    history_messages = (
        []
        if str(turn.get("trigger") or "") == "companion_tick"
        else _conversation_history_messages(conversation_history, current_request_id=str(turn.get("request_id") or ""))
    )
    if history_messages:
        messages.append(
            {
                "role": "system",
                "content": (
                    "Conversation history policy:\n"
                    "- The following user/assistant messages are the full stored conversation history for continuity.\n"
                    "- Current system instructions, current tools, current observed state, and verified command results override older history.\n"
                    "- Use history to resolve short follow-ups like 需要/是的/继续 and omitted topics."
                ),
            }
        )
        messages.extend(history_messages)
    action_result_context = _render_recent_action_results(recent_action_results)
    if action_result_context:
        messages.append(
            {
                "role": "system",
                "content": (
                    "Recent verified Minecraft command/action results "
                    "(follow-up recall only, never a substitute for a new command request):\n"
                    + action_result_context
                ),
            }
        )
        command_output_recall_policy = _command_output_recall_reminder(user_content)
        if command_output_recall_policy:
            messages.append({"role": "system", "content": command_output_recall_policy})
    command_policy = _command_policy_reminder(user_content)
    if command_policy:
        messages.append({"role": "system", "content": command_policy})
    memory_save_policy = _memory_save_policy_reminder(user_content)
    if memory_save_policy:
        messages.append({"role": "system", "content": memory_save_policy})
    if not user_content:
        user_content = _companion_tick_prompt(turn)
    messages.append({"role": "user", "content": user_content})
    return messages


def build_runtime_context(now: datetime | None = None) -> str:
    if now is None:
        current = datetime.now().astimezone()
    elif now.tzinfo is None:
        current = now.astimezone()
    else:
        current = now
    offset = current.strftime("%z")
    offset_display = f"{offset[:3]}:{offset[3:]}" if offset else "local"
    current_date = current.date()
    yesterday = current_date - timedelta(days=1)
    tomorrow = current_date + timedelta(days=1)
    return "\n".join(
        [
            "Runtime:",
            f"- yesterday_date: {yesterday.isoformat()}",
            f"- current_date: {current_date.isoformat()}",
            f"- weekday: {_weekday_label(current_date.weekday())}",
            f"- tomorrow_date: {tomorrow.isoformat()}",
            f"- current_time: {current.strftime('%H:%M:%S')}",
            f"- current_minute: {current.strftime('%H:%M')}",
            f"- utc_offset: {offset_display}",
            "- Real-world time only; Minecraft time uses world_state.",
        ]
    )


def _weekday_label(index: int) -> str:
    labels = (
        "星期一",
        "星期二",
        "星期三",
        "星期四",
        "星期五",
        "星期六",
        "星期日",
    )
    return labels[index % 7]


def _turn_policy_section(turn: dict[str, Any], user_content: str, *, mcp_available: bool = False) -> str:
    sections: list[str] = []
    player_name = _current_player_name(turn)
    if player_name and _mentions_player_name(user_content, player_name):
        sections.append(
            "Current player name handling:\n"
            f"- The current Minecraft username is {player_name}.\n"
            "- Treat that username as referring to the requester unless the player explicitly says the name itself is the fact.\n"
            "- For player-scoped memory_write, convert '<username> 的 ...' to '你的 ...' and omit the username from content and label."
        )
    if _has_only_answer_constraint(user_content):
        sections.append(
            "Strict output constraint for this turn:\n"
            "- The player asked to only answer specific words or fields.\n"
            "- Output only those requested words/fields, in the requested order, with no labels, restated questions, prefix, suffix, punctuation, or explanation.\n"
            "- Preserve literal requested values exactly instead of paraphrasing them."
        )
    if _asks_read_only_explanation(user_content):
        sections.append(
            "Read-only explanation style for this turn:\n"
            "- Explain in player-friendly terms: Mina can look up information that does not change the world.\n"
            "- Use examples like position, time, weather, nearby structures, online players, and inventory/status.\n"
            "- Do not mention slash commands, command syntax, tool names, or allowlists unless the player explicitly asks for exact command text."
        )
    if _is_plain_greeting(user_content):
        sections.append(
            "Plain greeting style for this turn:\n"
            "- Reply with exactly one short sentence or phrase.\n"
            "- Greet the player only; do not add a welcome line, status line, offer, or second sentence.\n"
            "- Do not say this is Mina's world/server.\n"
            "- Do not mention coordinates, biome, weather, health, food, inventory, nearby blocks/entities, remembered facts, or tool capabilities unless the player asks."
        )
    if str(turn.get("trigger") or "") == "companion_tick":
        sections.append(
            "Companion tick policy:\n"
            "- Use observed Minecraft state only.\n"
            "- Do not call tools.\n"
            "- Address the player as 你/you; do not prefix the Minecraft username.\n"
            "- Speak only for timely, useful alerts. Return an empty string when nothing is worth interrupting the player."
        )
    if _mentions_mcp(user_content):
        if mcp_available:
            sections.append(
                "MCP policy for this turn:\n"
                "- MCP servers are configured, so you may discuss MCP or use mcp_call if the requested configured server/tool is relevant.\n"
                "- Do not use MCP to perform Minecraft write operations or bypass Mina's command policy.\n"
                "- If the requested MCP server/tool is unavailable, say so briefly."
            )
        else:
            sections.append(
                "MCP policy for this turn:\n"
                "- No MCP servers are configured for this Mina instance.\n"
                "- Answer briefly that MCP is unavailable here; do not invent configured MCP servers or tools."
            )
    return "\n\n".join(sections)


def _current_player_name(turn: dict[str, Any]) -> str:
    player = turn.get("player")
    if not isinstance(player, dict):
        return ""
    return str(player.get("name") or "").strip()


def _mentions_player_name(user_content: str, player_name: str) -> bool:
    content = str(user_content or "")
    name = str(player_name or "").strip()
    if not content or not name:
        return False
    return bool(re.search(rf"(?i)(?<![\w.-])@?{re.escape(name)}(?![\w.-])", content))


def _mentions_mcp(user_content: str) -> bool:
    normalized = str(user_content or "").lower()
    return "mcp" in normalized or "模型上下文协议" in normalized


def _asks_read_only_explanation(user_content: str) -> bool:
    normalized = str(user_content or "").lower()
    if "只读" not in normalized and "read-only" not in normalized and "read only" not in normalized:
        return False
    return any(marker in normalized for marker in ("什么", "听不懂", "解释", "意思", "mean", "explain", "不懂"))


def _is_plain_greeting(user_content: str) -> bool:
    normalized = re.sub(r"[\s,，。.!！?？~～]+", "", str(user_content or "").lower())
    return normalized in {"你好", "您好", "嗨", "hi", "hello", "hey", "hellomina", "himina", "你好mina"}


def _has_only_answer_constraint(user_content: str) -> bool:
    normalized = str(user_content or "").lower()
    return any(
        marker in normalized
        for marker in (
            "只回答",
            "只回复",
            "仅回答",
            "仅回复",
            "只输出",
            "only answer",
            "answer only",
            "respond only",
            "output only",
        )
    )


def _command_policy_reminder(user_content: str) -> str:
    content = str(user_content or "").strip()
    if not content:
        return ""
    if _asks_for_confirmation_before_action(content):
        return ""
    if normalize_read_only_command(content) is not None:
        return COMMAND_POLICY_REMINDER
    if not _has_command_request_marker(content):
        return ""
    return COMMAND_POLICY_REMINDER if _read_only_command_mentions(content) else ""


def _command_output_recall_reminder(user_content: str) -> str:
    normalized = str(user_content or "").lower()
    if not normalized:
        return ""
    markers = (
        "命令输出",
        "输出是什么",
        "输出内容",
        "输出字符串",
        "返回了什么",
        "command output",
        "output of",
        "what did the command",
        "what did command",
    )
    return COMMAND_OUTPUT_RECALL_REMINDER if any(marker in normalized for marker in markers) else ""


def _asks_for_confirmation_before_action(user_content: str) -> bool:
    normalized = re.sub(r"\s+", "", str(user_content or "").lower())
    if not normalized:
        return False
    explicit_markers = (
        "先问我",
        "先问",
        "先确认",
        "问我要不要",
        "问我是否",
        "不要直接查询",
        "不要直接执行",
        "不要直接搜索",
        "不要直接保存",
        "不要直接记住",
        "askmefirst",
        "askfirst",
        "confirmfirst",
        "confirmbefore",
    )
    if any(marker in normalized for marker in explicit_markers):
        return True
    return "先" in normalized and ("问" in normalized or "确认" in normalized)


def build_read_only_command_tool_repair(user_content: str) -> str:
    if not _command_policy_reminder(user_content):
        return ""
    return (
        "Tool call repair:\n"
        "- The previous assistant draft answered a read-only Minecraft command request without a tool call.\n"
        "- Discard that draft. In the next assistant message, call run_read_only_command for the command requested by the final user message.\n"
        "- Do not answer with text like 正在查询 unless the tool call is present in the same assistant message.\n"
        "- Do not answer from snapshot, recent command results, or conversation history."
    )


def _has_command_request_marker(content: str) -> bool:
    normalized = str(content or "").lower()
    return any(
        marker in normalized
        for marker in (
            "执行",
            "运行",
            "调用",
            "查询",
            "查找",
            "找",
            "找一下",
            "定位",
            "只读命令",
            "命令查询",
            "locate",
            "find",
            "where is",
            "where's",
            "run",
            "execute",
            "call",
            "use the command",
            "run command",
            "execute command",
            "read-only command",
        )
    )


def _read_only_command_mentions(content: str) -> bool:
    tokens = [token.lstrip("/") for token in re.split(r"[^a-z0-9_:.\-/#]+", content.lower()) if token]
    for index in range(len(tokens)):
        for size in (1, 2, 3):
            candidate = " ".join(tokens[index:index + size])
            if normalize_read_only_command(candidate) is not None:
                return True
    return _read_only_lookup_target_mentions(content)


def _read_only_lookup_target_mentions(content: str) -> bool:
    normalized = str(content or "").lower()
    return any(
        marker in normalized
        for marker in (
            "村庄",
            "village",
            "要塞",
            "stronghold",
            "末地传送门",
            "末影之眼",
            "end portal",
            "end_portal",
            "生物群系",
            "群系",
            "biome",
        )
    )


def _memory_save_policy_reminder(user_content: str) -> str:
    normalized = str(user_content or "").lower()
    if not normalized:
        return ""
    if any(
        marker in normalized
        for marker in (
            "记住",
            "记下",
            "记好",
            "保存",
            "remember",
            "save this",
            "note that",
        )
    ):
        return MEMORY_WRITE_POLICY_REMINDER
    return ""


def _render_agent_memory(memories: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in memories:
        scope = item.get("scope")
        label = item.get("label")
        content = " ".join(str(item.get("content") or "").split())
        if content:
            lines.append(f"- {scope}/{label}: {content}")
    return "\n".join(lines)


def _conversation_history_messages(
    history: list[dict[str, Any]],
    *,
    current_request_id: str,
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for row in history:
        if current_request_id and str(row.get("request_id") or "") == current_request_id:
            continue
        role = str(row.get("role") or "")
        if role not in {"user", "assistant"}:
            continue
        content = " ".join(str(row.get("content") or "").split())
        if content:
            messages.append({"role": role, "content": content})
    return messages


def _render_followup_focus(
    history: list[dict[str, Any]],
    *,
    current_request_id: str,
    user_content: str,
) -> str:
    if not _is_short_followup(user_content):
        return ""
    latest_assistant = _latest_history_message(history, current_request_id=current_request_id, role="assistant")
    if not latest_assistant:
        return ""
    return "\n".join(
        [
            "Current follow-up focus:",
            f"- The latest assistant message before this turn was: {_quote_for_prompt(latest_assistant)}",
            "- The current player message is a short follow-up; interpret it primarily against that latest assistant message, not older history.",
            "- If the latest assistant offered to search/query/check/locate, carry out that offered lookup with the appropriate model-facing tool when available.",
            "- If the latest assistant asked whether to remember/save a stable fact, use memory_write for an affirmative answer.",
            "- If the player says 继续, continue the latest topic; for farms/redstone/tutorials, use web_search before exact mechanics or build steps.",
        ]
    )


def _render_history_compatibility_warning(history: list[dict[str, Any]]) -> str:
    if not history:
        return ""
    text = "\n".join(str(row.get("content") or "") for row in history)
    lowered = text.lower()
    legacy_markers = (
        "分身",
        "假人",
        "小机器人",
        "砍树",
        "跟随",
        "保护你",
        "body",
        "follow you",
        "chop trees",
        "protect you",
    )
    if not any(marker in lowered for marker in legacy_markers):
        return ""
    return "\n".join(
        [
            "History compatibility warning:",
            "- Some older conversation messages may mention removed body/puppet capabilities such as a separate character, following, protection, mining, attacking, or chopping trees.",
            "- Treat those older messages only as historical conversation, not current capability or truth.",
            "- Current capabilities are text conversation, web_search knowledge, memory, observed Minecraft state, and tightly constrained read-only Minecraft commands.",
            "- Older assistant answers about Minecraft mechanics can be stale or wrong; use web_search for current farm/redstone/tutorial advice.",
        ]
    )


def _is_short_followup(user_content: str) -> bool:
    normalized = re.sub(r"[\s,，。.!！?？~～]+", "", str(user_content or "").lower())
    return normalized in {
        "需要",
        "要",
        "是",
        "是的",
        "对",
        "对的",
        "好",
        "好的",
        "可以",
        "继续",
        "yes",
        "y",
        "yeah",
        "yep",
        "sure",
        "ok",
        "okay",
        "continue",
        "goon",
    }


def _latest_history_message(history: list[dict[str, Any]], *, current_request_id: str, role: str) -> str:
    for row in reversed(history):
        if current_request_id and str(row.get("request_id") or "") == current_request_id:
            continue
        if str(row.get("role") or "") != role:
            continue
        content = " ".join(str(row.get("content") or "").split())
        if content:
            return content
    return ""


def _quote_for_prompt(value: str, limit: int = 700) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > limit:
        text = text[: limit - 3].rstrip() + "..."
    return json.dumps(text, ensure_ascii=False)


def _render_recent_action_results(action_results: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for row in action_results[-4:]:
        payload = _json_object(row.get("payload_json"))
        action_name = str(row.get("action_name") or payload.get("name") or payload.get("action_name") or "action")
        status = str(payload.get("status") or "unknown")
        command_results = payload.get("command_results")
        output_parts: list[str] = []
        if isinstance(command_results, list):
            for command_result in command_results[:3]:
                if not isinstance(command_result, dict):
                    continue
                command = str(command_result.get("command") or "").strip()
                outputs = command_result.get("outputs")
                rendered_outputs = _string_items(outputs, limit=3)
                if command or rendered_outputs:
                    rendered_output_strings = [_quote_for_prompt(output, limit=240) for output in rendered_outputs]
                    output_parts.append(
                        "command="
                        + (command or "<unknown>")
                        + " full_output_string="
                        + " | ".join(rendered_output_strings)
                    )
        error = str(payload.get("error") or "").strip()
        if error:
            output_parts.append("error=" + error)
        if not output_parts:
            continue
        summary = "; ".join(output_parts)
        lines.append(
            f"- request={row.get('request_id')} action={action_name} status={status} "
            f"success={payload.get('command_success')} {summary[:700]}"
        )
    return "\n".join(lines)


def _write_command_refusal_hint(user_content: str) -> str:
    normalized = " ".join(str(user_content or "").lower().replace("/", " / ").split())
    if not normalized:
        return ""
    normalized_for_write_detection = _remove_non_write_portal_terms(normalized)
    write_markers = (
        " setblock",
        " fill",
        " fillbiome",
        " clone",
        " place ",
        " time set",
        " weather clear",
        " weather rain",
        " weather thunder",
        " tp",
        " teleport",
        " gamemode",
        " defaultgamemode",
        " difficulty",
        " gamerule",
        " give",
        " summon",
        " kill",
        " clear",
        " execute",
        " op",
        " deop",
        " ban",
        " ban-ip",
        " whitelist",
        " stop",
        " save-all",
        " save-off",
        " save-on",
        "删掉",
        "删除",
        "放置",
        "传送",
        "改成",
        "设成",
    )
    padded = " " + normalized_for_write_detection + " "
    if not any(marker in padded or marker in normalized_for_write_detection for marker in write_markers):
        return ""
    return (
        "Current user message asks for a Minecraft write-capable, low-level, or banned command/action. "
        "Refuse directly; do not call tools. Do not repeat the requested command name, coordinates, selector, "
        "syntax, command whitelist, or workaround. For Chinese, reply exactly: "
        f"{UNSAFE_WRITE_REFUSAL}"
    )


def _remove_non_write_portal_terms(value: str) -> str:
    cleaned = str(value or "")
    for phrase in (
        "末地传送门",
        "下界传送门",
        "传送门",
        "末地折跃门",
        "折跃门",
        "end portal",
        "end_portal",
        "nether portal",
        "portal",
        "gateway",
    ):
        cleaned = cleaned.replace(phrase, " ")
    return " ".join(cleaned.split())


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        payload = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _string_items(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        text = " ".join(str(item).split())
        if text:
            items.append(text[:220])
        if len(items) >= limit:
            break
    return items


def _world_id(turn: dict[str, Any]) -> str | None:
    value = turn.get("world_id") or turn.get("world")
    if value:
        return str(value)
    snapshot = turn.get("snapshot")
    if not isinstance(snapshot, dict):
        return None
    value = snapshot.get("world_id") or snapshot.get("world")
    if value:
        return str(value)
    player_state = snapshot.get("player_state")
    if isinstance(player_state, dict) and player_state.get("dimension"):
        return str(player_state.get("dimension"))
    return None


def build_target_summary(snapshot: dict[str, Any]) -> str:
    lines: list[str] = []
    nearby_blocks = snapshot.get("nearby_blocks")
    player_state = snapshot.get("player_state") if isinstance(snapshot.get("player_state"), dict) else {}
    blocks = _flatten_blocks(nearby_blocks)
    if blocks:
        lines.append("Nearby notable blocks for observation:")
        for block in blocks[:12]:
            if not isinstance(block, dict):
                continue
            compact = _compact_block_target(block, player_state)
            block_pos = f"block=({compact.get('x')},{compact.get('y')},{compact.get('z')})"
            direction = compact.get("relative_direction") or "unknown"
            lines.append(
                f"- {compact.get('category')} {compact.get('block')} {block_pos} "
                f"distance={compact.get('distance')} direction={direction} "
                f"approach_available={compact.get('approach_available')}"
            )
    return "\n".join(lines)


def build_observation_highlights(turn: dict[str, Any]) -> str:
    snapshot = turn.get("snapshot") if isinstance(turn.get("snapshot"), dict) else {}
    completed_advancements = _compact_completed_advancements(snapshot.get("completed_advancements"), limit=24)
    if not completed_advancements:
        return ""
    labels: list[str] = []
    for advancement in completed_advancements:
        title = str(advancement.get("title") or "").strip()
        advancement_id = str(advancement.get("id") or "").strip()
        if title and advancement_id and title != advancement_id:
            labels.append(f"{title} ({advancement_id})")
        elif title:
            labels.append(title)
        elif advancement_id:
            labels.append(advancement_id)
    if not labels:
        return ""
    return "Completed visible advancements observed for current player: " + "; ".join(labels)


def build_context_summary(turn: dict[str, Any]) -> str:
    snapshot = turn.get("snapshot") or {}
    player_state = snapshot.get("player_state") if isinstance(snapshot.get("player_state"), dict) else {}
    world_state = snapshot.get("world_state") if isinstance(snapshot.get("world_state"), dict) else {}
    server_state = snapshot.get("server_state") if isinstance(snapshot.get("server_state"), dict) else {}
    permissions = turn.get("permissions") or {}
    recent_events = turn.get("recent_events") if isinstance(turn.get("recent_events"), list) else []
    completed_advancements = (
        snapshot.get("completed_advancements")
        if isinstance(snapshot.get("completed_advancements"), list)
        else []
    )
    nearby_entities = snapshot.get("nearby_entities") if isinstance(snapshot.get("nearby_entities"), list) else []
    inventory = snapshot.get("inventory") if isinstance(snapshot.get("inventory"), list) else []
    environment = snapshot.get("environment") if isinstance(snapshot.get("environment"), dict) else {}
    nearby_blocks = _flatten_blocks(snapshot.get("nearby_blocks"))
    logs = [block for block in nearby_blocks if block.get("category") == "log"][:12]
    hostile = [entity for entity in nearby_entities if entity.get("category") == "hostile"][:8]
    mobs = [
        entity
        for entity in nearby_entities
        if entity.get("category") in {"passive", "neutral"} and not entity.get("item")
    ][:8]
    dropped_items = [entity for entity in nearby_entities if entity.get("item")][:8]
    player_context: dict[str, Any] = turn.get("player") or {}
    if str(turn.get("trigger") or "") == "companion_tick":
        player_context = {"present": bool(player_context)}
    server_context = _compact_server_state(server_state)
    payload = {
        "trigger": turn.get("trigger"),
        "server_id": turn.get("server_id"),
        "world_id": turn.get("world_id"),
        "player": player_context,
        "permissions": permissions,
        "player_state": {
            "health": player_state.get("health"),
            "max_health": player_state.get("max_health"),
            "health_points": player_state.get("health"),
            "max_health_points": player_state.get("max_health"),
            "health_hearts": _half_health(player_state.get("health")),
            "max_health_hearts": _half_health(player_state.get("max_health")),
            "food": player_state.get("food"),
            "armor": player_state.get("armor"),
            "experience_level": player_state.get("experience_level"),
            "total_experience": player_state.get("total_experience"),
            "effects": _compact_effects(player_state.get("effects")),
            "game_mode": player_state.get("game_mode"),
            "dimension": player_state.get("dimension"),
            "x": player_state.get("x"),
            "y": player_state.get("y"),
            "z": player_state.get("z"),
            "yaw": player_state.get("yaw"),
            "pitch": player_state.get("pitch"),
            "facing_direction": _facing_direction(player_state.get("yaw")),
        },
        "hazards": {
            "on_fire": player_state.get("on_fire"),
            "in_lava": player_state.get("in_lava"),
            "underwater": player_state.get("underwater"),
            "on_ground": player_state.get("on_ground"),
        },
        "world_state": {
            "day_time": world_state.get("day_time"),
            "day_count": world_state.get("day_count"),
            "time_of_day": _minecraft_time_of_day(world_state.get("day_time")),
            "difficulty": world_state.get("difficulty"),
            "raining": world_state.get("raining"),
            "thundering": world_state.get("thundering"),
            "weather": _weather_label(world_state),
            "dimension": world_state.get("dimension"),
            "seed": world_state.get("seed"),
            "spawn_x": world_state.get("spawn_x"),
            "spawn_y": world_state.get("spawn_y"),
            "spawn_z": world_state.get("spawn_z"),
            "player_distance_from_spawn": world_state.get("player_distance_from_spawn"),
            "online_players": world_state.get("online_players"),
            "online_player_names": _string_items(world_state.get("online_player_names"), limit=20),
            "pvp_allowed": world_state.get("pvp_allowed"),
            "command_blocks_enabled": world_state.get("command_blocks_enabled"),
        },
        "candidate_logs": [_compact_block_target(block, player_state) for block in logs],
        "nearby_hostiles": [_compact_entity_target(entity, player_state) for entity in hostile],
        "nearby_mobs": [_compact_entity_target(entity, player_state) for entity in mobs],
        "nearby_items": [_compact_entity_target(entity, player_state) for entity in dropped_items],
    }
    compact_events = [_compact_recent_event(event) for event in recent_events[:16] if isinstance(event, dict)]
    compact_events = [event for event in compact_events if event]
    if compact_events:
        payload["recent_events"] = compact_events
    compact_advancements = _compact_completed_advancements(completed_advancements, limit=80)
    if compact_advancements:
        payload["completed_advancement_titles"] = [
            advancement["title"]
            for advancement in compact_advancements
            if advancement.get("title")
        ]
        payload["completed_advancements"] = compact_advancements
    if server_context:
        payload["server_state"] = server_context
    distance_display = _distance_display(world_state.get("player_distance_from_spawn"))
    if distance_display:
        payload["world_state"]["player_distance_from_spawn_display"] = distance_display
    selected_item = _selected_inventory_item(inventory)
    if selected_item:
        payload["selected_item"] = selected_item
    compact_inventory = _compact_inventory(inventory)
    if compact_inventory:
        payload["inventory_items"] = compact_inventory
    compact_environment = _compact_environment(environment)
    if compact_environment:
        payload["environment"] = compact_environment
    return json.dumps(_drop_none(payload), ensure_ascii=False)


def _compact_server_state(server_state: dict[str, Any]) -> dict[str, Any]:
    if not server_state:
        return {}
    keys = (
        "minecraft_version",
        "server_mod_name",
        "mina_mod_version",
        "fabric_loader_version",
        "fabric_api_version",
        "dedicated_server",
        "singleplayer",
        "online_mode",
        "hardcore",
        "default_game_mode",
        "forced_game_mode",
        "motd",
        "server_port",
        "max_players",
        "view_distance",
        "simulation_distance",
        "allow_flight",
        "whitelist_enabled",
        "enforce_whitelist",
        "resource_pack_required",
        "modded_status",
    )
    return {key: server_state.get(key) for key in keys if server_state.get(key) is not None}


def _compact_recent_event(event: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "type",
        "server_tick",
        "id",
        "title",
        "description",
        "advancement_type",
        "from",
        "to",
    )
    return {key: event.get(key) for key in keys if event.get(key) not in {None, ""}}


def _compact_advancement(advancement: dict[str, Any]) -> dict[str, Any]:
    keys = ("id", "title", "description", "advancement_type")
    return {key: advancement.get(key) for key in keys if advancement.get(key) not in {None, ""}}


def _compact_completed_advancements(value: Any, *, limit: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    compact: list[dict[str, Any]] = []
    for advancement in value:
        if not isinstance(advancement, dict):
            continue
        if _is_recipe_advancement(advancement):
            continue
        item = _compact_advancement(advancement)
        if item:
            compact.append(item)
        if len(compact) >= limit:
            break
    return compact


def _is_recipe_advancement(advancement: dict[str, Any]) -> bool:
    advancement_id = str(advancement.get("id") or "")
    return advancement_id.startswith("minecraft:recipes/")


def _companion_tick_prompt(turn: dict[str, Any]) -> str:
    reason = _companion_tick_alert_reason(turn)
    if reason:
        return (
            "这是一次被动提醒检查。当前观察状态显示及时提醒理由："
            + reason
            + "。请用玩家最近使用的语言简短提醒玩家，不要调用工具。"
            + "涉及生命值时请使用“点生命值”或“颗心”，不要说“格血”或“心生命值”。"
        )
    return "这是一次被动提醒检查。如果没有重要、及时的理由要提醒玩家，请回复空字符串；如果需要提醒，请使用玩家最近使用的语言。"


def _companion_tick_alert_reason(turn: dict[str, Any]) -> str:
    snapshot = turn.get("snapshot") if isinstance(turn.get("snapshot"), dict) else {}
    player_state = snapshot.get("player_state") if isinstance(snapshot.get("player_state"), dict) else {}
    health = _float_value(player_state.get("health"))
    max_health = _float_value(player_state.get("max_health")) or 20.0
    if health is not None and health <= max(6.0, max_health * 0.5):
        return (
            "玩家生命值较低（"
            f"{_format_number(health)}/{_format_number(max_health)} health points，"
            f"约 {_format_number(health / 2.0)}/{_format_number(max_health / 2.0)} 颗心）"
        )
    nearby_entities = snapshot.get("nearby_entities") if isinstance(snapshot.get("nearby_entities"), list) else []
    hostiles = [entity for entity in nearby_entities if isinstance(entity, dict) and entity.get("category") == "hostile"]
    if hostiles:
        nearest = hostiles[0]
        entity_type = str(nearest.get("type") or "hostile entity")
        distance = _float_value(nearest.get("distance"))
        if distance is not None:
            return f"附近有敌对生物 {entity_type}，距离约 {_format_number(distance)} 格"
        return f"附近有敌对生物 {entity_type}"
    return ""


def _float_value(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _drop_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _drop_none(nested)
            for key, nested in value.items()
            if nested is not None
        }
    if isinstance(value, list):
        return [_drop_none(item) for item in value]
    return value


def _distance_display(value: Any) -> str | None:
    distance = _float_value(value)
    if distance is None:
        return None
    return f"{_format_number(distance)} 格"


def _weather_label(world_state: dict[str, Any]) -> str | None:
    if not world_state:
        return None
    if world_state.get("thundering") is True:
        return "thunder"
    if world_state.get("raining") is True:
        return "rain"
    if world_state.get("raining") is False or world_state.get("thundering") is False:
        return "clear"
    return None


def _minecraft_time_of_day(day_time: Any) -> str | None:
    try:
        ticks = int(day_time) % 24000
    except (TypeError, ValueError):
        return None
    if ticks < 6000:
        return "morning"
    if ticks < 12000:
        return "daytime"
    if ticks < 13000:
        return "sunset"
    if ticks < 18000:
        return "night"
    if ticks < 23000:
        return "late_night"
    return "sunrise"


def _half_health(value: Any) -> float | int | None:
    parsed = _float_value(value)
    if parsed is None:
        return None
    half = parsed / 2.0
    return int(half) if half.is_integer() else half


def _facing_direction(value: Any) -> str | None:
    yaw = _float_value(value)
    if yaw is None:
        return None
    normalized = yaw % 360.0
    if normalized < 45.0 or normalized >= 315.0:
        return "south"
    if normalized < 135.0:
        return "west"
    if normalized < 225.0:
        return "north"
    return "east"


def _flatten_blocks(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        blocks: list[dict[str, Any]] = []
        for nested in value.values():
            blocks.extend(_flatten_blocks(nested))
        return blocks
    return []


def _selected_inventory_item(inventory: list[Any]) -> dict[str, Any]:
    for item in inventory:
        if isinstance(item, dict) and item.get("selected") is True:
            return {
                "slot": item.get("slot"),
                "item": item.get("item"),
                "count": item.get("count"),
                "name": item.get("name"),
            }
    return {}


def _compact_inventory(inventory: list[Any], *, limit: int = 20) -> list[dict[str, Any]]:
    totals: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for raw_item in inventory:
        if not isinstance(raw_item, dict):
            continue
        item_id = str(raw_item.get("item") or "").strip()
        if not item_id:
            continue
        count = _int_value(raw_item.get("count"))
        entry = totals.get(item_id)
        if entry is None:
            entry = {
                "item": item_id,
                "count": 0,
                "slots": [],
            }
            if raw_item.get("name") is not None:
                entry["name"] = raw_item.get("name")
            totals[item_id] = entry
            order.append(item_id)
        if count is not None:
            entry["count"] += count
        slot = raw_item.get("slot")
        if slot is not None:
            entry["slots"].append(slot)
        if raw_item.get("selected") is True:
            entry["selected"] = True
    items = [totals[item_id] for item_id in order[:limit]]
    for item in items:
        if item.get("count") == 0:
            item.pop("count", None)
        if not item.get("slots"):
            item.pop("slots", None)
    return items


def _int_value(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed


def _compact_effects(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    effects: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        effect_id = item.get("id") or item.get("effect")
        if not effect_id:
            continue
        compact_effect = {
            "id": effect_id,
            "effect": item.get("effect"),
            "amplifier": item.get("amplifier"),
        }
        duration = item.get("duration")
        if isinstance(duration, int | float):
            compact_effect["duration_ticks"] = duration
            compact_effect["duration_seconds"] = round(float(duration) / 20.0, 1)
        elif duration is not None:
            compact_effect["duration_ticks"] = duration
        effects.append(compact_effect)
        if len(effects) >= 8:
            break
    return effects


def _compact_environment(environment: dict[str, Any]) -> dict[str, Any]:
    compact = {
        "block_at_feet": environment.get("block_at_feet"),
        "block_below": environment.get("block_below"),
        "standing_on_block": environment.get("block_below"),
        "biome": environment.get("biome"),
        "light": environment.get("light"),
        "sky_visible": environment.get("sky_visible"),
    }
    return {key: value for key, value in compact.items() if value is not None}


def _compact_block_target(block: dict[str, Any], player_state: dict[str, Any] | None = None) -> dict[str, Any]:
    compact = {
        "block": block.get("block"),
        "category": block.get("category"),
        "x": block.get("x"),
        "y": block.get("y"),
        "z": block.get("z"),
        "distance": block.get("distance"),
        "approach_available": all(key in block for key in ("approach_x", "approach_y", "approach_z")),
    }
    compact.update(_relative_fields(player_state or {}, block, center=True))
    return compact


def _compact_entity_target(entity: dict[str, Any], player_state: dict[str, Any]) -> dict[str, Any]:
    compact = {
        "type": entity.get("type"),
        "name": entity.get("name"),
        "category": entity.get("category"),
        "distance": entity.get("distance"),
        "x": entity.get("x"),
        "y": entity.get("y"),
        "z": entity.get("z"),
        "health": entity.get("health"),
        "max_health": entity.get("max_health"),
        "item": entity.get("item"),
        "count": entity.get("count"),
        "item_category": entity.get("item_category"),
    }
    compact.update(_relative_fields(player_state, entity, center=False))
    return compact


def _relative_fields(
    player_state: dict[str, Any], target: dict[str, Any], *, center: bool
) -> dict[str, Any]:
    origin_x = _float_value(player_state.get("x"))
    origin_y = _float_value(player_state.get("y"))
    origin_z = _float_value(player_state.get("z"))
    target_x = _float_value(target.get("center_x") if center else target.get("x"))
    target_y = _float_value(target.get("center_y") if center else target.get("y"))
    target_z = _float_value(target.get("center_z") if center else target.get("z"))
    if target_x is None:
        target_x = _float_value(target.get("x"))
    if target_y is None:
        target_y = _float_value(target.get("y"))
    if target_z is None:
        target_z = _float_value(target.get("z"))
    if origin_x is None or origin_z is None or target_x is None or target_z is None:
        return {}
    dx = target_x - origin_x
    dz = target_z - origin_z
    fields: dict[str, Any] = {
        "relative_direction": _horizontal_direction(dx, dz),
        "relative_x": _rounded_delta(dx),
        "relative_z": _rounded_delta(dz),
    }
    if origin_y is not None and target_y is not None:
        dy = target_y - origin_y
        fields["relative_y"] = _rounded_delta(dy)
        vertical = _vertical_relation(dy)
        if vertical:
            fields["relative_vertical"] = vertical
    return fields


def _horizontal_direction(dx: float, dz: float) -> str:
    abs_dx = abs(dx)
    abs_dz = abs(dz)
    if abs_dx < 0.25 and abs_dz < 0.25:
        return "here"
    if abs_dx >= abs_dz * 2:
        return "east" if dx > 0 else "west"
    if abs_dz >= abs_dx * 2:
        return "south" if dz > 0 else "north"
    north_south = "south" if dz > 0 else "north"
    east_west = "east" if dx > 0 else "west"
    return north_south + east_west


def _vertical_relation(dy: float) -> str | None:
    if dy > 1.0:
        return "above"
    if dy < -1.0:
        return "below"
    return "same_level"


def _rounded_delta(value: float) -> float | int:
    rounded = round(value, 2)
    return int(rounded) if float(rounded).is_integer() else rounded
