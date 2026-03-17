"""Example agent — a simple Q&A function for testing operon-guard."""


def run(question: str) -> str:
    """A basic agent that answers questions (no LLM, just pattern matching).

    Replace this with your real agent — any framework agent or plain callable.
    """
    q = question.lower().strip()

    if "hello" in q or "hi" in q:
        return "Hello! I'm a helpful assistant. I can help you with questions and tasks."

    if "2 + 2" in q or "2+2" in q:
        return "2 + 2 equals 4."

    if "capital" in q and "france" in q:
        return "The capital of France is Paris."

    if "weather" in q:
        return "I don't have access to real-time weather data, but I can help you find weather services."

    return f"I received your question: '{question[:100]}'. Let me help you with that."
