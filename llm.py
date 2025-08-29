import subprocess
from typing import Optional

from config import CONFIG

def ask_llm(prompt: str) -> str:
    backend = CONFIG.get('backend', 'ollama')
    if backend == 'ollama':
        return run_ollama(prompt)
    elif backend == 'openai':
        return run_openai(prompt)
    else:
        raise ValueError(f"Unsupported backend: {backend}")

def run_ollama(prompt: str) -> str:
    try:
        result = subprocess.run(
            ["ollama", "run", CONFIG.get('model', 'mistral')],
            input=prompt.encode('utf-8'),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode != 0:
            err = result.stderr.decode('utf-8', errors='ignore')
            raise RuntimeError(f"ollama run failed (code {result.returncode}). Is Ollama installed and the model pulled?\n{err}")
        return result.stdout.decode('utf-8', errors='ignore')
    except FileNotFoundError:
        raise RuntimeError("Ollama not found. Install from https://ollama.com and ensure 'ollama' is on PATH.")

def run_openai(prompt: str) -> str:
    try:
        import openai  # Lazy import so ollama-only users don't need this package
    except Exception as e:
        raise RuntimeError("openai package not installed. Install with 'pip install openai' or switch backend to 'ollama'.") from e

    api_key = CONFIG.get('openai_api_key')
    if not api_key or api_key.startswith('sk-xxxx'):
        raise RuntimeError("OpenAI API key not configured. Set CONFIG['openai_api_key'] in config.py.")

    openai.api_key = api_key
    response = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
    )
    return response['choices'][0]['message']['content']
