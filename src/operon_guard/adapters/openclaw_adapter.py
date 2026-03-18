"""OpenClaw adapter — wraps OpenClaw skills and agents into testable callables.

OpenClaw is a self-hosted AI assistant that uses a skill system where
skills are defined via SKILL.md files and invoked through messaging platforms.

This adapter detects OpenClaw-style agents by checking for:
  - OpenClaw SDK client objects (ClawHub, OpenClawClient)
  - Skill directories containing SKILL.md files
  - Objects with OpenClaw-specific methods (send_message, run_skill, kickoff)
  - Module paths containing "openclaw" or "clawhub"

It wraps them into the fn(input) -> str interface that operon-guard needs.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Callable

from operon_guard.adapters.base import AgentAdapter


def _resolve_coro(coro):
    """Await a coroutine, handling both sync and async calling contexts.

    Uses a dedicated thread with its own event loop to avoid deadlocking
    when called from within an already-running async loop.
    """
    if not asyncio.iscoroutine(coro):
        raise TypeError(f"Expected a coroutine, got {type(coro).__name__}")
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(1) as pool:
            future = pool.submit(asyncio.run, coro)
            try:
                return future.result(timeout=60)
            except concurrent.futures.TimeoutError:
                future.cancel()
                raise TimeoutError("Async agent call timed out after 60s")
    else:
        return asyncio.run(coro)


class OpenClawAdapter(AgentAdapter):
    """Wrap OpenClaw agents and skills into testable callables.

    Supports:
      1. OpenClaw Python SDK clients (ClawHub, OpenClawClient)
      2. Skill directories (containing SKILL.md)
      3. OpenClaw-style callables with messaging patterns
      4. Direct skill functions that follow OpenClaw conventions
    """

    name = "openclaw"

    def wrap(self, agent: Any) -> Callable[[Any], Any]:
        # ── Case 1: Skill directory path (string pointing to dir with SKILL.md) ──
        if isinstance(agent, (str, Path)):
            skill_path = Path(agent)
            if skill_path.is_dir() and (skill_path / "SKILL.md").exists():
                return self._wrap_skill_dir(skill_path)

        # ── Case 2: OpenClaw SDK client with send_message / run_skill ──
        if hasattr(agent, "run_skill"):
            def _run_skill(inp: Any) -> str:
                result = agent.run_skill(str(inp))
                if asyncio.iscoroutine(result):
                    result = _resolve_coro(result)
                return _extract_openclaw_output(result)
            return _run_skill

        if hasattr(agent, "send_message"):
            def _send(inp: Any) -> str:
                result = agent.send_message(str(inp))
                if asyncio.iscoroutine(result):
                    result = _resolve_coro(result)
                return _extract_openclaw_output(result)
            return _send

        # ── Case 3: ClawHub-style client with search/install ──
        if hasattr(agent, "search") and hasattr(agent, "installed_skills"):
            def _search(inp: Any) -> str:
                result = agent.search(str(inp))
                if asyncio.iscoroutine(result):
                    result = _resolve_coro(result)
                return _extract_openclaw_output(result)
            return _search

        # ── Case 4: Agent with .invoke() or .execute() (common in SDK wrappers) ──
        if hasattr(agent, "invoke"):
            def _invoke(inp: Any) -> str:
                result = agent.invoke(str(inp))
                if asyncio.iscoroutine(result):
                    result = _resolve_coro(result)
                return _extract_openclaw_output(result)
            return _invoke

        if hasattr(agent, "execute"):
            def _execute(inp: Any) -> str:
                result = agent.execute(str(inp))
                if asyncio.iscoroutine(result):
                    result = _resolve_coro(result)
                return _extract_openclaw_output(result)
            return _execute

        # ── Case 5: Callable (function from a skill's scripts/) ──
        if callable(agent):
            def _call(inp: Any) -> str:
                result = agent(str(inp))
                if asyncio.iscoroutine(result):
                    result = _resolve_coro(result)
                return _extract_openclaw_output(result)
            return _call

        raise TypeError(
            f"Cannot wrap OpenClaw object of type {type(agent).__name__}. "
            "Expected a skill directory, SDK client, or callable."
        )

    def _wrap_skill_dir(self, skill_path: Path) -> Callable[[Any], Any]:
        """Wrap a skill directory — finds Python scripts and wraps them.

        OpenClaw skills can have:
          - scripts/*.py files with entry points
          - A main.py or run.py in the skill dir
          - Just SKILL.md (instruction-only skill, no code to test)
        """
        # look for executable Python scripts
        script_candidates = []

        scripts_dir = skill_path / "scripts"
        if scripts_dir.is_dir():
            _skip = {"__init__", "conftest", "setup", "utils", "helpers", "constants"}
            script_candidates.extend(
                sorted(p for p in scripts_dir.glob("*.py") if p.stem not in _skip)
            )

        for name in ("main.py", "run.py", "agent.py", "skill.py"):
            p = skill_path / name
            if p.exists():
                script_candidates.append(p)

        if not script_candidates:
            # instruction-only skill — return SKILL.md content as the "output"
            skill_md = (skill_path / "SKILL.md").read_text()

            def _instruction_skill(inp: Any) -> str:
                return (
                    f"[Instruction-only skill: {skill_path.name}]\n"
                    f"Input: {inp}\n"
                    f"Skill instructions:\n{skill_md[:2000]}"
                )
            return _instruction_skill

        # load the first viable script
        script = script_candidates[0]
        return self._load_script(script)

    def _load_script(self, script_path: Path) -> Callable[[Any], Any]:
        """Load a Python script and find its entry point."""
        import importlib.util

        parent = str(script_path.parent.resolve())
        if parent not in sys.path:
            sys.path.insert(0, parent)
        # don't add further ancestors — limits import hijack surface

        module_name = script_path.stem
        spec = importlib.util.spec_from_file_location(module_name, str(script_path))
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load OpenClaw skill script: {script_path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # find entry point
        for name in ("run", "main", "execute", "process", "agent", "handle"):
            if hasattr(module, name):
                fn = getattr(module, name)
                if callable(fn):
                    def _wrapped(inp: Any, _fn=fn) -> str:
                        result = _fn(str(inp))
                        if asyncio.iscoroutine(result):
                            result = _resolve_coro(result)
                        return _extract_openclaw_output(result)
                    return _wrapped

        raise AttributeError(
            f"No entry point found in {script_path}. "
            "Define a function named 'run', 'main', or 'execute'."
        )

    @classmethod
    def detect(cls, agent: Any) -> bool:
        """Detect if this is an OpenClaw agent, skill, or client."""
        # check module path
        module = getattr(type(agent), "__module__", "") or ""
        module_lower = module.lower()
        if "openclaw" in module_lower or "clawhub" in module_lower:
            return True

        # check class name
        class_name = type(agent).__name__.lower()
        if "openclaw" in class_name or "clawhub" in class_name:
            return True

        # check for OpenClaw-specific method combinations
        if hasattr(agent, "run_skill") and hasattr(agent, "send_message"):
            return True

        # check for ClawHub client pattern
        if hasattr(agent, "search") and hasattr(agent, "installed_skills"):
            return True

        # check if it's a skill directory path
        if isinstance(agent, (str, Path)):
            p = Path(agent)
            if p.is_dir() and (p / "SKILL.md").exists():
                return True

        return False


def _extract_openclaw_output(result: Any, _depth: int = 0) -> str:
    """Extract text from OpenClaw response objects.

    OpenClaw responses can be:
      - Plain strings
      - Dicts with 'content', 'text', 'output', 'message' keys
      - Objects with .content, .text, .raw, .message attributes
      - Lists of messages (extract last assistant message)
    """
    if _depth > 5:
        return str(result)

    if result is None:
        return "No output."

    if isinstance(result, str):
        return result

    if isinstance(result, dict):
        # OpenClaw message format: {role: "assistant", content: "..."}
        if "content" in result:
            return str(result["content"])
        for key in ("text", "output", "message", "result", "response"):
            if key in result:
                return str(result[key])
        return str(result)

    if isinstance(result, list):
        if not result:
            return "No output."
        # list of messages — get last assistant message
        for msg in reversed(result):
            if isinstance(msg, dict):
                if msg.get("role") == "assistant" and "content" in msg:
                    return str(msg["content"])
        # fallback: last item
        return _extract_openclaw_output(result[-1], _depth + 1)

    # object attributes
    for attr in ("content", "text", "raw", "message", "output"):
        if hasattr(result, attr):
            val = getattr(result, attr)
            if val is not None:
                return str(val)

    return str(result)


def load_openclaw_skill(skill_path: str | Path) -> tuple[Callable, OpenClawAdapter]:
    """Convenience: load an OpenClaw skill directory and return (callable, adapter).

    Usage:
        fn, adapter = load_openclaw_skill("./my-skill/")
        report = await GuardRunner(spec).run(fn)
    """
    adapter = OpenClawAdapter()
    fn = adapter.wrap(skill_path)
    return fn, adapter
