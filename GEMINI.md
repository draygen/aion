# GEMINI.md - AION Project Context

## Project Overview
**AION** is a personal AI assistant designed for adaptability and deep integration with personal data. It uses Retrieval Augmented Generation (RAG) to provide context-aware responses based on a large collection of personal facts, message logs, and curated identity data.

### Core Technologies
- **Language Models**: Ollama (local, default `qwen2.5:7b` or `mistral`) and OpenAI (GPT-4o/mini).
- **Backend**: Python 3.11+, Flask (for web/API).
- **Frontend**: Electron (Desktop client), HTML/JS (Web interface).
- **RAG/Memory**: TF-IDF (scikit-learn), OpenAI Embeddings, and Lexical search.
- **Speech**: gTTS and ElevenLabs for text-to-speech.
- **Operations**: Vast.ai integration for GPU cloud deployment.

## Project Structure
- `app.py`: CLI REPL entry point.
- `web.py`: Flask server for REST API and web UI.
- `brain.py`: The RAG engine (loads JSONL facts, manages indexing and retrieval).
- `llm.py`: Abstraction layer for routing prompts to Ollama or OpenAI.
- `config.py`: Central configuration (overridden by `config_local.py` for secrets).
- `auth.py`: SQLite-backed authentication system.
- `tools.py`: Plugin system for extending assistant capabilities.
- `data/`: (Ignored by git) Contains `.jsonl` fact files, `aion.db` (SQLite), and user-specific data.
- `drayops/`: Deployment presets and operational utilities.
- `ui/`: Electron desktop application.

## Building and Running

### Prerequisites
- Python 3.11+ in a virtual environment (`.venv`).
- Ollama running locally (`ollama serve`) for local LLM support.
- Node.js for the Electron UI.

### Key Commands
- **Start CLI**: `./.venv/bin/python app.py`
- **Start Web Server**: `./.venv/bin/python web.py`
- **Run Tests**: `./.venv/bin/python -m unittest discover -p 'test_*.py'`
- **Start Electron UI**: `cd ui && npm start`
- **Build Electron UI**: `cd ui && npm run build` (Windows installer)

## Development Conventions

### Coding Style
- **Python**: 4-space indentation, `snake_case` for functions/variables, `PascalCase` for classes, `ALL_CAPS` for constants.
- **JavaScript (UI)**: CommonJS (`require`/`module.exports`).
- **Commits**: Conventional Commits (e.g., `feat:`, `fix:`, `perf:`).

### RAG & Data Handling
- Facts are stored in JSONL format: `{"input": "...", "output": "...", "_meta": {...}}`.
- Only curated fact types (`curated_fact`, `qa_pair`, `manual_learned`, `imported_fact`) are indexed via TF-IDF to maintain performance.
- Large verbatim logs (e.g., `verbatim_message`) are retrieved via OpenAI embeddings or lexical search.
- When adding new facts via `add_fact`, use `destination="pending"` if the fact requires review.

### Testing
- Tests are located at the root as `test_*.py`.
- Use `unittest` and `unittest.mock` for mocking LLM/API responses.
- **Note**: `test_brain.py` and `test_web_security.py` have known baseline failures; do not treat them as regressions unless new errors are introduced.

### Configuration
- Never commit secrets to `config.py`. Use `config_local.py` for `openai_api_key`, `vast_api_key`, etc.
- The `CONFIG` dictionary in `config.py` is the source of truth for runtime behavior.

## CLI Commands (internal to Aion)
- `/recall`: Show recently loaded facts.
- `/reload`: Refresh the fact index from disk.
- `/why`: Explain why the last answer was given (shows retrieved snippets).
- `/teach Q => A`: Manually add a new fact.
- `/note TEXT`: Add a standalone fact.
- `/set KEY=VALUE`: Update configuration at runtime.
- `/mem-*`: Manage semantic memories (requires `memory_store.py`).
- `/goals`: Manage active goals (requires `goals_store.py`).
