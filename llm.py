import requests

from config import CONFIG


def ask_llm_chat(messages: list) -> str:
    """Send a multi-turn conversation to the LLM. messages is a list of
    {role, content} dicts (system, user, assistant).

    If backend is 'openai', tries OpenAI first and falls back to Ollama on failure.
    If backend is 'ollama', uses Ollama only.
    """
    backend = CONFIG.get('backend', 'ollama')
    if backend == 'ollama':
        return _ollama_chat(messages)
    elif backend == 'openai':
        try:
            return _openai_chat(messages)
        except Exception as e:
            print(f"[llm] OpenAI failed ({e}), falling back to Ollama.")
            return _ollama_chat(messages)
    else:
        raise ValueError(f"Unsupported backend: {backend}")


def ask_llm(prompt: str) -> str:
    """Legacy single-turn interface. Wraps ask_llm_chat."""
    return ask_llm_chat([{"role": "user", "content": prompt}])


def _ollama_chat(messages: list) -> str:
    try:
        resp = requests.post(
            "http://localhost:11434/api/chat",
            json={
                "model": CONFIG.get('model', 'mistral'),
                "messages": messages,
                "stream": False,
            },
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]
    except requests.exceptions.ConnectionError:
        raise RuntimeError("Ollama not running. Start with: ollama serve")
    except Exception as e:
        raise RuntimeError(f"Ollama error: {e}")


def _openai_chat(messages: list) -> str:
    try:
        import openai
    except ImportError as e:
        raise RuntimeError("openai package not installed.") from e

    api_key = CONFIG.get('openai_api_key')
    if not api_key or api_key.startswith('sk-xxxx'):
        raise RuntimeError("OpenAI API key not configured in config.py.")

    client = openai.OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=CONFIG.get("openai_model", "gpt-4o"),
        messages=messages,
    )
    return response.choices[0].message.content
