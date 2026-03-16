"""Conversable adapter — wraps conversable/reply-style agents."""

from __future__ import annotations

from typing import Any, Callable

from operon_guard.adapters.base import AgentAdapter


class ConversableAdapter(AgentAdapter):
    """Wrap conversable agents (generate_reply/run pattern) into a testable callable."""

    name = "conversable"

    def wrap(self, agent: Any) -> Callable[[Any], Any]:
        # Conversable agent with generate_reply
        if hasattr(agent, "generate_reply"):
            def _reply(inp: Any) -> str:
                messages = [{"role": "user", "content": str(inp)}]
                result = agent.generate_reply(messages=messages)
                return str(result) if result else ""
            return _reply

        # Group run interface
        if hasattr(agent, "run"):
            def _run(inp: Any) -> str:
                result = agent.run(str(inp))
                if hasattr(result, "summary"):
                    return result.summary
                return str(result)
            return _run

        raise TypeError(f"Cannot wrap conversable object of type {type(agent).__name__}")

    @classmethod
    def detect(cls, agent: Any) -> bool:
        module = getattr(type(agent), "__module__", "")
        return "autogen" in module
