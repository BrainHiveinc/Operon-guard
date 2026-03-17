"""Concurrency check — ORC-lite race condition & deadlock detection for agents."""

from __future__ import annotations

import asyncio
import inspect
import threading
import time
from typing import Any, Callable

from operon_guard.core.scorer import CheckResult, Finding, Severity
from operon_guard.core.spec import GuardSpec, TestCase


class _SharedStateDetector:
    """Detect shared mutable state by wrapping the agent and tracking attribute access."""

    def __init__(self):
        self.shared_writes: list[dict[str, Any]] = []
        self.lock_acquisitions: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def record_write(self, obj_id: int, attr: str, thread_id: int):
        with self._lock:
            self.shared_writes.append({
                "obj_id": obj_id,
                "attr": attr,
                "thread_id": thread_id,
                "time": time.monotonic(),
            })

    def detect_races(self) -> list[dict[str, Any]]:
        """Find writes to same (obj_id, attr) from different threads within short windows."""
        races = []
        by_key: dict[tuple, list[dict]] = {}
        for w in self.shared_writes:
            key = (w["obj_id"], w["attr"])
            by_key.setdefault(key, []).append(w)

        for key, writes in by_key.items():
            threads = set(w["thread_id"] for w in writes)
            if len(threads) > 1:
                # multiple threads writing to same attribute
                writes.sort(key=lambda x: x["time"])
                for i in range(len(writes) - 1):
                    if (writes[i]["thread_id"] != writes[i + 1]["thread_id"]
                            and writes[i + 1]["time"] - writes[i]["time"] < 0.1):
                        races.append({
                            "attr": writes[0]["attr"],
                            "threads": list(threads),
                            "writes": len(writes),
                            "window_ms": round(
                                (writes[i + 1]["time"] - writes[i]["time"]) * 1000, 1
                            ),
                        })
                        break
        return races


async def _run_concurrent(
    agent_fn: Callable,
    inputs: list[Any],
    workers: int,
    timeout_s: float,
) -> dict[str, Any]:
    """Run agent concurrently and collect timing + error data."""
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    start = time.monotonic()

    sem = asyncio.Semaphore(workers)

    async def _worker(idx: int, inp: Any):
        async with sem:
            t0 = time.monotonic()
            try:
                result = agent_fn(inp)
                if asyncio.iscoroutine(result):
                    result = await asyncio.wait_for(result, timeout=timeout_s)
                elapsed = (time.monotonic() - t0) * 1000
                results.append({"idx": idx, "output": str(result)[:500], "ms": elapsed})
            except asyncio.TimeoutError:
                errors.append({"idx": idx, "error": "timeout", "after_ms": timeout_s * 1000})
            except Exception as e:
                elapsed = (time.monotonic() - t0) * 1000
                errors.append({"idx": idx, "error": f"{type(e).__name__}: {e}", "ms": elapsed})

    tasks = [_worker(i, inp) for i, inp in enumerate(inputs)]
    await asyncio.gather(*tasks, return_exceptions=True)

    total_ms = (time.monotonic() - start) * 1000
    return {
        "results": results,
        "errors": errors,
        "total_ms": total_ms,
        "throughput": len(results) / (total_ms / 1000) if total_ms > 0 else 0,
    }


def _static_analysis(agent_fn: Callable) -> list[Finding]:
    """Static analysis: look for common concurrency anti-patterns in source."""
    findings: list[Finding] = []

    try:
        source = inspect.getsource(agent_fn)
    except (OSError, TypeError):
        return findings

    # check for global variable mutations
    if "global " in source:
        findings.append(Finding(
            check="concurrency.static",
            severity=Severity.WARNING,
            message="Agent uses 'global' keyword — shared mutable state risk",
        ))

    # check for missing locks around shared state
    has_shared_state = any(kw in source for kw in ["self.", "cls.", "global "])
    has_locks = any(kw in source for kw in ["Lock()", "RLock()", "asyncio.Lock()", "Semaphore("])
    if has_shared_state and not has_locks:
        findings.append(Finding(
            check="concurrency.static",
            severity=Severity.WARNING,
            message="Agent accesses shared state without apparent locking",
        ))

    # check for thread-unsafe patterns
    unsafe_patterns = {
        "datetime.now()": "Non-deterministic timestamps may cause race conditions",
        "random.": "Shared random state is not thread-safe",
        "open(": "File I/O without locks can cause data corruption",
    }
    for pattern, msg in unsafe_patterns.items():
        if pattern in source:
            findings.append(Finding(
                check="concurrency.static",
                severity=Severity.INFO,
                message=msg,
                details={"pattern": pattern},
            ))

    return findings


class ConcurrencyCheck:
    """Detect race conditions, deadlocks, and concurrency issues."""

    def __init__(self, spec: GuardSpec):
        self.spec = spec

    async def run(
        self,
        agent_fn: Callable[..., Any],
        test_cases: list[TestCase],
    ) -> CheckResult:
        findings: list[Finding] = []
        score = 100.0

        # ── Phase 1: Static analysis ──
        static_findings = _static_analysis(agent_fn)
        findings.extend(static_findings)
        # deduct for static findings
        for f in static_findings:
            if f.severity == Severity.WARNING:
                score -= 5
            elif f.severity == Severity.CRITICAL:
                score -= 15

        # ── Phase 2: Concurrent execution ──
        if test_cases:
            # run all test cases concurrently
            inputs = [tc.input for tc in test_cases]
            # duplicate inputs to increase contention
            concurrent_inputs = inputs * max(1, self.spec.concurrency_workers // len(inputs) + 1)
            concurrent_inputs = concurrent_inputs[: self.spec.concurrency_workers * len(inputs)]

            run_data = await _run_concurrent(
                agent_fn,
                concurrent_inputs,
                workers=self.spec.concurrency_workers,
                timeout_s=self.spec.concurrency_timeout_s,
            )

            # ── Check for timeouts (potential deadlocks) ──
            timeouts = [e for e in run_data["errors"] if e.get("error") == "timeout"]
            if timeouts:
                pct = len(timeouts) / len(concurrent_inputs)
                findings.append(Finding(
                    check="concurrency",
                    severity=Severity.CRITICAL if pct > 0.3 else Severity.WARNING,
                    message=f"{len(timeouts)}/{len(concurrent_inputs)} runs timed out — possible deadlock",
                    details={"timeout_count": len(timeouts), "timeout_s": self.spec.concurrency_timeout_s},
                ))
                score -= min(40, pct * 80)

            # ── Check for errors under load ──
            other_errors = [e for e in run_data["errors"] if e.get("error") != "timeout"]
            if other_errors:
                pct = len(other_errors) / len(concurrent_inputs)
                findings.append(Finding(
                    check="concurrency",
                    severity=Severity.WARNING if pct < 0.2 else Severity.CRITICAL,
                    message=f"{len(other_errors)}/{len(concurrent_inputs)} runs failed under concurrent load",
                    details={"errors": [e["error"] for e in other_errors[:5]]},
                ))
                score -= min(30, pct * 60)

            # ── Check output consistency under concurrency ──
            if run_data["results"]:
                # group by input and check if same input gives wildly different outputs
                from collections import defaultdict
                by_input: dict[str, list[str]] = defaultdict(list)
                for r in run_data["results"]:
                    input_key = str(concurrent_inputs[r["idx"]])[:100]
                    by_input[input_key].append(r["output"])

                from operon_guard.checks.determinism import _structural_similarity
                for input_key, outputs in by_input.items():
                    if len(outputs) >= 2:
                        sim = _structural_similarity(outputs)
                        if sim < 0.5:
                            findings.append(Finding(
                                check="concurrency",
                                severity=Severity.WARNING,
                                message=f"Outputs diverged under concurrency (similarity: {sim:.0%})",
                                details={"input_preview": input_key[:80], "similarity": round(sim, 3)},
                            ))
                            score -= 10

            # record throughput
            findings.append(Finding(
                check="concurrency",
                severity=Severity.INFO,
                message=f"Throughput: {run_data['throughput']:.1f} calls/sec across {self.spec.concurrency_workers} workers",
                details={
                    "throughput": round(run_data["throughput"], 2),
                    "total_ms": round(run_data["total_ms"], 1),
                    "workers": self.spec.concurrency_workers,
                },
            ))

        score = max(0.0, min(100.0, score))
        return CheckResult(
            name="concurrency",
            score=round(score, 1),
            passed=score >= 60,
            findings=findings,
            metadata={
                "workers": self.spec.concurrency_workers,
                "timeout_s": self.spec.concurrency_timeout_s,
            },
        )
