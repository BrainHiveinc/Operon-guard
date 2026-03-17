"""Test harness for Operon Backend agents.

Wraps real Operon services into single-input callables
that operon-guard can test.

Usage:
    cd ~/Desktop/Operon/operon-guard/examples
    operon-guard test operon_agent.py:local_llm_agent --spec operon_guardfile.yaml
    operon-guard test operon_agent.py:research_agent --spec operon_guardfile.yaml
    operon-guard test operon_agent.py:search_agent --spec operon_guardfile.yaml
"""

import sys
import os

# add Backend1 to path so we can import Operon services
# must be inserted BEFORE 'app' so Python resolves `app.services.*` correctly
_backend_path = os.path.expanduser("~/Desktop/Operon/Backend1")
if _backend_path not in sys.path:
    sys.path.insert(0, _backend_path)

# also ensure the parent env has access to Backend1's dependencies
os.chdir(_backend_path)


async def local_llm_agent(question: str) -> str:
    """Wraps run_local_llm — tests your local Ollama model.

    Requires: Ollama running locally.
    """
    from app.services.local_llm import run_local_llm

    text, _meta = await run_local_llm(
        system_prompt="You are a helpful assistant. Answer concisely.",
        user_prompt=question,
    )
    return text


async def research_agent(question: str) -> str:
    """Wraps quick_research — tests the intelligent research pipeline.

    Requires: At least one LLM provider configured (env vars).
    """
    try:
        from app.services.intelligent_research import quick_research
        result = await quick_research(topic=question, perspective="general")
        return result or "No research results generated."
    except ImportError as e:
        return f"Import error: {e}. Run from Backend1 venv or install deps."


async def search_agent(question: str) -> str:
    """Wraps web_search — tests the search brain.

    Requires: Network access (uses DuckDuckGo).
    """
    try:
        from app.services.sri_search_brain import web_search
        results = await web_search(query=question, max_results=3)
        if not results:
            return "No results found."
        return "\n".join(f"- {r.title}: {r.snippet}" for r in results)
    except ImportError as e:
        return f"Import error: {e}. Run from Backend1 venv or install deps."
