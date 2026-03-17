"""GuardSpec — defines what an agent should do and how to verify it."""

from __future__ import annotations

import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class TestCase:
    """A single input → expected-output pair."""

    name: str
    input: str | dict[str, Any]
    expected: str | dict[str, Any] | None = None
    expected_contains: list[str] = field(default_factory=list)
    expected_not_contains: list[str] = field(default_factory=list)
    max_latency_ms: float | None = None
    max_cost_usd: float | None = None
    tags: list[str] = field(default_factory=list)


@dataclass
class GuardSpec:
    """Full specification for agent verification."""

    name: str = "unnamed-agent"
    description: str = ""
    agent_module: str = ""          # e.g. "my_agent:run"
    agent_class: str = ""           # e.g. "my_agent:MyAgent"
    framework: str = "auto"         # auto | generic | runnable | crew | conversable

    # ── check toggles ──
    check_determinism: bool = True
    determinism_runs: int = 5
    determinism_threshold: float = 0.8   # 0-1, how similar outputs must be

    check_concurrency: bool = True
    concurrency_workers: int = 4
    concurrency_timeout_s: float = 30.0

    check_safety: bool = True
    safety_check_pii: bool = True
    safety_check_injection: bool = True
    safety_check_hallucination: bool = True
    safety_banned_phrases: list[str] = field(default_factory=list)

    check_latency: bool = True
    latency_p95_ms: float = 5000.0
    latency_budget_usd: float | None = None

    test_cases: list[TestCase] = field(default_factory=list)

    @classmethod
    def from_yaml(cls, path: str | Path) -> GuardSpec:
        """Load a guardfile.yaml into a GuardSpec."""
        raw = yaml.safe_load(Path(path).read_text())
        if not isinstance(raw, dict):
            raise ValueError(f"guardfile must be a YAML mapping, got {type(raw).__name__}")

        cases = []
        for tc in raw.pop("test_cases", []):
            cases.append(TestCase(**tc))

        # flatten nested sections
        det = raw.pop("determinism", {})
        conc = raw.pop("concurrency", {})
        saf = raw.pop("safety", {})
        lat = raw.pop("latency", {})

        return cls(
            **raw,
            check_determinism=det.get("enabled", True),
            determinism_runs=det.get("runs", 5),
            determinism_threshold=det.get("threshold", 0.8),
            check_concurrency=conc.get("enabled", True),
            concurrency_workers=conc.get("workers", 4),
            concurrency_timeout_s=conc.get("timeout_s", 30.0),
            check_safety=saf.get("enabled", True),
            safety_check_pii=saf.get("check_pii", True),
            safety_check_injection=saf.get("check_injection", True),
            safety_check_hallucination=saf.get("check_hallucination", True),
            safety_banned_phrases=saf.get("banned_phrases", []),
            check_latency=lat.get("enabled", True),
            latency_p95_ms=lat.get("p95_ms", 5000.0),
            latency_budget_usd=lat.get("budget_usd"),
            test_cases=cases,
        )

    def to_yaml(self) -> str:
        """Serialize to YAML string."""
        d: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
        }
        if self.agent_module:
            d["agent_module"] = self.agent_module
        if self.agent_class:
            d["agent_class"] = self.agent_class
        if self.framework != "auto":
            d["framework"] = self.framework

        d["determinism"] = {
            "enabled": self.check_determinism,
            "runs": self.determinism_runs,
            "threshold": self.determinism_threshold,
        }
        d["concurrency"] = {
            "enabled": self.check_concurrency,
            "workers": self.concurrency_workers,
            "timeout_s": self.concurrency_timeout_s,
        }
        d["safety"] = {
            "enabled": self.check_safety,
            "check_pii": self.safety_check_pii,
            "check_injection": self.safety_check_injection,
            "check_hallucination": self.safety_check_hallucination,
        }
        if self.safety_banned_phrases:
            d["safety"]["banned_phrases"] = self.safety_banned_phrases

        d["latency"] = {
            "enabled": self.check_latency,
            "p95_ms": self.latency_p95_ms,
        }
        if self.latency_budget_usd is not None:
            d["latency"]["budget_usd"] = self.latency_budget_usd

        d["test_cases"] = []
        for tc in self.test_cases:
            tcd: dict[str, Any] = {"name": tc.name, "input": tc.input}
            if tc.expected is not None:
                tcd["expected"] = tc.expected
            if tc.expected_contains:
                tcd["expected_contains"] = tc.expected_contains
            if tc.expected_not_contains:
                tcd["expected_not_contains"] = tc.expected_not_contains
            if tc.max_latency_ms is not None:
                tcd["max_latency_ms"] = tc.max_latency_ms
            if tc.tags:
                tcd["tags"] = tc.tags
            d["test_cases"].append(tcd)

        return yaml.dump(d, default_flow_style=False, sort_keys=False)
