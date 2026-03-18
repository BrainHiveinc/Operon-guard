"""operon-guard CLI — trust verification from your terminal."""

from __future__ import annotations

import asyncio
import logging
import sys
import warnings
from pathlib import Path

# suppress ALL warnings from agent dependencies — operon-guard output only
# override showwarning so nothing can bypass the filter
import os
os.environ["PYTHONWARNINGS"] = "ignore"
warnings.simplefilter("ignore")
warnings.showwarning = lambda *args, **kwargs: None
logging.disable(logging.WARNING)

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, TextColumn

from operon_guard.core.spec import GuardSpec, TestCase
from operon_guard.core.runner import GuardRunner
from operon_guard.core.scorer import TrustReport, Severity, Grade
from operon_guard.core.remediation import get_remedies
from operon_guard.adapters.detect import detect_and_load

console = Console()


# ── Rich formatting helpers ──

def _grade_color(grade: Grade) -> str:
    return {"A": "bold green", "B": "green", "C": "yellow", "D": "red", "F": "bold red"}[grade.value]


def _severity_style(sev: Severity) -> str:
    return {"critical": "bold red", "warning": "yellow", "info": "dim"}[sev.value]


def _severity_icon(sev: Severity) -> str:
    return {"critical": "X", "warning": "!", "info": "-"}[sev.value]


def _render_report(report: TrustReport):
    """Render a beautiful trust report in the terminal."""
    ts = report.trust_score
    grade_style = _grade_color(ts.grade)
    status = "PASS" if ts.passed else "FAIL"
    status_style = "bold green" if ts.passed else "bold red"

    # ── Header panel ──
    header = Text()
    header.append("OPERON GUARD", style="bold cyan")
    header.append(" — Agent Trust Verification\n\n", style="dim")
    header.append(f"Agent:  ", style="dim")
    header.append(f"{report.agent_name}\n", style="bold")
    header.append(f"Status: ", style="dim")
    header.append(f"{status}\n", style=status_style)
    header.append(f"Score:  ", style="dim")
    header.append(f"{ts.overall}/100", style=grade_style)
    header.append(f"  Grade: ", style="dim")
    header.append(f"{ts.grade.value}", style=grade_style)
    header.append(f"\nTests:  ", style="dim")
    header.append(f"{report.test_cases_passed}/{report.test_cases_run} passed")
    header.append(f"  Time: {report.duration_ms:.0f}ms\n", style="dim")

    console.print(Panel(header, border_style="cyan", padding=(1, 2)))

    # ── Check results table ──
    table = Table(title="Check Results", border_style="dim", show_lines=True)
    table.add_column("Check", style="bold", width=15)
    table.add_column("Score", justify="center", width=10)
    table.add_column("Grade", justify="center", width=7)
    table.add_column("Status", justify="center", width=8)
    table.add_column("Key Finding", width=50)

    for name, result in ts.checks.items():
        g = result.grade
        # pick the most important finding to show
        key_finding = ""
        for f in result.findings:
            if f.severity in (Severity.CRITICAL, Severity.WARNING):
                key_finding = f.message[:50]
                break
        if not key_finding:
            info = [f for f in result.findings if f.severity == Severity.INFO]
            if info:
                key_finding = info[0].message[:50]

        table.add_row(
            name.capitalize(),
            f"{result.score:.0f}",
            Text(g.value, style=_grade_color(g)),
            Text("PASS" if result.passed else "FAIL",
                 style="green" if result.passed else "red"),
            key_finding,
        )

    console.print(table)

    # ── Findings detail ──
    critical = [f for f in ts.critical_findings]
    warnings = []
    for cr in ts.checks.values():
        warnings.extend(f for f in cr.findings if f.severity == Severity.WARNING)

    if critical:
        console.print(f"\n[bold red]CRITICAL FINDINGS ({len(critical)}):[/]")
        for f in critical:
            console.print(f"  [red]X[/] [{f.check}] {f.message}")

    if warnings:
        console.print(f"\n[yellow]WARNINGS ({len(warnings)}):[/]")
        for f in warnings[:10]:
            console.print(f"  [yellow]![/] [{f.check}] {f.message}")
        if len(warnings) > 10:
            console.print(f"  [dim]... and {len(warnings) - 10} more[/]")

    # ── Auto-Fix Suggestions ──
    all_actionable = critical + warnings
    seen_titles: set[str] = set()
    fix_count = 0

    for f in all_actionable:
        remedies = get_remedies(f)
        if not remedies:
            continue
        for r in remedies:
            if r.title in seen_titles:
                continue
            seen_titles.add(r.title)
            if fix_count == 0:
                console.print(f"\n[bold cyan]HOW TO FIX:[/]")
            fix_count += 1
            console.print(f"\n  [bold]{fix_count}. {r.title}[/]")
            console.print(f"     [dim]{r.explanation}[/]")
            if r.code:
                console.print()
                for line in r.code.split("\n"):
                    console.print(f"     [green]{line}[/]")

    # ── Footer ──
    console.print(f"\n[dim]operon-guard v0.2.0 — https://github.com/BrainHiveinc/Operon-guard[/]\n")


# ── CLI commands ──

@click.group()
@click.version_option(version="0.2.1", prog_name="operon-guard")
def main():
    """Trust verification for AI agents."""
    pass


@main.command()
@click.argument("agent_path")
@click.option("--spec", "-s", type=click.Path(exists=True), help="Path to guardfile.yaml")
@click.option("--runs", "-r", type=int, default=None, help="Override determinism runs")
@click.option("--workers", "-w", type=int, default=None, help="Override concurrency workers")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def test(agent_path: str, spec: str | None, runs: int | None, workers: int | None, json_output: bool):
    """Run trust verification against an agent.

    AGENT_PATH can be:
      my_agent.py          (auto-detect entry point)
      my_agent.py:run      (specific function)
      my_agent.py:MyAgent  (class, instantiated automatically)
    """
    # ── Load spec ──
    if spec:
        guard_spec = GuardSpec.from_yaml(spec)
    else:
        # auto-discover guardfile
        candidates = ["guardfile.yaml", "guardfile.yml", ".guardfile.yaml", "operon-guard.yaml"]
        found = None
        for c in candidates:
            if Path(c).exists():
                found = c
                break
        if found:
            guard_spec = GuardSpec.from_yaml(found)
            console.print(f"[dim]Using spec: {found}[/]")
        else:
            # minimal default spec with a basic test
            guard_spec = GuardSpec(
                name=Path(agent_path).stem,
                test_cases=[TestCase(name="basic", input="Hello, how can you help me?")],
            )
            console.print("[dim]No guardfile found, using default test case[/]")

    # always use the actual agent name, not whatever is in the guardfile
    agent_stem = agent_path.split(":")[-1] if ":" in agent_path else Path(agent_path).stem
    guard_spec.name = agent_stem

    # apply overrides
    if runs:
        guard_spec.determinism_runs = runs
    if workers:
        guard_spec.concurrency_workers = workers

    # ── Load agent ──
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                  console=console, transient=True) as progress:
        progress.add_task("Loading agent...", total=None)
        try:
            agent_fn, adapter = detect_and_load(agent_path)
        except Exception as e:
            console.print(f"[red]Failed to load agent:[/] {e}")
            sys.exit(1)

    console.print(f"[dim]Adapter: {adapter.name}[/]\n")

    # ── Run checks ──
    runner = GuardRunner(guard_spec)

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                  console=console, transient=True) as progress:
        task = progress.add_task("Running trust verification...", total=None)
        report = asyncio.run(runner.run(agent_fn))
        report.spec_file = spec

    if json_output:
        import json
        out = {
            "agent": report.agent_name,
            "score": report.trust_score.overall,
            "grade": report.trust_score.grade.value,
            "passed": report.trust_score.passed,
            "duration_ms": round(report.duration_ms, 1),
            "checks": {},
        }
        for name, cr in report.trust_score.checks.items():
            out["checks"][name] = {
                "score": cr.score,
                "passed": cr.passed,
                "findings": [
                    {"severity": f.severity.value, "message": f.message}
                    for f in cr.findings
                ],
            }
        console.print_json(json.dumps(out, indent=2))
    else:
        _render_report(report)

    sys.exit(0 if report.trust_score.passed else 1)


@main.command()
@click.argument("agent_path")
def scan(agent_path: str):
    """Quick safety scan — check for PII, injection vulnerabilities, and hallucination patterns."""
    guard_spec = GuardSpec(
        name=Path(agent_path).stem,
        check_determinism=False,
        check_concurrency=False,
        check_latency=False,
        check_safety=True,
        test_cases=[TestCase(name="scan", input="Tell me about yourself and your capabilities.")],
    )

    try:
        agent_fn, adapter = detect_and_load(agent_path)
    except Exception as e:
        console.print(f"[red]Failed to load agent:[/] {e}")
        sys.exit(1)

    runner = GuardRunner(guard_spec)
    report = asyncio.run(runner.run(agent_fn))

    safety = report.trust_score.checks.get("safety")
    if safety:
        console.print(f"\n[bold]Safety Scan: {Path(agent_path).name}[/]")
        console.print(f"Score: [{_grade_color(safety.grade)}]{safety.score}/100[/]\n")
        for f in safety.findings:
            icon = _severity_icon(f.severity)
            style = _severity_style(f.severity)
            console.print(f"  [{style}]{icon}[/] {f.message}")
    console.print()


@main.command()
@click.argument("output", default="guardfile.yaml")
@click.option("--agent", "-a", help="Agent path to inspect and generate tests for")
def init(output: str, agent: str | None):
    """Generate a guardfile.yaml — auto-inspects your agent if path provided."""
    import inspect as _inspect

    agent_name = "my-agent"
    agent_module = "my_agent.py:run"
    test_cases = []
    description = "Agent trust verification spec"

    if agent:
        agent_module = agent
        agent_name = agent.split(":")[0].replace(".py", "").split("/")[-1]

        # try to load and inspect the agent for smart test generation
        try:
            from operon_guard.adapters.detect import load_agent_from_path
            raw = load_agent_from_path(agent)

            # extract docstring for context
            doc = _inspect.getdoc(raw) or ""
            if doc:
                description = doc.split("\n")[0][:100]

            # inspect signature to understand what the agent does
            sig = _inspect.signature(raw)
            params = [p for p in sig.parameters.values() if p.name not in ("self", "cls")]
            param_names = [p.name.lower() for p in params]

            # generate contextual test cases based on parameter names
            if any(k in " ".join(param_names) for k in ("query", "search", "find")):
                test_cases = [
                    TestCase(name="search-basic", input="What is machine learning?"),
                    TestCase(name="search-specific", input="latest developments in AI agents 2026"),
                    TestCase(name="search-empty", input="xyznonexistentqueryzyx"),
                ]
            elif any(k in " ".join(param_names) for k in ("topic", "research", "analyze")):
                test_cases = [
                    TestCase(name="research-broad", input="artificial intelligence trends"),
                    TestCase(name="research-specific", input="how do autonomous agents handle failures"),
                    TestCase(name="research-edge", input=""),
                ]
            elif any(k in " ".join(param_names) for k in ("prompt", "question", "message")):
                test_cases = [
                    TestCase(name="greeting", input="Hello, how can you help me?",
                             expected_contains=["help"]),
                    TestCase(name="factual", input="What is 2 + 2?",
                             expected_contains=["4"]),
                    TestCase(name="reasoning", input="Explain why testing matters for AI agents"),
                ]
            else:
                test_cases = [
                    TestCase(name="basic", input="Hello, how can you help me?"),
                    TestCase(name="detailed", input="Explain your core functionality"),
                    TestCase(name="edge-empty", input=""),
                ]

            console.print(f"[dim]Inspected {agent} — found {len(params)} params, generated {len(test_cases)} test cases[/]")

        except Exception as e:
            console.print(f"[dim]Could not inspect agent ({e}), using default tests[/]")

    if not test_cases:
        test_cases = [
            TestCase(name="greeting", input="Hello, how can you help me?",
                     expected_contains=["help", "assist"],
                     expected_not_contains=["error", "cannot"]),
            TestCase(name="factual", input="What is 2 + 2?",
                     expected_contains=["4"]),
        ]

    spec = GuardSpec(
        name=agent_name,
        description=description,
        agent_module=agent_module,
        test_cases=test_cases,
    )

    Path(output).write_text(spec.to_yaml())
    console.print(f"[green]Created {output}[/] — edit it to match your agent's behavior.")


if __name__ == "__main__":
    main()
