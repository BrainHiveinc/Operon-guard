"""Latency & cost check — performance profiling and budget enforcement."""

from __future__ import annotations

import asyncio
import statistics
import time
from typing import Any, Callable

from operon_guard.core.scorer import CheckResult, Finding, Severity
from operon_guard.core.spec import GuardSpec, TestCase


def _estimate_token_cost(text: str, model: str = "default") -> float:
    """Rough token cost estimation (input + output).

    Uses ~4 chars per token heuristic. Pricing tiers based on model class.
    """
    est_tokens = len(text) / 4

    # approximate $/1K tokens (input + output blended) by tier
    pricing = {
        "premium": 0.06,       # flagship models
        "standard": 0.005,     # mid-tier models
        "fast": 0.002,         # speed-optimized models
        "mini": 0.0005,        # lightweight models
        "edge": 0.0003,        # edge / hosted inference
        "local": 0.0,          # self-hosted
        "default": 0.005,
    }
    rate = pricing.get(model, 0.005)
    return (est_tokens / 1000) * rate


class LatencyCheck:
    """Profile agent latency, throughput, and estimated cost."""

    def __init__(self, spec: GuardSpec):
        self.spec = spec

    async def run(
        self,
        agent_fn: Callable[..., Any],
        test_cases: list[TestCase],
    ) -> CheckResult:
        findings: list[Finding] = []
        score = 100.0

        timings: list[float] = []   # ms
        output_sizes: list[int] = []
        total_cost = 0.0

        for tc in test_cases:
            t0 = time.monotonic()
            try:
                result = agent_fn(tc.input)
                if asyncio.iscoroutine(result):
                    timeout = max(self.spec.latency_p95_ms / 1000 * 3, 30.0)
                    result = await asyncio.wait_for(result, timeout=timeout)
                elapsed_ms = (time.monotonic() - t0) * 1000
                output_str = str(result)

                timings.append(elapsed_ms)
                output_sizes.append(len(output_str))

                # estimate cost
                input_str = str(tc.input)
                total_cost += _estimate_token_cost(input_str + output_str)

                # per-case latency check
                if tc.max_latency_ms and elapsed_ms > tc.max_latency_ms:
                    findings.append(Finding(
                        check="latency",
                        severity=Severity.WARNING,
                        message=(
                            f"[{tc.name}] {elapsed_ms:.0f}ms exceeds "
                            f"case limit {tc.max_latency_ms:.0f}ms"
                        ),
                        details={"actual_ms": round(elapsed_ms, 1), "limit_ms": tc.max_latency_ms},
                    ))

            except Exception as e:
                elapsed_ms = (time.monotonic() - t0) * 1000
                timings.append(elapsed_ms)
                findings.append(Finding(
                    check="latency",
                    severity=Severity.INFO,
                    message=f"[{tc.name}] Failed after {elapsed_ms:.0f}ms: {e}",
                ))

        if not timings:
            return CheckResult(
                name="latency", score=0.0, passed=False,
                findings=[Finding(check="latency", severity=Severity.CRITICAL,
                                  message="No test cases completed")],
            )

        # ── Compute stats ──
        p50 = statistics.median(timings)
        sorted_timings = sorted(timings)
        p95_idx = min(int(len(sorted_timings) * 0.95), len(sorted_timings) - 1)
        p99_idx = min(int(len(sorted_timings) * 0.99), len(sorted_timings) - 1)
        p95 = sorted_timings[p95_idx] if len(timings) >= 2 else max(timings)
        p99 = sorted_timings[p99_idx] if len(timings) >= 2 else max(timings)
        mean = statistics.mean(timings)
        stddev = statistics.stdev(timings) if len(timings) >= 2 else 0.0

        # ── P95 check ──
        if p95 > self.spec.latency_p95_ms:
            pct_over = ((p95 - self.spec.latency_p95_ms) / self.spec.latency_p95_ms) * 100
            severity = Severity.CRITICAL if pct_over > 100 else Severity.WARNING
            findings.append(Finding(
                check="latency.p95",
                severity=severity,
                message=f"P95 latency {p95:.0f}ms exceeds limit {self.spec.latency_p95_ms:.0f}ms (+{pct_over:.0f}%)",
                details={"p95_ms": round(p95, 1), "limit_ms": self.spec.latency_p95_ms},
            ))
            score -= min(30, pct_over / 3)
        else:
            findings.append(Finding(
                check="latency.p95",
                severity=Severity.INFO,
                message=f"P95 latency {p95:.0f}ms within limit {self.spec.latency_p95_ms:.0f}ms",
            ))

        # ── Variance check (high stddev = unpredictable) ──
        if mean > 0 and stddev / mean > 0.5:
            cv = stddev / mean
            findings.append(Finding(
                check="latency.variance",
                severity=Severity.WARNING,
                message=f"High latency variance (CV={cv:.2f}) — agent performance is unpredictable",
                details={"mean_ms": round(mean, 1), "stddev_ms": round(stddev, 1), "cv": round(cv, 3)},
            ))
            score -= 10

        # ── Cost check ──
        if self.spec.latency_budget_usd is not None:
            if total_cost > self.spec.latency_budget_usd:
                findings.append(Finding(
                    check="latency.cost",
                    severity=Severity.WARNING,
                    message=(
                        f"Estimated cost ${total_cost:.4f} exceeds "
                        f"budget ${self.spec.latency_budget_usd:.4f}"
                    ),
                    details={"estimated_usd": round(total_cost, 6),
                             "budget_usd": self.spec.latency_budget_usd},
                ))
                score -= 15
            else:
                findings.append(Finding(
                    check="latency.cost",
                    severity=Severity.INFO,
                    message=f"Estimated cost ${total_cost:.4f} within budget ${self.spec.latency_budget_usd:.4f}",
                ))

        # ── Summary stats ──
        findings.append(Finding(
            check="latency.summary",
            severity=Severity.INFO,
            message=f"Latency: p50={p50:.0f}ms  p95={p95:.0f}ms  p99={p99:.0f}ms  mean={mean:.0f}ms",
            details={
                "p50_ms": round(p50, 1),
                "p95_ms": round(p95, 1),
                "p99_ms": round(p99, 1),
                "mean_ms": round(mean, 1),
                "stddev_ms": round(stddev, 1),
                "total_runs": len(timings),
                "estimated_cost_usd": round(total_cost, 6),
            },
        ))

        score = max(0.0, min(100.0, score))
        return CheckResult(
            name="latency",
            score=round(score, 1),
            passed=score >= 60,
            findings=findings,
            metadata={
                "p50_ms": round(p50, 1),
                "p95_ms": round(p95, 1),
                "mean_ms": round(mean, 1),
                "estimated_cost_usd": round(total_cost, 6),
            },
        )
