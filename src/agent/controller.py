"""
Agent Controller - ReAct loop implementation for trend monitoring.

Implements the ReAct (Reasoning + Acting) pattern:
- Thought: Agent reasons about current state and next action
- Action: Agent selects and executes a tool
- Observation: Agent receives tool output

Includes guardrails: max steps, timeout.
"""

import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Callable
from pathlib import Path
import yaml


class AgentController:
    """
    Controls the ReAct agent loop with configurable limits.

    The agent iteratively:
    1. Thinks about the current state
    2. Selects an action (tool call)
    3. Observes the result
    4. Repeats until goal is reached or limits hit
    """

    def __init__(
        self,
        tools: Dict[str, Callable] = None,
        limits_config_path: Optional[str] = None
    ):
        """
        Initialize agent controller.

        Args:
            tools: Dictionary mapping tool names to callable functions
            limits_config_path: Path to agent_limits.yaml config
        """
        self.tools = tools or {}
        self.limits = self._load_limits(limits_config_path)

        # Runtime state
        self.steps_taken = 0
        self.start_time = None
        self.reasoning_trace: List[Dict[str, Any]] = []
        self.is_running = False

    def _load_limits(self, config_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Load agent limits from configuration file.

        Args:
            config_path: Path to agent_limits.yaml

        Returns:
            Dictionary with limit settings
        """
        # Default limits
        defaults = {
            "max_steps": 6,
            "timeout": 90
        }

        if config_path is None:
            config_dir = Path(__file__).parent.parent.parent / "config"
            config_path = config_dir / "agent_limits.yaml"
        else:
            config_path = Path(config_path)

        if not config_path.exists():
            return defaults

        try:
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
                return {**defaults, **config}
        except Exception:
            return defaults

    def register_tool(self, name: str, func: Callable, schema: Dict[str, Any] = None):
        """
        Register a tool for the agent to use.

        Args:
            name: Tool name (used in action selection)
            func: Callable that implements the tool
            schema: JSON schema describing tool parameters
        """
        self.tools[name] = {
            "function": func,
            "schema": schema or {}
        }

    def _check_limits(self) -> Optional[str]:
        """
        Check if any limits have been exceeded.

        Returns:
            Stop reason string if limit exceeded, None otherwise
        """
        # Check step limit
        if self.steps_taken >= self.limits["max_steps"]:
            return f"max_steps_reached ({self.limits['max_steps']})"

        # Check timeout
        if self.start_time:
            elapsed = time.time() - self.start_time
            if elapsed >= self.limits["timeout"]:
                return f"timeout ({elapsed:.1f}s >= {self.limits['timeout']}s)"

        return None

    def _log_step(
        self,
        thought: str,
        action: str,
        action_input: Dict[str, Any],
        observation: str,
        error: Optional[str] = None
    ):
        """
        Log a single ReAct step to the reasoning trace.

        Args:
            thought: Agent's reasoning
            action: Tool name selected
            action_input: Parameters passed to tool
            observation: Tool output
            error: Error message if tool failed
        """
        step = {
            "step": self.steps_taken,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "thought": thought,
            "action": action,
            "action_input": action_input,
            "observation": observation,
            "error": error
        }
        self.reasoning_trace.append(step)

    def execute_tool(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a registered tool with given parameters.

        Args:
            tool_name: Name of tool to execute
            params: Parameters to pass to tool

        Returns:
            Dictionary with keys:
                - success: bool
                - result: tool output if successful
                - error: error message if failed
        """
        if tool_name not in self.tools:
            return {
                "success": False,
                "error": f"Unknown tool: {tool_name}"
            }

        tool = self.tools[tool_name]

        try:
            result = tool["function"](**params)
            return {
                "success": True,
                "result": result
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def run(
        self,
        goal: str,
        llm_callback: Callable[[str, List[Dict]], Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Run the ReAct loop until goal is reached or limits hit.

        Args:
            goal: The goal/task for the agent to accomplish
            llm_callback: Function that takes (prompt, history) and returns
                         {"thought": str, "action": str, "action_input": dict}
                         or {"thought": str, "final_answer": str} when done

        Returns:
            Dictionary with:
                - success: bool
                - final_answer: result if successful
                - stop_reason: why loop stopped
                - steps_taken: number of iterations
                - reasoning_trace: list of all steps
        """
        self.start_time = time.time()
        self.steps_taken = 0
        self.reasoning_trace = []
        self.is_running = True

        stop_reason = None
        final_answer = None

        while self.is_running:
            # Check limits before each step
            limit_check = self._check_limits()
            if limit_check:
                stop_reason = limit_check
                break

            # Get next action from LLM
            try:
                llm_response = llm_callback(goal, self.reasoning_trace)
            except Exception as e:
                stop_reason = f"llm_error: {str(e)}"
                break

            thought = llm_response.get("thought", "")

            # Check if agent is done
            if "final_answer" in llm_response:
                final_answer = llm_response["final_answer"]
                stop_reason = "goal_completed"
                self._log_step(
                    thought=thought,
                    action="finish",
                    action_input={},
                    observation=final_answer
                )
                break

            # Execute the selected action
            action = llm_response.get("action", "")
            action_input = llm_response.get("action_input", {})

            self.steps_taken += 1

            tool_result = self.execute_tool(action, action_input)

            if tool_result["success"]:
                observation = str(tool_result["result"])
                self._log_step(
                    thought=thought,
                    action=action,
                    action_input=action_input,
                    observation=observation
                )
            else:
                error_msg = tool_result["error"]
                self._log_step(
                    thought=thought,
                    action=action,
                    action_input=action_input,
                    observation="",
                    error=error_msg
                )
                # Continue loop - let agent decide how to handle error

        self.is_running = False
        elapsed = time.time() - self.start_time

        return {
            "success": stop_reason == "goal_completed",
            "final_answer": final_answer,
            "stop_reason": stop_reason,
            "steps_taken": self.steps_taken,
            "elapsed_time": elapsed,
            "reasoning_trace": self.reasoning_trace
        }

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """
        Get JSON schemas for all registered tools.

        Returns:
            List of tool schema dictionaries
        """
        schemas = []
        for name, tool in self.tools.items():
            schema = {
                "name": name,
                **tool.get("schema", {})
            }
            schemas.append(schema)
        return schemas

    def write_reasoning_log(self, log_path: Optional[str] = None):
        """
        Write reasoning trace to markdown log file.

        Format: Thought (1 line) / Action / Action Input / Observation

        Args:
            log_path: Path to log file (defaults to logs/agent_reasoning.md)
        """
        if log_path is None:
            log_dir = Path(__file__).parent.parent.parent / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / "agent_reasoning.md"

        lines = []
        lines.append("# Agent Reasoning Trace")
        lines.append(f"\nGenerated: {datetime.now().isoformat()}")
        lines.append(f"Steps: {self.steps_taken}")
        lines.append("")

        for step in self.reasoning_trace:
            lines.append(f"## Step {step.get('step', '?')}")
            lines.append("")
            lines.append(f"**Thought:** {step.get('thought', 'N/A')}")
            lines.append("")
            lines.append(f"**Action:** {step.get('action', 'N/A')}")
            lines.append("")
            lines.append(f"**Action Input:** `{step.get('action_input', {})}`")
            lines.append("")

            if step.get('error'):
                lines.append(f"**Error:** {step.get('error')}")
            else:
                obs = step.get('observation', '')
                # Truncate long observations
                if len(obs) > 500:
                    obs = obs[:500] + "... [truncated]"
                lines.append(f"**Observation:** {obs}")
            lines.append("")
            lines.append("---")
            lines.append("")

        with open(log_path, 'w') as f:
            f.write("\n".join(lines))

        return str(log_path)

    def write_summary_log(
        self,
        goal: str,
        outcome: str,
        log_path: Optional[str] = None
    ):
        """
        Write agent run summary to markdown log file.

        Format: Goal / Actions Taken / Key Decisions / Outcome

        Args:
            goal: The original goal/task
            outcome: Final outcome description
            log_path: Path to log file (defaults to logs/agent_summary.md)
        """
        if log_path is None:
            log_dir = Path(__file__).parent.parent.parent / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / "agent_summary.md"

        # Extract actions taken
        actions_taken = []
        for step in self.reasoning_trace:
            action = step.get('action', 'unknown')
            if action != 'finish':
                action_input = step.get('action_input', {})
                actions_taken.append(f"- `{action}`: {action_input}")

        # Extract key decisions (thoughts that led to actions)
        key_decisions = []
        for step in self.reasoning_trace:
            thought = step.get('thought', '')
            if thought:
                # Take first sentence as key decision
                decision = thought.split('.')[0] + '.'
                key_decisions.append(f"- {decision}")

        lines = []
        lines.append("# Agent Run Summary")
        lines.append(f"\nGenerated: {datetime.now().isoformat()}")
        lines.append("")

        lines.append("## Goal")
        lines.append(f"\n{goal}")
        lines.append("")

        lines.append("## Actions Taken")
        lines.append(f"\nTotal steps: {self.steps_taken}")
        lines.append("")
        if actions_taken:
            lines.extend(actions_taken)
        else:
            lines.append("- No actions taken")
        lines.append("")

        lines.append("## Key Decisions")
        lines.append("")
        if key_decisions:
            lines.extend(key_decisions)
        else:
            lines.append("- No decisions recorded")
        lines.append("")

        lines.append("## Outcome")
        lines.append(f"\n{outcome}")
        lines.append("")

        # Add metrics
        lines.append("## Metrics")
        lines.append("")
        lines.append(f"- Steps taken: {self.steps_taken}")
        if self.start_time:
            elapsed = time.time() - self.start_time
            lines.append(f"- Elapsed time: {elapsed:.1f}s")

        with open(log_path, 'w') as f:
            f.write("\n".join(lines))

        return str(log_path)
