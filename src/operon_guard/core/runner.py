"""GuardRunner — orchestrates all checks and produces a TrustReport."""

from __future__ import annotations

import asyncio
import logging
import time
import warnings
from typing import Any, Callable

from operon_guard.core.spec import GuardSpec
from operon_guard.core.scorer import (
    CheckResult,
    TrustReport,
    compute_trust_score,
)
from operon_guard.checks.determinism import DeterminismCheck
from operon_guard.checks.concurrency import ConcurrencyCheck
from operon_guard.checks.safety import SafetyCheck
from operon_guard.checks.latency import LatencyCheck


class GuardRunner:
    """Run all enabled checks against an agent and produce a TrustReport."""

    def __init__(self, spec: GuardSpec):
        self.spec = spec

    async def run(self, agent_fn: Callable[..., Any]) -> TrustReport:
        """Execute all checks and return a full trust report."""
        # suppress noisy "Future exception was never retrieved" warnings
        # from agent code that fires and forgets async tasks
        loop = asyncio.get_event_loop()
        _orig_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, ctx: None)

        # also suppress noisy logging and runtime warnings from agent internals
        _prev_level = logging.root.level
        logging.disable(logging.WARNING)
        warnings.filterwarnings("ignore", category=RuntimeWarning)
        warnings.filterwarnings("ignore", category=DeprecationWarning)

        t0 = time.monotonic()
        results: dict[str, CheckResult] = {}
        test_cases = self.spec.test_cases

        # ── Determinism ──
        if self.spec.check_determinism and test_cases:
            det_check = DeterminismCheck(self.spec)
            results["determinism"] = await det_check.run(agent_fn, test_cases)

        # ── Concurrency ──
        if self.spec.check_concurrency and test_cases:
            conc_check = ConcurrencyCheck(self.spec)
            results["concurrency"] = await conc_check.run(agent_fn, test_cases)

        # ── Safety ──
        if self.spec.check_safety:
            safety_check = SafetyCheck(self.spec)
            results["safety"] = await safety_check.run(agent_fn, test_cases)

        # ── Latency & Cost ──
        if self.spec.check_latency and test_cases:
            lat_check = LatencyCheck(self.spec)
            results["latency"] = await lat_check.run(agent_fn, test_cases)

        # ── Compute trust score ──
        trust_score = compute_trust_score(results)

        elapsed_ms = (time.monotonic() - t0) * 1000

        # count passed test cases (from determinism check metadata)
        cases_run = len(test_cases)
        cases_passed = cases_run  # default
        if "determinism" in results:
            # if determinism found critical issues, some cases failed
            crit = sum(
                1 for f in results["determinism"].findings
                if f.severity.value == "critical"
            )
            cases_passed = max(0, cases_run - crit)

        # restore logging, warnings, and exception handler
        logging.disable(logging.NOTSET)
        logging.root.setLevel(_prev_level)
        warnings.resetwarnings()
        loop.set_exception_handler(_orig_handler)

        return TrustReport(
            agent_name=self.spec.name,
            spec_file=None,
            trust_score=trust_score,
            duration_ms=elapsed_ms,
            test_cases_run=cases_run,
            test_cases_passed=cases_passed,
        )
