"""
Unit tests for agent entrypoint wiring.

Verifies that running the CLI without a subcommand invokes AgentController.run()
with TOOL_REGISTRY and an llm_callback, and that existing subcommands still work.
"""

import sys
from unittest.mock import patch, MagicMock

import pytest

from src.agent.controller import AgentController


def test_default_cli_invokes_agent_controller():
    """Running main() with no subcommand should invoke AgentController.run()."""
    mock_result = {
        "success": True,
        "final_answer": "Collected and rendered 3 items.",
        "stop_reason": "goal_completed",
        "steps_taken": 3,
        "elapsed_time": 5.2,
        "reasoning_trace": [],
    }

    with patch.object(AgentController, "run", return_value=mock_result) as mock_run, \
         patch("src.agent.llm_callback.OpenAI"), \
         patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), \
         patch("sys.argv", ["cron_entrypoints"]):

        from src.scheduler.cron_entrypoints import main

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        mock_run.assert_called_once()

        call_args = mock_run.call_args
        goal = call_args.kwargs.get("goal") or call_args[0][0]
        assert "trend" in goal.lower()

        llm_callback = call_args.kwargs.get("llm_callback") or call_args[0][1]
        assert callable(llm_callback)


def test_default_cli_exits_1_on_agent_failure():
    """When AgentController.run() returns success=False, exit code should be 1."""
    mock_result = {
        "success": False,
        "final_answer": None,
        "stop_reason": "max_steps_reached (6)",
        "steps_taken": 6,
        "elapsed_time": 45.0,
        "reasoning_trace": [],
    }

    with patch.object(AgentController, "run", return_value=mock_result) as mock_run, \
         patch("src.agent.llm_callback.OpenAI"), \
         patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), \
         patch("sys.argv", ["cron_entrypoints"]):

        from src.scheduler.cron_entrypoints import main

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1
        mock_run.assert_called_once()


def test_collect_subcommand_still_works():
    """Existing 'collect' subcommand should still invoke run_collection."""
    with patch("src.scheduler.cron_entrypoints.run_collection") as mock_collect, \
         patch("sys.argv", ["cron_entrypoints", "collect"]):

        mock_collect.return_value = {"status": "success"}

        from src.scheduler.cron_entrypoints import main

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        mock_collect.assert_called_once()
