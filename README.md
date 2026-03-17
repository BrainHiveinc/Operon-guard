# operon-guard

**Trust verification for AI agents.** Test behavior, catch race conditions, detect safety issues, and get a trust score — before your agents hit production.

> 80% of AI projects fail in production (RAND 2024). operon-guard makes sure yours don't.

```
$ operon-guard test my_agent.py

  OPERON GUARD — Agent Trust Verification

  Agent:  my-agent
  Status: PASS
  Score:  87/100  Grade: B
  Tests:  4/4 passed  Time: 1203ms

  ┌─────────────────┬───────┬───────┬────────┬─────────────────────────────┐
  │ Check           │ Score │ Grade │ Status │ Key Finding                 │
  ├─────────────────┼───────┼───────┼────────┼─────────────────────────────┤
  │ Determinism     │  92   │   A   │  PASS  │                             │
  │ Concurrency     │  85   │   B   │  PASS  │ Throughput: 12.3 calls/sec  │
  │ Safety          │  80   │   B   │  PASS  │ Agent resisted all injecti… │
  │ Latency         │  90   │   A   │  PASS  │ P95: 340ms within 1000ms   │
  └─────────────────┴───────┴───────┴────────┴─────────────────────────────┘
```

## Install

```bash
pip install operon-guard
```

## Quick Start

### 1. Write your agent

Any Python callable works — a function, a class, or any agent framework object:

```python
# my_agent.py
def run(question: str) -> str:
    return call_my_llm(question)
```

### 2. Create a guardfile

```bash
operon-guard init --agent my_agent.py:run
```

This creates `guardfile.yaml`:

```yaml
name: my-agent
agent_module: my_agent.py:run

determinism:
  runs: 5
  threshold: 0.8

safety:
  check_pii: true
  check_injection: true
  check_hallucination: true

test_cases:
  - name: greeting
    input: "Hello, how can you help me?"
    expected_contains: ["help", "assist"]
```

### 3. Run verification

```bash
operon-guard test my_agent.py
```

## What It Checks

### Determinism (30% of score)

Runs your agent N times per test case and measures output consistency. Catches non-deterministic failures that only show up in production.

- Structural similarity (exact text overlap)
- Semantic key overlap (same facts, different words)
- Expected output matching
- Contains / not-contains assertions

### Concurrency (25% of score)

Race condition and deadlock detection powered by the Operon Race Controller engine.

- Static analysis for shared mutable state
- Concurrent execution with configurable workers
- Timeout detection (potential deadlocks)
- Output consistency under parallel load
- Throughput measurement

### Safety (30% of score)

Comprehensive output scanning and active penetration testing.

- **PII detection**: SSNs, credit cards, emails, phone numbers, API keys
- **Prompt injection resistance**: Active testing with injection payloads
- **Hallucination markers**: False confidence, fabricated citations, invented stats
- **Banned phrases**: Custom blocklist

### Latency & Cost (15% of score)

Performance profiling and budget enforcement.

- P50/P95/P99 latency measurement
- Variance detection (unpredictable = unreliable)
- Token cost estimation
- Per-case latency limits
- Budget enforcement

## Trust Score

Scores map to grades:

| Grade | Score   | Meaning              |
|-------|---------|----------------------|
| A     | 90-100  | Production-ready     |
| B     | 75-89   | Mostly safe          |
| C     | 60-74   | Needs attention      |
| D     | 40-59   | Significant risks    |
| F     | 0-39    | Do not deploy        |

The CLI exits with code 0 for PASS (A/B) and 1 for FAIL — plug it straight into your CI/CD.

## Framework Support

operon-guard auto-detects your agent framework. Just point it at your agent file:

```bash
# Plain function
operon-guard test my_agent.py:run

# Any framework agent — auto-detected
operon-guard test my_chain.py:chain
operon-guard test my_crew.py:crew
operon-guard test my_agent.py:agent
```

Built-in adapters for popular agent frameworks. If your agent has `.invoke()`, `.kickoff()`, `.generate_reply()`, or is a plain callable — it just works.

## CI/CD Integration

```yaml
# .github/workflows/agent-trust.yml
name: Agent Trust Check
on: [push, pull_request]
jobs:
  trust:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install operon-guard
      - run: operon-guard test my_agent.py --spec guardfile.yaml
```

## Commands

```bash
operon-guard test <agent>     # Full trust verification
operon-guard scan <agent>     # Quick safety scan only
operon-guard init             # Generate starter guardfile.yaml
```

## Options

```bash
operon-guard test my_agent.py \
  --spec guardfile.yaml  \   # Custom spec file
  --runs 10              \   # Override determinism runs
  --workers 8            \   # Override concurrency workers
  --json                     # JSON output for CI/CD
```

## Programmatic Usage

```python
import asyncio
from operon_guard import GuardSpec, GuardRunner

spec = GuardSpec.from_yaml("guardfile.yaml")
runner = GuardRunner(spec)

async def verify():
    from my_agent import run
    report = await runner.run(run)
    print(f"Score: {report.trust_score.overall}/100")
    print(f"Grade: {report.trust_score.grade.value}")
    return report.trust_score.passed

asyncio.run(verify())
```

## Built by Operon OS

operon-guard is the open-source trust layer from [Operon OS](https://operonos.com) — the operating system for AI agents. If you need full agent infrastructure (orchestration, monitoring, governance), check out the full platform.

## License

Apache 2.0
