"""Base adapter — the interface all framework adapters implement."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable


class AgentAdapter(ABC):
    """Wraps any agent framework into a simple callable for testing."""

    name: str = "base"

    @abstractmethod
    def wrap(self, agent: Any) -> Callable[[Any], Any]:
        """Return a callable: input → output string."""
        ...

    @classmethod
    def detect(cls, agent: Any) -> bool:
        """Return True if this adapter can handle the given agent object."""
        return False


class GenericAdapter(AgentAdapter):
    """Adapter for plain functions / callables."""

    name = "generic"

    def wrap(self, agent: Any) -> Callable[[Any], Any]:
        if callable(agent):
            return agent
        raise TypeError(f"GenericAdapter requires a callable, got {type(agent).__name__}")

    @classmethod
    def detect(cls, agent: Any) -> bool:
        return callable(agent)
