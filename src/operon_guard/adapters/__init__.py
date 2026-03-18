"""Framework adapters — normalize any agent into a callable for testing."""

from operon_guard.adapters.base import AgentAdapter, GenericAdapter
from operon_guard.adapters.detect import detect_and_load

try:
    from operon_guard.adapters.openclaw_adapter import OpenClawAdapter, load_openclaw_skill
except ImportError:
    OpenClawAdapter = None
    load_openclaw_skill = None

__all__ = [
    "AgentAdapter",
    "GenericAdapter",
    "OpenClawAdapter",
    "detect_and_load",
    "load_openclaw_skill",
]
