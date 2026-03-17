"""TrustScore — aggregated trust scoring for agent verification."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Grade(str, Enum):
    A = "A"   # 90-100  — production-ready
    B = "B"   # 75-89   — mostly safe, minor issues
    C = "C"   # 60-74   — needs attention
    D = "D"   # 40-59   — significant risks
    F = "F"   # 0-39    — do not deploy

    @classmethod
    def from_score(cls, score: float) -> Grade:
        if score >= 90:
            return cls.A
        elif score >= 75:
            return cls.B
        elif score >= 60:
            return cls.C
        elif score >= 40:
            return cls.D
        return cls.F


class Severity(str, Enum):
    CRITICAL = "critical"   # blocks deployment
    WARNING = "warning"     # should fix
    INFO = "info"           # nice to know


@dataclass
class Finding:
    """A single issue or observation from a check."""

    check: str                 # e.g. "determinism", "safety.pii"
    severity: Severity
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class CheckResult:
    """Result from a single check category."""

    name: str                  # e.g. "determinism", "concurrency", "safety", "latency"
    score: float               # 0-100
    passed: bool
    findings: list[Finding] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def grade(self) -> Grade:
        return Grade.from_score(self.score)


@dataclass
class TrustScore:
    """Aggregated trust score across all checks."""

    overall: float             # 0-100 weighted average
    grade: Grade
    checks: dict[str, CheckResult] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.grade in (Grade.A, Grade.B)

    @property
    def critical_findings(self) -> list[Finding]:
        findings = []
        for cr in self.checks.values():
            findings.extend(f for f in cr.findings if f.severity == Severity.CRITICAL)
        return findings


# ── Weights for each check category ──
DEFAULT_WEIGHTS = {
    "determinism": 0.30,
    "concurrency": 0.25,
    "safety": 0.30,
    "latency": 0.15,
}


def compute_trust_score(results: dict[str, CheckResult]) -> TrustScore:
    """Compute weighted trust score from individual check results."""
    weights = {k: DEFAULT_WEIGHTS.get(k, 0.1) for k in results}
    total_weight = sum(weights.values()) or 1.0

    weighted_sum = sum(results[k].score * weights[k] for k in results)
    overall = weighted_sum / total_weight

    return TrustScore(
        overall=round(overall, 1),
        grade=Grade.from_score(overall),
        checks=results,
    )


@dataclass
class TrustReport:
    """Full verification report."""

    agent_name: str
    spec_file: str | None
    trust_score: TrustScore
    duration_ms: float
    test_cases_run: int
    test_cases_passed: int

    def summary_line(self) -> str:
        icon = {
            Grade.A: "A",
            Grade.B: "B",
            Grade.C: "C",
            Grade.D: "D",
            Grade.F: "F",
        }[self.trust_score.grade]
        status = "PASS" if self.trust_score.passed else "FAIL"
        return (
            f"[{status}] {self.agent_name}  "
            f"Trust: {self.trust_score.overall}/100 (Grade {icon})  "
            f"Tests: {self.test_cases_passed}/{self.test_cases_run}  "
            f"Time: {self.duration_ms:.0f}ms"
        )
