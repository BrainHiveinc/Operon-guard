"""Runnable adapter — wraps chain/runnable/executor style agents."""

from __future__ import annotations

from typing import Any, Callable

from operon_guard.adapters.base import AgentAdapter


class RunnableAdapter(AgentAdapter):
    """Wrap runnable-style agents (invoke/run/call pattern) into a testable callable."""

    name = "runnable"

    def wrap(self, agent: Any) -> Callable[[Any], Any]:
        # Runnable interface (.invoke)
        if hasattr(agent, "invoke"):
            def _invoke(inp: Any) -> str:
                result = agent.invoke(inp)
                if hasattr(result, "content"):
                    return result.content
                if isinstance(result, dict):
                    return str(result.get("output", result.get("text", result)))
                return str(result)
            return _invoke

        # Legacy chain interface (.run)
        if hasattr(agent, "run"):
            def _run(inp: Any) -> str:
                return str(agent.run(inp))
            return _run

        # Direct callable executor
        if hasattr(agent, "__call__"):
            def _call(inp: Any) -> str:
                result = agent(inp)
                if isinstance(result, dict):
                    return str(result.get("output", result))
                return str(result)
            return _call

        raise TypeError(f"Cannot wrap runnable object of type {type(agent).__name__}")

    @classmethod
    def detect(cls, agent: Any) -> bool:
        agent_type = type(agent)
        module = getattr(agent_type, "__module__", "")
        # detect chain/runnable frameworks by interface pattern
        return ("langchain" in module) or (
            hasattr(agent, "invoke") and hasattr(agent, "batch")
        )
