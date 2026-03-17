"""operon-guard — Trust verification for AI agents."""

__version__ = "0.1.0"

from operon_guard.core.spec import GuardSpec, TestCase
from operon_guard.core.runner import GuardRunner
from operon_guard.core.scorer import TrustScore, TrustReport

__all__ = ["GuardSpec", "TestCase", "GuardRunner", "TrustScore", "TrustReport", "__version__"]
