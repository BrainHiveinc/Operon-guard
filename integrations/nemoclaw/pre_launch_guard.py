#!/usr/bin/env python3
"""
operon-guard × NemoClaw — Pre-Launch Trust Gate
================================================
Runs between NemoClaw's plan and apply phases.
If the agent fails the trust score, the sandbox never starts.

Usage:
  # As standalone pre-launch check:
  python pre_launch_guard.py /path/to/agent --threshold 75

  # In NemoClaw blueprint flow:
  nemoclaw plan --profile default
  python pre_launch_guard.py /sandbox/agent.py --threshold 80
  nemoclaw apply --profile default

  # In a wrapper script:
  nemoclaw-guard launch --profile default --agent /sandbox/agent.py

Exit codes:
  0 = agent passed trust verification → safe to launch sandbox
  1 = agent failed → DO NOT launch sandbox
  2 = operon-guard not installed
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def check_operon_guard_installed() -> bool:
    """Check if operon-guard is available."""
    try:
        subprocess.run(
            ["operon-guard", "--version"],
            capture_output=True, text=True, timeout=10,
        )
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def run_trust_check(
    agent_path: str,
    threshold: int = 75,
    runs: int = 3,
    workers: int = 2,
) -> dict:
    """Run operon-guard and return the trust report."""
    cmd = [
        "operon-guard", "test", agent_path,
        "--runs", str(runs),
        "--workers", str(workers),
        "--json",
    ]

    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=300,
    )

    # Parse JSON output
    try:
        report = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return {
            "score": 0,
            "grade": "F",
            "passed": False,
            "error": f"Failed to parse operon-guard output: {result.stderr[:200]}",
        }

    return report


def print_gate_result(report: dict, threshold: int) -> None:
    """Print a clear pass/fail message for the NemoClaw pipeline."""
    score = report.get("score", 0)
    grade = report.get("grade", "?")
    passed = score >= threshold

    print()
    print("=" * 60)
    print("  OPERON GUARD — Pre-Launch Trust Gate")
    print("=" * 60)
    print(f"  Trust Score:  {score}/100  (Grade {grade})")
    print(f"  Threshold:    {threshold}/100")
    print(f"  Verdict:      {'PASS — safe to launch sandbox' if passed else 'FAIL — sandbox launch blocked'}")
    print()

    # Show check breakdown
    checks = report.get("checks", {})
    for name, data in checks.items():
        check_score = data.get("score", 0)
        check_passed = data.get("passed", False)
        icon = "+" if check_passed else "X"
        print(f"  [{icon}] {name:15s} {check_score:.0f}/100")

    print()

    # Show critical findings
    for name, data in checks.items():
        for f in data.get("findings", []):
            if f.get("severity") == "critical":
                print(f"  CRITICAL: [{name}] {f['message']}")

    print("=" * 60)

    if not passed:
        print()
        print("  Sandbox launch BLOCKED by operon-guard.")
        print("  Fix the issues above and retry.")
        print("  Run: operon-guard test <agent> for full report with fixes.")
        print()


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="operon-guard pre-launch trust gate for NemoClaw",
    )
    parser.add_argument("agent_path", help="Path to the agent to verify")
    parser.add_argument(
        "--threshold", type=int, default=75,
        help="Minimum trust score to allow sandbox launch (default: 75)",
    )
    parser.add_argument(
        "--runs", type=int, default=3,
        help="Number of determinism runs (default: 3)",
    )
    parser.add_argument(
        "--workers", type=int, default=2,
        help="Number of concurrency workers (default: 2)",
    )
    parser.add_argument(
        "--json", dest="json_output", action="store_true",
        help="Output result as JSON (for pipeline integration)",
    )

    args = parser.parse_args()

    # Check operon-guard is installed
    if not check_operon_guard_installed():
        print("ERROR: operon-guard not installed.")
        print("  Install: pip install operon-guard")
        sys.exit(2)

    # Run trust verification
    report = run_trust_check(
        args.agent_path,
        threshold=args.threshold,
        runs=args.runs,
        workers=args.workers,
    )

    if args.json_output:
        gate_result = {
            "gate": "operon-guard",
            "agent": args.agent_path,
            "score": report.get("score", 0),
            "grade": report.get("grade", "F"),
            "threshold": args.threshold,
            "passed": report.get("score", 0) >= args.threshold,
            "checks": report.get("checks", {}),
        }
        print(json.dumps(gate_result, indent=2))
    else:
        print_gate_result(report, args.threshold)

    # Exit code determines if NemoClaw proceeds
    score = report.get("score", 0)
    sys.exit(0 if score >= args.threshold else 1)


if __name__ == "__main__":
    main()
