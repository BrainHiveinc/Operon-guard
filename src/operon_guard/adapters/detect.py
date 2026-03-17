"""Auto-detect agent framework and load the right adapter.

The goal: ANY agent, ZERO wrappers. The user just points at their file
and operon-guard figures out how to call it.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import sys
from pathlib import Path
from typing import Any, Callable

from operon_guard.adapters.base import AgentAdapter, GenericAdapter


def _get_adapters() -> list[type[AgentAdapter]]:
    """Get all available adapters, framework-specific first."""
    adapters: list[type[AgentAdapter]] = []

    # Try importing framework adapters
    try:
        from operon_guard.adapters.langchain_adapter import RunnableAdapter
        adapters.append(RunnableAdapter)
    except ImportError:
        pass

    try:
        from operon_guard.adapters.crewai_adapter import CrewAdapter
        adapters.append(CrewAdapter)
    except ImportError:
        pass

    try:
        from operon_guard.adapters.autogen_adapter import ConversableAdapter
        adapters.append(ConversableAdapter)
    except ImportError:
        pass

    # Generic is always last — catches plain callables
    adapters.append(GenericAdapter)
    return adapters


def detect_adapter(agent: Any) -> AgentAdapter:
    """Auto-detect the right adapter for an agent object."""
    for adapter_cls in _get_adapters():
        if adapter_cls.detect(agent):
            return adapter_cls()
    raise TypeError(
        f"No adapter found for {type(agent).__name__}. "
        "Ensure your agent is a callable, or install the appropriate framework adapter."
    )


def _smart_wrap(fn: Callable) -> Callable[[str], Any]:
    """Intelligently wrap ANY function into fn(single_string) -> string.

    Handles:
      - fn(question: str) -> str                          # already good
      - fn(system_prompt, user_prompt) -> (text, meta)    # LLM-style
      - fn(query, max_results=5) -> list                  # search-style
      - fn(topic, perspective="general") -> str            # research-style
      - fn(**kwargs) -> Any                                # keyword-heavy
      - class with __call__, run, invoke, generate, execute, process methods
    """
    # if it's a class instance, find the best method to call
    if not callable(fn) and hasattr(fn, '__class__'):
        for method_name in ["__call__", "run", "invoke", "generate", "execute", "process"]:
            if hasattr(fn, method_name):
                fn = getattr(fn, method_name)
                break

    sig = inspect.signature(fn)
    params = list(sig.parameters.values())

    # filter out 'self' and 'cls'
    params = [p for p in params if p.name not in ("self", "cls")]

    if not params:
        # no-arg function — just call it
        def _wrap(inp: str) -> str:
            result = fn()
            if asyncio.iscoroutine(result):
                raise _AsyncMarker(result)
            return _extract_text(result)
        _wrap._is_async = asyncio.iscoroutinefunction(fn)
        return _wrap

    # count required params (no default value)
    required = [p for p in params if p.default is inspect.Parameter.empty
                and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)]
    optional = [p for p in params if p.default is not inspect.Parameter.empty]

    # ── 1 required param: already the ideal shape ──
    if len(required) == 1:
        def _wrap(inp: str) -> str:
            result = fn(inp)
            if asyncio.iscoroutine(result):
                raise _AsyncMarker(result)
            return _extract_text(result)
        _wrap._is_async = asyncio.iscoroutinefunction(fn)
        return _wrap

    # ── 2 required params: likely (system_prompt, user_prompt) or (query, context) ──
    if len(required) == 2:
        name0 = required[0].name.lower()
        name1 = required[1].name.lower()

        # detect LLM-style: (system_prompt, user_prompt)
        if "system" in name0 or "prompt" in name0:
            def _wrap(inp: str) -> str:
                result = fn("You are a helpful assistant. Answer concisely.", inp)
                if asyncio.iscoroutine(result):
                    raise _AsyncMarker(result)
                return _extract_text(result)
            _wrap._is_async = asyncio.iscoroutinefunction(fn)
            return _wrap

        # detect (query/topic, context/perspective)
        if any(k in name0 for k in ("query", "topic", "question", "input", "text")):
            def _wrap(inp: str) -> str:
                result = fn(inp, "general")
                if asyncio.iscoroutine(result):
                    raise _AsyncMarker(result)
                return _extract_text(result)
            _wrap._is_async = asyncio.iscoroutinefunction(fn)
            return _wrap

        # generic 2-arg: pass input as first, empty string as second
        def _wrap(inp: str) -> str:
            result = fn(inp, "")
            if asyncio.iscoroutine(result):
                raise _AsyncMarker(result)
            return _extract_text(result)
        _wrap._is_async = asyncio.iscoroutinefunction(fn)
        return _wrap

    # ── 3+ required params: try to fill with sensible defaults ──
    if len(required) >= 3:
        def _wrap(inp: str) -> str:
            kwargs = {}
            for i, p in enumerate(required):
                name = p.name.lower()
                if i == 0 or any(k in name for k in ("query", "topic", "question",
                                                       "input", "text", "prompt", "user")):
                    kwargs[p.name] = inp
                elif any(k in name for k in ("system", "role")):
                    kwargs[p.name] = "You are a helpful assistant."
                elif any(k in name for k in ("context", "perspective", "mode")):
                    kwargs[p.name] = "general"
                elif p.annotation in (int, float) or "max" in name or "limit" in name:
                    kwargs[p.name] = 5
                elif p.annotation == bool or "enable" in name or "verbose" in name:
                    kwargs[p.name] = False
                else:
                    kwargs[p.name] = inp  # fallback: pass input
            result = fn(**kwargs)
            if asyncio.iscoroutine(result):
                raise _AsyncMarker(result)
            return _extract_text(result)
        _wrap._is_async = asyncio.iscoroutinefunction(fn)
        return _wrap

    # ── Only optional params with 1+ required: pass input to the required one ──
    if len(required) == 0 and optional:
        # all optional — pass input as first positional
        def _wrap(inp: str) -> str:
            result = fn(inp)
            if asyncio.iscoroutine(result):
                raise _AsyncMarker(result)
            return _extract_text(result)
        _wrap._is_async = asyncio.iscoroutinefunction(fn)
        return _wrap

    # fallback
    def _wrap(inp: str) -> str:
        result = fn(inp)
        if asyncio.iscoroutine(result):
            raise _AsyncMarker(result)
        return _extract_text(result)
    _wrap._is_async = asyncio.iscoroutinefunction(fn)
    return _wrap


class _AsyncMarker(Exception):
    """Internal: carries a coroutine that needs to be awaited."""
    def __init__(self, coro):
        self.coro = coro


def _extract_text(result: Any) -> str:
    """Extract text from any agent return type.

    Handles:
      - str                           → as-is
      - (text, meta) tuple            → text
      - dict with 'text'/'output'     → that field
      - list of results               → joined
      - object with .content/.text    → that attr
      - anything else                 → str()
    """
    if isinstance(result, str):
        return result

    if isinstance(result, tuple) and len(result) >= 1:
        return str(result[0])

    if isinstance(result, dict):
        for key in ("text", "output", "content", "result", "answer", "response"):
            if key in result:
                return str(result[key])
        return str(result)

    if isinstance(result, list):
        if not result:
            return "No results."
        # if list of objects with title/snippet, format them
        first = result[0]
        if hasattr(first, "title") and hasattr(first, "snippet"):
            return "\n".join(f"- {r.title}: {r.snippet}" for r in result[:10])
        return "\n".join(str(r) for r in result[:10])

    if hasattr(result, "content"):
        return str(result.content)
    if hasattr(result, "text"):
        return str(result.text)
    if hasattr(result, "raw"):
        return str(result.raw)

    return str(result) if result is not None else "No output."


async def _async_smart_call(wrapped_fn: Callable, inp: str) -> str:
    """Call a smart-wrapped function, handling both sync and async agents."""
    try:
        result = wrapped_fn(inp)
        return result
    except _AsyncMarker as am:
        result = await am.coro
        return _extract_text(result)


def load_agent_from_path(path: str) -> Any:
    """Load an agent from a module:attribute path.

    Supports:
      - "my_agent.py:run"          → loads function `run` from my_agent.py
      - "my_agent:MyAgent"         → loads class `MyAgent` and instantiates it
      - "my_agent.py"              → looks for `agent`, `run`, `main`, or first callable
    """
    if ":" in path:
        module_path, attr_name = path.rsplit(":", 1)
    else:
        module_path = path
        attr_name = None

    # resolve to actual file
    file_path = Path(module_path).resolve()
    if not file_path.exists():
        raise FileNotFoundError(f"Agent file not found: {file_path}")

    # add parent dir to sys.path for imports
    parent = str(file_path.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)

    # also add grandparent if the file is inside a package (e.g. app/services/foo.py)
    grandparent = str(file_path.parent.parent)
    if grandparent not in sys.path:
        sys.path.insert(0, grandparent)
    great_grandparent = str(file_path.parent.parent.parent)
    if great_grandparent not in sys.path:
        sys.path.insert(0, great_grandparent)

    # import the module
    module_name = file_path.stem
    spec = importlib.util.spec_from_file_location(module_name, str(file_path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {file_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if attr_name:
        agent = getattr(module, attr_name)
        # if it's a class, instantiate it
        if isinstance(agent, type):
            agent = agent()
        return agent

    # auto-detect: look for common names
    for name in ["agent", "run", "main", "execute", "process", "invoke",
                  "generate", "predict", "call", "query", "search"]:
        if hasattr(module, name):
            agent = getattr(module, name)
            if isinstance(agent, type):
                agent = agent()
            return agent

    # find first callable that isn't a built-in or import
    for name in dir(module):
        if name.startswith("_"):
            continue
        obj = getattr(module, name)
        if callable(obj) and not isinstance(obj, type) and hasattr(obj, "__module__"):
            if obj.__module__ == module_name:
                return obj

    raise AttributeError(
        f"No agent found in {file_path}. "
        "Define a function named `run`, `agent`, or `main`, "
        "or specify it as `my_agent.py:my_function`."
    )


def detect_and_load(path: str) -> tuple[Callable, AgentAdapter]:
    """Load agent from path, auto-detect framework, smart-wrap for testing.

    This handles ANY agent signature — no wrapper needed from the user.
    """
    raw_agent = load_agent_from_path(path)

    # first try framework adapters
    for adapter_cls in _get_adapters():
        if adapter_cls.detect(raw_agent) and not isinstance(adapter_cls, type(GenericAdapter)):
            adapter = adapter_cls()
            fn = adapter.wrap(raw_agent)
            return fn, adapter

    # for generic callables, use smart wrapping
    if callable(raw_agent):
        wrapped = _smart_wrap(raw_agent)
        is_async = getattr(wrapped, "_is_async", False) or asyncio.iscoroutinefunction(raw_agent)

        if is_async:
            async def _async_fn(inp: str) -> str:
                return await _async_smart_call(wrapped, inp)
            adapter = GenericAdapter()
            adapter.name = "generic (auto-wrapped)"
            return _async_fn, adapter
        else:
            adapter = GenericAdapter()
            adapter.name = "generic (auto-wrapped)"
            return wrapped, adapter

    raise TypeError(
        f"Cannot test {type(raw_agent).__name__}. "
        "Ensure your agent is a callable (function, class with __call__, etc.)"
    )
