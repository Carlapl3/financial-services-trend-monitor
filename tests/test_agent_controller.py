"""
Unit test for the ReAct agent loop.

Verifies that AgentController correctly executes a scripted tool sequence
and records a complete reasoning trace — without any LLM calls.
"""

from src.agent.controller import AgentController


def test_react_loop_scripted_sequence():
    """Agent should call tools in the order the callback prescribes, then stop."""

    # ── Scripted LLM responses (returned in order) ────────────────────
    responses = iter([
        {
            "thought": "Check what items are in storage.",
            "action": "check_duplicates",
            "action_input": {},
        },
        {
            "thought": "Storage has items. Render a digest.",
            "action": "render_digest",
            "action_input": {"days_lookback": 7},
        },
        {
            "thought": "Digest ready.",
            "final_answer": "Digest ready.",
        },
    ])

    def mock_callback(goal, reasoning_trace):
        return next(responses)

    # ── Minimal tool stubs ────────────────────────────────────────────
    tools = {
        "check_duplicates": {
            "function": lambda: {"total_items": 5, "unique_urls": 5},
            "schema": {},
        },
        "render_digest": {
            "function": lambda days_lookback: {"items_included": 2},
            "schema": {},
        },
    }

    controller = AgentController(tools=tools)
    result = controller.run(goal="Generate a digest", llm_callback=mock_callback)

    # ── Assertions ────────────────────────────────────────────────────
    assert result["success"] is True
    assert result["stop_reason"] == "goal_completed"
    assert result["steps_taken"] == 2
    assert result["final_answer"] == "Digest ready."

    trace = result["reasoning_trace"]
    assert len(trace) == 3
    assert trace[0]["action"] == "check_duplicates"
    assert trace[1]["action"] == "render_digest"
    assert trace[2]["action"] == "finish"
