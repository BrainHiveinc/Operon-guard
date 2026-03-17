"""Framework adapters — normalize any agent into a callable for testing."""

from operon_guard.adapters.base import AgentAdapter, GenericAdapter
from operon_guard.adapters.detect import detect_and_load

__all__ = ["AgentAdapter", "GenericAdapter", "detect_and_load"]
