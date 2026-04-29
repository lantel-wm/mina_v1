from __future__ import annotations

import json

from mina_agent.policy import (
    ResponsePolicyRuntime,
    is_tool_error,
    minecraft_chat_text,
    normalize_health_unit_claims,
    strip_player_name_address,
)


def test_minecraft_chat_text_strips_markdown_and_emoji() -> None:
    assert minecraft_chat_text("**你好** `Mina` ✨") == "你好 Mina"


def test_minecraft_chat_text_strips_emoji_variation_residue() -> None:
    assert minecraft_chat_text("生命值: 20 ❤️") == "生命值: 20"
    assert minecraft_chat_text("危险 ⚠️ 请后退") == "危险 请后退"


def test_minecraft_chat_text_collapses_markdown_lists_to_plain_chat() -> None:
    content = """
    **状态**
    - 坐标：X=0.5
    - 生命值：20
    """

    assert minecraft_chat_text(content) == "状态 坐标：X=0.5 生命值：20"


def test_minecraft_chat_text_strips_process_preamble() -> None:
    assert minecraft_chat_text("我来看看你的位置和附近情况。附近有一只苦力怕。") == "附近有一只苦力怕。"
    assert minecraft_chat_text("Let me check your current surroundings. There is a Creeper nearby.") == "There is a Creeper nearby."


def test_minecraft_chat_text_strips_decorative_wave() -> None:
    assert minecraft_chat_text("我可以帮你查询世界状态～") == "我可以帮你查询世界状态"


def test_policy_replaces_write_command_advice_with_safe_refusal() -> None:
    policy = ResponsePolicyRuntime()

    review = policy.review_final_content("我不能执行，但你可以自己运行 setblock 命令处理坐标 2 80 0。", can_repair=True)

    assert not review.needs_repair
    assert "setblock" not in review.content
    assert "2 80 0" not in review.content
    assert "不能执行或提供写入世界的命令" in review.content


def test_policy_replaces_write_command_after_cjk_punctuation() -> None:
    policy = ResponsePolicyRuntime()

    review = policy.review_final_content("抱歉，setblock 属于写操作命令，我无法执行。", can_repair=True)

    assert not review.needs_repair
    assert "setblock" not in review.content
    assert "不能执行或提供写入世界的命令" in review.content


def test_policy_does_not_treat_clear_weather_as_clear_command() -> None:
    policy = ResponsePolicyRuntime()

    review = policy.review_final_content("当前天气晴朗（clear），没有下雨或打雷。", can_repair=True)

    assert not review.needs_repair
    assert "clear" in review.content
    assert "不能执行或提供写入世界的命令" not in review.content


def test_policy_still_replaces_ambiguous_clear_command_advice() -> None:
    policy = ResponsePolicyRuntime()

    review = policy.review_final_content("我不能执行，但你可以运行 /clear @p。", can_repair=True)

    assert not review.needs_repair
    assert "/clear" not in review.content
    assert "不能执行或提供写入世界的命令" in review.content


def test_policy_normalizes_health_points_misread_as_hearts() -> None:
    snapshot = {"player_state": {"health": 4, "max_health": 20}}

    content = normalize_health_unit_claims("你现在只剩4颗心，满值是20颗心。", snapshot)

    assert "4颗心" not in content
    assert "20颗心" not in content
    assert "4点生命值（约2颗心）" in content
    assert "20点生命值（约10颗心）" in content


def test_policy_normalizes_english_health_points_misread_as_hearts() -> None:
    snapshot = {"player_state": {"health": 4, "max_health": 20}}

    content = normalize_health_unit_claims("You have 4 hearts out of 20 hearts.", snapshot)

    assert "4 hearts" not in content
    assert "20 hearts" not in content
    assert "4 health points (about 2 hearts)" in content
    assert "20 health points (about 10 hearts)" in content


def test_policy_normalizes_ambiguous_chinese_health_grid_claim() -> None:
    snapshot = {"player_state": {"health": 4, "max_health": 20}}

    content = normalize_health_unit_claims("你生命值比较低，只有两格血。", snapshot)

    assert "格血" not in content
    assert "只有4点生命值（约2颗心）" in content


def test_policy_does_not_rewrite_non_remaining_health_grid_claim() -> None:
    snapshot = {"player_state": {"health": 16, "max_health": 20}}

    content = normalize_health_unit_claims("我刚才掉了两格血。", snapshot)

    assert content == "我刚才掉了两格血。"


def test_policy_normalizes_ambiguous_chinese_heart_health_claim() -> None:
    snapshot = {"player_state": {"health": 4, "max_health": 20}}

    content = normalize_health_unit_claims("你只有两心生命值了。", snapshot)

    assert "心生命值" not in content
    assert "只有4点生命值（约2颗心）" in content


def test_policy_strips_player_name_address_prefix() -> None:
    assert strip_player_name_address("mina_tester，你只有2颗心了。", "mina_tester") == "你只有2颗心了。"
    assert strip_player_name_address("你只有2颗心了。", "mina_tester") == "你只有2颗心了。"


def test_policy_repairs_memory_claim_until_memory_write_succeeds() -> None:
    policy = ResponsePolicyRuntime()

    first = policy.review_final_content("记住了，你的基地在樱花林旁边。", can_repair=True)
    policy.note_successful_tool_result("memory_write", json.dumps({"ok": True}))
    second = policy.review_final_content("已记住，你的基地在樱花林旁边。", can_repair=True)

    assert first.needs_repair
    assert first.repair_reason == "memory_claim_without_write"
    assert not second.needs_repair
    assert "樱花林" in second.content


def test_policy_replaces_repeated_memory_claim_without_write() -> None:
    policy = ResponsePolicyRuntime()

    first = policy.review_final_content("记住了，你的基地在樱花林旁边。", can_repair=True)
    second = policy.review_final_content("已经记住，你的基地在樱花林旁边。", can_repair=False)

    assert first.needs_repair
    assert not second.needs_repair
    assert "还没有把这条信息保存进记忆" in second.content
    assert "樱花林" not in second.content


def test_policy_allows_historical_memory_recall_reference() -> None:
    policy = ResponsePolicyRuntime()

    review = policy.review_final_content("你的基地在樱花林旁边，我之前已经记下了。", can_repair=True)

    assert not review.needs_repair
    assert review.content == "你的基地在樱花林旁边，我之前已经记下了。"


def test_policy_allows_already_remembered_recall_reference() -> None:
    policy = ResponsePolicyRuntime()

    review = policy.review_final_content("你的基地在樱花林旁边，我已经记住了。", can_repair=True)

    assert not review.needs_repair
    assert review.content == "你的基地在樱花林旁边，我已经记住了。"


def test_policy_allows_stored_memory_capability_reference() -> None:
    policy = ResponsePolicyRuntime()

    review = policy.review_final_content("我可以帮你查询游戏状态、找到已记住的基地位置，或者搜索网络信息。", can_repair=True)

    assert not review.needs_repair
    assert review.content == "我可以帮你查询游戏状态、找到已记住的基地位置，或者搜索网络信息。"


def test_policy_normalizes_successful_memory_write_ack() -> None:
    policy = ResponsePolicyRuntime()
    policy.note_successful_tool_result("memory_write", json.dumps({"ok": True}))

    review = policy.review_final_content("已记好了！你的基地在樱花林旁边。", can_repair=True)

    assert not review.needs_repair
    assert review.content.startswith("已记住。")
    assert "樱花林" in review.content


def test_policy_normalizes_save_only_memory_write_ack() -> None:
    policy = ResponsePolicyRuntime()
    policy.note_successful_tool_result("memory_write", json.dumps({"ok": True}))

    review = policy.review_final_content("已保存。", can_repair=True)

    assert not review.needs_repair
    assert review.content == "已记住。"


def test_is_tool_error_reads_standard_tool_result_envelope() -> None:
    assert is_tool_error(json.dumps({"ok": False, "error": "missing query"}))
    assert not is_tool_error(json.dumps({"ok": True}))
    assert not is_tool_error("plain text")
