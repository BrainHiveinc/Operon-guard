"""Crew adapter — wraps crew/kickoff style agents."""

from __future__ import annotations

from typing import Any, Callable

from operon_guard.adapters.base import AgentAdapter


class CrewAdapter(AgentAdapter):
    """Wrap crew-style agents (kickoff/execute_task pattern) into a testable callable."""

    name = "crew"

    def wrap(self, agent: Any) -> Callable[[Any], Any]:
        # Crew kickoff interface
        if hasattr(agent, "kickoff"):
            def _kickoff(inp: Any) -> str:
                inputs = inp if isinstance(inp, dict) else {"input": str(inp)}
                result = agent.kickoff(inputs=inputs)
                if hasattr(result, "raw"):
                    return result.raw
                return str(result)
            return _kickoff

        # Single agent with execute_task
        if hasattr(agent, "execute_task"):
            def _execute(inp: Any) -> str:
                return str(agent.execute_task(str(inp)))
            return _execute

        raise TypeError(f"Cannot wrap crew object of type {type(agent).__name__}")

    @classmethod
    def detect(cls, agent: Any) -> bool:
        module = getattr(type(agent), "__module__", "")
        return "crewai" in module
