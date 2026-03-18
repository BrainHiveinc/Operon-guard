"""Determinism check — run the agent N times and measure output consistency."""

from __future__ import annotations

import asyncio
import time
from difflib import SequenceMatcher
from typing import Any, Callable

from operon_guard.core.scorer import CheckResult, Finding, Severity
from operon_guard.core.spec import GuardSpec, TestCase


def _similarity(a: str, b: str) -> float:
    """Normalized string similarity 0-1."""
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def _structural_similarity(outputs: list[str]) -> float:
    """Average pairwise similarity across all outputs."""
    if len(outputs) < 2:
        return 1.0
    pairs = []
    for i in range(len(outputs)):
        for j in range(i + 1, len(outputs)):
            pairs.append(_similarity(outputs[i], outputs[j]))
    return sum(pairs) / len(pairs) if pairs else 1.0


def _semantic_key_overlap(outputs: list[str]) -> float:
    """Check if the same key facts appear across runs.

    Extracts 'key phrases' (3+ word sequences) and measures overlap.
    This catches cases where wording differs but content is consistent.
    """
    import re

    def extract_phrases(text: str) -> set[str]:
        words = re.findall(r"\b[a-zA-Z]{3,}\b", text.lower())
        phrases = set()
        for i in range(len(words) - 2):
            phrases.add(f"{words[i]} {words[i+1]} {words[i+2]}")
        # also add individual significant words (5+ chars)
        phrases.update(w for w in words if len(w) >= 5)
        return phrases

    if len(outputs) < 2:
        return 1.0

    phrase_sets = [extract_phrases(o) for o in outputs]
    overlaps = []
    for i in range(len(phrase_sets)):
        for j in range(i + 1, len(phrase_sets)):
            union = phrase_sets[i] | phrase_sets[j]
            if not union:
                overlaps.append(1.0)
                continue
            inter = phrase_sets[i] & phrase_sets[j]
            overlaps.append(len(inter) / len(union))
    return sum(overlaps) / len(overlaps) if overlaps else 1.0


class DeterminismCheck:
    """Run agent multiple times per test case; measure output consistency."""

    def __init__(self, spec: GuardSpec):
        self.spec = spec

    async def run(
        self,
        agent_fn: Callable[..., Any],
        test_cases: list[TestCase],
    ) -> CheckResult:
        findings: list[Finding] = []
        case_scores: list[float] = []

        for tc in test_cases:
            outputs: list[str] = []
            errors: list[str] = []

            for run_idx in range(self.spec.determinism_runs):
                try:
                    result = agent_fn(tc.input)
                    if asyncio.iscoroutine(result):
                        result = await asyncio.wait_for(result, timeout=60.0)
                    outputs.append(str(result))
                except Exception as e:
                    errors.append(f"Run {run_idx + 1}: {type(e).__name__}: {e}")

            if errors:
                findings.append(Finding(
                    check="determinism",
                    severity=Severity.WARNING,
                    message=f"[{tc.name}] {len(errors)}/{self.spec.determinism_runs} runs failed",
                    details={"errors": errors[:5]},
                ))

            if len(outputs) < 2:
                case_scores.append(0.0 if not outputs else 50.0)
                findings.append(Finding(
                    check="determinism",
                    severity=Severity.CRITICAL,
                    message=f"[{tc.name}] Not enough successful runs to measure consistency",
                ))
                continue

            # ── measure consistency ──
            structural = _structural_similarity(outputs)
            semantic = _semantic_key_overlap(outputs)
            # weighted: structural similarity matters more for exact outputs,
            # semantic overlap catches "same meaning, different words"
            combined = 0.6 * structural + 0.4 * semantic
            case_scores.append(combined)

            if combined < self.spec.determinism_threshold:
                findings.append(Finding(
                    check="determinism",
                    severity=Severity.WARNING if combined > 0.5 else Severity.CRITICAL,
                    message=(
                        f"[{tc.name}] Low consistency: {combined:.0%} "
                        f"(threshold: {self.spec.determinism_threshold:.0%})"
                    ),
                    details={
                        "structural_similarity": round(structural, 3),
                        "semantic_overlap": round(semantic, 3),
                        "combined": round(combined, 3),
                        "sample_outputs": outputs[:3],
                    },
                ))

            # ── check expected output if provided ──
            if tc.expected is not None:
                expected_str = str(tc.expected)
                best_match = max(_similarity(o, expected_str) for o in outputs)
                if best_match < 0.7:
                    findings.append(Finding(
                        check="determinism",
                        severity=Severity.WARNING,
                        message=f"[{tc.name}] Best output only {best_match:.0%} similar to expected",
                        details={"expected": expected_str, "best_output": outputs[0][:200]},
                    ))

            # ── check contains / not-contains ──
            for phrase in tc.expected_contains:
                if not any(phrase.lower() in o.lower() for o in outputs):
                    findings.append(Finding(
                        check="determinism",
                        severity=Severity.WARNING,
                        message=f"[{tc.name}] Expected phrase not found in any output: '{phrase}'",
                    ))

            for phrase in tc.expected_not_contains:
                if any(phrase.lower() in o.lower() for o in outputs):
                    findings.append(Finding(
                        check="determinism",
                        severity=Severity.CRITICAL,
                        message=f"[{tc.name}] Banned phrase found in output: '{phrase}'",
                    ))

        avg_score = (sum(case_scores) / len(case_scores) * 100) if case_scores else 0.0
        passed = avg_score >= self.spec.determinism_threshold * 100

        return CheckResult(
            name="determinism",
            score=round(avg_score, 1),
            passed=passed,
            findings=findings,
            metadata={
                "runs_per_case": self.spec.determinism_runs,
                "threshold": self.spec.determinism_threshold,
                "cases_tested": len(test_cases),
            },
        )
