import requests

from config import CONFIG

# Singleton OpenAI client — avoids re-instantiating (connection pool setup) on every request.
_openai_client = None


def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        try:
            import openai
            api_key = CONFIG.get("openai_api_key")
            if not api_key or api_key.startswith("sk-xxxx"):
                raise RuntimeError("OpenAI API key not configured.")
            _openai_client = openai.OpenAI(api_key=api_key)
        except ImportError as e:
            raise RuntimeError("openai package not installed.") from e
    return _openai_client


def ask_llm_chat(messages: list) -> str:
    """Send a multi-turn conversation to the LLM.

    Routing:
      backend=ollama  → local Ollama (GPU), falls back to OpenAI on failure
      backend=openai  → OpenAI API, falls back to Ollama on failure
    """
    backend = CONFIG.get('backend', 'ollama')
    if backend == 'ollama':
        try:
            return _ollama_chat(messages)
        except Exception as e:
            openai_key = CONFIG.get("openai_api_key", "")
            if openai_key and not openai_key.startswith("sk-xxxx"):
                print(f"[llm] Ollama failed ({e}), falling back to OpenAI.")
                return _openai_chat(messages)
            raise
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
    model = CONFIG.get('model', 'mistral')
    try:
        resp = requests.post(
            "http://localhost:11434/api/chat",
            json={
                "model": model,
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
        raise RuntimeError(f"Ollama error ({model}): {e}")


def _openai_chat(messages: list) -> str:
    client = _get_openai_client()
    response = client.chat.completions.create(
        model=CONFIG.get("openai_model", "gpt-4o"),
        messages=messages,
    )
    return response.choices[0].message.content
