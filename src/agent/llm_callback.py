"""
LLM callback for AgentController - bridges OpenAI chat API to ReAct loop.

Provides a factory function that creates an llm_callback compatible with
AgentController.run(). Uses the same env-var conventions as extract.py:
- OPENAI_API_KEY for authentication
- LLM_MODEL for model selection (default: gpt-4o-mini)
"""

import json
import os
from typing import Any, Callable, Dict, List

from openai import OpenAI


SYSTEM_PROMPT = """\
You are a financial services trend monitoring agent. You have access to tools \
that let you scrape sources, analyze content, check for duplicates, and \
render digests.

Available tools:
{tool_descriptions}

Respond with a JSON object. While you still have work to do, use:
{{"thought": "<your reasoning>", "action": "<tool_name>", "action_input": {{<params>}}}}

When the goal is fully achieved, use:
{{"thought": "<your reasoning>", "final_answer": "<summary of what was accomplished>"}}

Always respond with valid JSON only. No markdown fences or extra text.\
"""


def make_llm_callback(
    tool_schemas: List[Dict[str, Any]],
    api_key: str = None,
    model: str = None,
) -> Callable[[str, List[Dict]], Dict[str, Any]]:
    """
    Create an llm_callback function for AgentController.run().

    Args:
        tool_schemas: Tool schemas from AgentController.get_tool_schemas()
        api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
        model: Model name (defaults to LLM_MODEL env var or "gpt-4o-mini")

    Returns:
        Callable with signature (goal: str, reasoning_trace: List[Dict]) -> Dict
    """
    resolved_key = api_key or os.getenv("OPENAI_API_KEY")
    if not resolved_key:
        raise ValueError(
            "OpenAI API key not found. Set OPENAI_API_KEY environment variable."
        )
    resolved_model = model or os.getenv("LLM_MODEL", "gpt-4o-mini")
    client = OpenAI(api_key=resolved_key)

    # Format tool descriptions once at construction time
    tool_desc_lines = []
    for schema in tool_schemas:
        name = schema.get("name", "unknown")
        desc = schema.get("description", "")
        params = schema.get("parameters", {})
        tool_desc_lines.append(
            f"- {name}: {desc}\n  Parameters: {json.dumps(params)}"
        )
    tool_descriptions = "\n".join(tool_desc_lines)
    system_message = SYSTEM_PROMPT.format(tool_descriptions=tool_descriptions)

    def llm_callback(goal: str, reasoning_trace: List[Dict]) -> Dict[str, Any]:
        messages = [{"role": "system", "content": system_message}]

        # Build user message with goal and history
        user_parts = [f"Goal: {goal}"]
        if reasoning_trace:
            user_parts.append("\nPrevious steps:")
            for step in reasoning_trace:
                user_parts.append(
                    f"  Step {step.get('step', '?')}: "
                    f"Action={step.get('action', 'N/A')}, "
                    f"Observation={str(step.get('observation', ''))[:200]}"
                )
            user_parts.append("\nDecide your next action or provide final_answer.")
        else:
            user_parts.append("\nThis is the first step. Decide what to do first.")

        messages.append({"role": "user", "content": "\n".join(user_parts)})

        response = client.chat.completions.create(
            model=resolved_model,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.2,
        )

        content = response.choices[0].message.content
        return json.loads(content)

    return llm_callback
