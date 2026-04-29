from __future__ import annotations

import json

from mina_agent.policy import ResponsePolicyRuntime, is_tool_error, minecraft_chat_text


def test_minecraft_chat_text_strips_markdown_and_emoji() -> None:
    assert minecraft_chat_text("**你好** `Mina` ✨") == "你好 Mina"


def test_policy_repairs_write_command_advice_then_falls_back_to_safe_refusal() -> None:
    policy = ResponsePolicyRuntime()

    first = policy.review_final_content("我不能执行，但你可以自己运行 setblock 命令处理坐标 2 80 0。", can_repair=True)
    second = policy.review_final_content("我不能执行，但你可以自己运行 /setblock 2 80 0 air。", can_repair=True)

    assert first.needs_repair
    assert first.repair_reason == "unsafe_write_command_advice"
    assert not second.needs_repair
    assert "/setblock" not in second.content
    assert "不能执行或提供写入世界的命令" in second.content


def test_policy_repairs_memory_claim_until_memory_write_succeeds() -> None:
    policy = ResponsePolicyRuntime()

    first = policy.review_final_content("记住了，你的基地在樱花林旁边。", can_repair=True)
    policy.note_successful_tool_result("memory_write", json.dumps({"ok": True}))
    second = policy.review_final_content("已记住，你的基地在樱花林旁边。", can_repair=True)

    assert first.needs_repair
    assert first.repair_reason == "memory_claim_without_write"
    assert not second.needs_repair
    assert "樱花林" in second.content


def test_policy_normalizes_successful_memory_write_ack() -> None:
    policy = ResponsePolicyRuntime()
    policy.note_successful_tool_result("memory_write", json.dumps({"ok": True}))

    review = policy.review_final_content("已记好了！你的基地在樱花林旁边。", can_repair=True)

    assert not review.needs_repair
    assert review.content.startswith("已记住。")
    assert "樱花林" in review.content


def test_is_tool_error_reads_standard_tool_result_envelope() -> None:
    assert is_tool_error(json.dumps({"ok": False, "error": "missing query"}))
    assert not is_tool_error(json.dumps({"ok": True}))
    assert not is_tool_error("plain text")
