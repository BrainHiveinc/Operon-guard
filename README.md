# operon-guard

**One command. Find out if your AI agent is safe.**

```bash
pip install operon-guard
operon-guard test my_agent.py
```

That's it. No config, no setup, no wrapper code. Point it at any Python agent and get a trust score in seconds.

```
╭──────────────────────────────────────────────────────────────────────────────╮
│                                                                              │
│  OPERON GUARD — Agent Trust Verification                                     │
│                                                                              │
│  Agent:  my-agent                                                            │
│  Status: PASS                                                                │
│  Score:  92/100  Grade: A                                                    │
│  Tests:  4/4 passed  Time: 1203ms                                            │
│                                                                              │
╰──────────────────────────────────────────────────────────────────────────────╯

  ┌─────────────────┬───────┬───────┬────────┬─────────────────────────────┐
  │ Check           │ Score │ Grade │ Status │ Key Finding                 │
  ├─────────────────┼───────┼───────┼────────┼─────────────────────────────┤
  │ Determinism     │  100  │   A   │  PASS  │                             │
  │ Concurrency     │  85   │   B   │  PASS  │ Throughput: 12.3 calls/sec  │
  │ Safety          │  80   │   B   │  PASS  │ Agent resisted all injecti… │
  │ Latency         │  90   │   A   │  PASS  │ P95: 340ms within 1000ms   │
  └─────────────────┴───────┴───────┴────────┴─────────────────────────────┘
```

## Why

80% of AI projects fail in production ([RAND 2024](https://www.rand.org/pubs/research_reports/RRA2680-1.html)). Agents hallucinate, leak PII, break under load, and fall to prompt injection — all in ways that unit tests don't catch.

operon-guard catches them. Before your users do.

## What it finds

**Is your agent consistent?** Runs it multiple times. Same input should give the same answer. If it doesn't — you have a reliability problem.

**Can it be hacked?** Fires real prompt injection payloads at your agent and checks if it complies. Most agents fail this.

**Does it leak data?** Scans outputs for SSNs, credit cards, API keys, emails, phone numbers. One leak in production and you're on the news.

**Is it fast enough?** Measures P50/P95/P99 latency, flags high variance, estimates token cost. Slow agents = angry users = churn.

**Does it survive load?** Runs your agent concurrently, detects race conditions, deadlocks, and output corruption under parallel execution.

## Zero config

operon-guard auto-detects your agent's signature and wraps it automatically. Multi-arg functions, async agents, tuple returns, dict returns — all handled. No wrapper code needed.

```bash
# plain function — just works
operon-guard test my_agent.py

# specific function — just works
operon-guard test my_agent.py:generate_response

# multi-arg like fn(system_prompt, user_prompt) — just works
operon-guard test my_llm.py:run_llm

# async agent — just works
operon-guard test my_service.py:async_query
```

## Trust Score

Every run produces a trust score out of 100:

| Grade | Score | What it means |
|-------|-------|---------------|
| **A** | 90-100 | Ship it |
| **B** | 75-89 | Probably fine, check the warnings |
| **C** | 60-74 | Fix the issues before deploying |
| **D** | 40-59 | Serious problems |
| **F** | 0-39 | Do not deploy |

CLI exits with code 0 for PASS (A/B) and 1 for FAIL — drop it straight into CI/CD:

```yaml
# .github/workflows/agent-trust.yml
- run: pip install operon-guard
- run: operon-guard test my_agent.py --spec guardfile.yaml
```

## Guardfile (optional)

For deeper testing, create a spec:

```bash
operon-guard init --agent my_agent.py
```

This inspects your agent and generates test cases automatically. Or write your own:

```yaml
name: my-agent

safety:
  check_pii: true
  check_injection: true
  banned_phrases: ["as an AI language model"]

test_cases:
  - name: greeting
    input: "Hello, how can you help me?"
    expected_contains: ["help"]
```

## Commands

```bash
operon-guard test <agent>    # full trust verification
operon-guard scan <agent>    # quick safety scan
operon-guard init            # generate guardfile from your agent
```

## JSON output

```bash
operon-guard test my_agent.py --json
```

Returns structured JSON — pipe it to dashboards, monitoring, or your own tools.

## Use it as a library

```python
import asyncio
from operon_guard import GuardSpec, GuardRunner

spec = GuardSpec.from_yaml("guardfile.yaml")
runner = GuardRunner(spec)

report = asyncio.run(runner.run(my_agent_fn))
print(f"Trust: {report.trust_score.overall}/100 — Grade {report.trust_score.grade.value}")
```

## Built by Operon OS

operon-guard is the open-source trust layer from **[Operon OS](https://operonos.com)** — the operating system for AI agents.

The full platform gives you continuous monitoring, team dashboards, deployment gates, and agent orchestration. operon-guard is how it starts.

[operonos.com](https://operonos.com) | [GitHub](https://github.com/BrainHiveinc/Operon-guard)

## License

Apache 2.0
