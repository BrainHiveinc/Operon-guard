#!/bin/bash
# nemoclaw-guard — Launch NemoClaw sandbox with operon-guard trust verification
#
# Usage:
#   ./nemoclaw-guard.sh launch --profile default --agent ./my_agent.py
#   ./nemoclaw-guard.sh launch --profile nim-local --agent ./my_agent.py --threshold 80
#
# Flow:
#   1. nemoclaw plan (validate blueprint)
#   2. operon-guard test (trust verification — blocks if score below threshold)
#   3. nemoclaw apply (launch sandbox only if agent passed)

set -euo pipefail

THRESHOLD="${THRESHOLD:-75}"
AGENT_PATH=""
PROFILE="default"
ENDPOINT_URL=""

# Parse args
while [[ $# -gt 0 ]]; do
  case $1 in
    launch) shift ;;
    --profile) PROFILE="$2"; shift 2 ;;
    --agent) AGENT_PATH="$2"; shift 2 ;;
    --threshold) THRESHOLD="$2"; shift 2 ;;
    --endpoint-url) ENDPOINT_URL="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

if [ -z "$AGENT_PATH" ]; then
  echo "Error: --agent <path> is required"
  echo "Usage: ./nemoclaw-guard.sh launch --profile default --agent ./my_agent.py"
  exit 1
fi

echo "=============================================="
echo "  NemoClaw + operon-guard — Verified Launch"
echo "=============================================="
echo ""

# Step 1: Plan
echo "[1/3] Planning NemoClaw deployment..."
PLAN_ARGS="--profile $PROFILE"
if [ -n "$ENDPOINT_URL" ]; then
  PLAN_ARGS="$PLAN_ARGS --endpoint-url $ENDPOINT_URL"
fi
python3 nemoclaw-blueprint/orchestrator/runner.py plan $PLAN_ARGS
echo ""

# Step 2: Trust verification
echo "[2/3] Running operon-guard trust verification..."
echo "  Agent: $AGENT_PATH"
echo "  Threshold: $THRESHOLD/100"
echo ""

if ! command -v operon-guard &> /dev/null; then
  echo "  Installing operon-guard..."
  pip install operon-guard -q
fi

operon-guard test "$AGENT_PATH" --runs 3 --workers 2
GUARD_EXIT=$?

if [ $GUARD_EXIT -ne 0 ]; then
  echo ""
  echo "BLOCKED: Agent failed trust verification."
  echo "Sandbox will NOT be launched."
  echo ""
  echo "Fix the issues above and retry."
  exit 1
fi

echo ""
echo "PASSED: Agent trusted."
echo ""

# Step 3: Apply (launch sandbox)
echo "[3/3] Launching NemoClaw sandbox..."
APPLY_ARGS="--profile $PROFILE"
if [ -n "$ENDPOINT_URL" ]; then
  APPLY_ARGS="$APPLY_ARGS --endpoint-url $ENDPOINT_URL"
fi
python3 nemoclaw-blueprint/orchestrator/runner.py apply $APPLY_ARGS

echo ""
echo "=============================================="
echo "  Sandbox running. Agent verified."
echo "=============================================="
