from __future__ import annotations

from mina_agent.schemas import ToolResult
from mina_agent.turn_runtime import TurnRuntimeState


def test_turn_runtime_collects_actions_and_tool_observations() -> None:
    state = TurnRuntimeState(request_id="req-1", player_id="player-1", messages=[])

    actions = state.collect_result_actions(
        ToolResult(
            content="{}",
            action={"id": "a1", "name": "run_read_only_command"},
            actions=[{"id": "a2", "name": "send_player_message"}],
        )
    )
    state.append_tool_observation("call-1", "{}")

    assert actions == state.actions
    assert [action["id"] for action in state.actions] == ["a1", "a2"]
    assert state.messages == [{"role": "tool", "tool_call_id": "call-1", "content": "{}"}]
