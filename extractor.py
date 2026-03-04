"""Background fact extraction from conversations."""
import json
import re
import threading

from brain import add_fact
from llm import ask_llm_chat


def extract_and_save(user_msg: str, assistant_msg: str, source_user: str = ""):
    """Fire-and-forget: starts a daemon thread, returns immediately."""
    threading.Thread(
        target=_extract_worker,
        args=(user_msg, assistant_msg, source_user),
        daemon=True,
    ).start()


def _extract_worker(user_msg: str, assistant_msg: str, source_user: str):
    try:
        prompt = (
            "Extract factual statements from this conversation worth remembering long-term. "
            "Focus on: people's names/relationships, locations, preferences, important facts.\n"
            "Return ONLY a JSON array of short fact strings. If nothing worth saving, return [].\n\n"
            f"User ({source_user}): {user_msg}\n"
            f"Assistant: {assistant_msg}\n\n"
            "JSON array of facts:"
        )
        response = ask_llm_chat([{"role": "user", "content": prompt}])

        # Find first [...] in response
        match = re.search(r'\[.*?\]', response, re.DOTALL)
        if not match:
            return

        facts = json.loads(match.group(0))
        if not isinstance(facts, list):
            return

        for fact in facts:
            if isinstance(fact, str) and fact.strip():
                add_fact(None, fact.strip())
    except Exception as e:
        print(f"[extractor] Error: {e}")
