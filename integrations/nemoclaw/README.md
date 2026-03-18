# operon-guard × NemoClaw Integration

Pre-launch trust verification for NemoClaw sandboxes. If the agent fails the trust score, the sandbox never starts.

## How It Works

```
nemoclaw plan → operon-guard test → nemoclaw apply
                     ↓
              Score < threshold?
                     ↓
              BLOCKED. No sandbox.
```

operon-guard runs between NemoClaw's `plan` and `apply` phases. It fires 47 injection payloads, scans for PII, tests concurrency, and measures determinism. If the agent scores below the threshold, the sandbox launch is blocked.

## Quick Start

```bash
# Option 1: Wrapper script (recommended)
./nemoclaw-guard.sh launch --profile default --agent ./my_agent.py

# Option 2: Manual pipeline
nemoclaw plan --profile default
python pre_launch_guard.py ./my_agent.py --threshold 80
nemoclaw apply --profile default

# Option 3: In your own script
operon-guard test ./my_agent.py --json | python -c "
import json, sys
r = json.load(sys.stdin)
sys.exit(0 if r['score'] >= 75 else 1)
" && nemoclaw apply --profile default
```

## Network Policy

If your NemoClaw sandbox needs to install operon-guard, add the policy from `operon-guard-policy.yaml` to your blueprint:

```yaml
# blueprint.yaml
components:
  policy:
    additions:
      operon_guard:
        name: operon_guard
        endpoints:
          - host: pypi.org
            port: 443
            protocol: rest
            rules:
              - allow: { method: GET, path: "/**" }
          - host: files.pythonhosted.org
            port: 443
            protocol: rest
            rules:
              - allow: { method: GET, path: "/**" }
```

## Files

- `pre_launch_guard.py` — Standalone trust gate (exit 0 = pass, exit 1 = fail)
- `nemoclaw-guard.sh` — Wrapper that chains plan → verify → apply
- `operon-guard-policy.yaml` — Network policy addition for sandbox installation

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Agent passed — safe to launch |
| 1 | Agent failed — sandbox blocked |
| 2 | operon-guard not installed |
