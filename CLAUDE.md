# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Use the repo virtualenv, not system Python:

```bash
# CLI assistant
./.venv/bin/python app.py

# Flask web server (local dev)
./.venv/bin/python web.py

# Run all tests (from repo root — avoids recursing into data/)
./.venv/bin/python -m unittest discover -s . -p 'test_*.py'

# Run a single test file
./.venv/bin/python -m unittest test_brain.py

# Quick prompt to local Ollama
./run.sh "Hello"

# Electron desktop client
cd ui && npm start
cd ui && npm run build  # builds Windows installer to ui/dist/
```

**Known baseline failures**: `test_brain.py` and `test_web_security.py` have two pre-existing failures — do not count these as regressions.

## Architecture

AION is a personal AI assistant with CLI and web interfaces, RAG-based fact retrieval, and optional Vast.ai GPU deployment.

### Data flow (conversation)

1. User input → `app.py` (CLI) or `web.py` (HTTP)
2. `brain.py` retrieves top-k relevant facts via: OpenAI embeddings → TF-IDF → lexical fallback
3. Facts + optional `profile_builder.py` summary injected into system prompt → `llm.py` routes to Ollama or OpenAI
4. Response returned; CLI optionally speaks via gTTS/ElevenLabs

### Key modules

| Module | Role |
|--------|------|
| `app.py` | CLI REPL — reads input, runs commands, builds prompts, calls TTS |
| `web.py` | Flask server — REST API, chat endpoints, Vast.ai admin, auth |
| `brain.py` | Fact retrieval engine — loads JSONL facts, manages 3-tier embedding/TF-IDF/lexical search with caching |
| `llm.py` | LLM abstraction — `ask_llm_chat()` routes between Ollama (localhost:11434) and OpenAI with automatic fallback |
| `commands.py` | Command parser — maps `/recall`, `/teach`, `/mem`, `/goals`, etc. to handlers |
| `config.py` | Config singleton — model name, backend (`ollama`/`openai`), retrieval mode, user→fact file mappings |
| `auth.py` | SQLite-backed auth — users, sessions, bcrypt passwords, `@login_required`/`@admin_required` decorators |
| `vast.py` | Vast.ai GPU management — list offers, deploy/destroy instances |
| `memory_store.py` / `goals_store.py` | Optional semantic memory and goals — imported with graceful `ImportError` fallback in both `app.py` and `web.py`; check `_MEMORY_AVAILABLE` flag before using |
| `profile_builder.py` | Builds and caches a GPT-4o profile summary prepended to every system prompt |
| `tools.py` | Plugin/tool system for extensible LLM capabilities |
| `events.py` | Lightweight event log — `log_event()` / `list_events()` used by web.py for audit trail |
| `extractor.py` | Auto-extracts facts from conversation turns and saves them to pending/shared stores |

### Brain.py retrieval details

Facts are stored as JSONL records: `{"input": "...", "output": "...", "_meta": {"source_type": "...", "trusted": true, "status": "active"}}`.

Source types: `curated_fact`, `qa_pair`, `manual_learned`, `imported_fact`, `verbatim_message`, `llm_extracted_pending`.

**Critical**: only `curated_fact | qa_pair | manual_learned | imported_fact` are fed into TF-IDF (`_index_memory`). `verbatim_message` records (raw FB message logs, ~26K docs) are excluded from the TF-IDF matrix to keep build time under ~200ms. They are still reachable via OpenAI embedding path or lexical fallback.

Query result cache TTL is 600 seconds (`_FACTS_CACHE_TTL`). Invalidated on `add_fact()`.

### Configuration

`config.py` sets defaults; `config_local.py` (not in git) overrides with actual secrets:

```python
# config_local.py pattern
CONFIG_LOCAL = {
    "openai_api_key": "sk-...",
    "vast_api_key": "...",
    "admin_password": "...",
}
```

Key config values:
- `model`: Ollama model name (default `qwen2.5:7b`)
- `backend`: `ollama` (tries Ollama first, falls back to OpenAI) or `openai`
- `retrieval`: `embed` (semantic) or `lexical`
- `embed_backend`: `tfidf` or `openai`
- `primary_user`: scopes fact files and memory (e.g. `brian`)
- `memory_enabled`, `goals_enabled`: feature flags for `memory_store`/`goals_store`

### Data files (in `data/`, not in git)

- `aion.db` — SQLite: users, sessions
- `profile.jsonl`, `brian_facts.jsonl`, `fb_qa_pairs.jsonl` — curated identity facts
- `fb_messages_parsed.jsonl`, `jenn_messages.jsonl` — verbatim message logs (excluded from TF-IDF index)
- `embeddings_cache.pkl` — disk cache for OpenAI embeddings (keyed by MD5 of fact text)
- `shared_learned.jsonl`, `pending_learned.jsonl` — runtime-learned facts
- `data/users/<username>/learned.jsonl` — per-user scoped facts

### CLI commands (handled by `commands.py`)

`/recall`, `/reload`, `/why` (show last retrieval snippets), `/teach <q> | <a>`, `/note <text>`, `/set <key> <value>`, `/mem [text]`, `/mem-search <query>`, `/mem-recent`, `/mem-delete <id>`, `/goals`, `/goal-add`, `/goal-done`

### Deployment

Deployment targets Vast.ai GPU instances. `deploy.sh` installs Ollama, pulls `qwen2.5:7b`, and starts Flask via gunicorn on port 5000. `vast.py` and the `/admin` routes in `web.py` manage instance lifecycle.

## Coding conventions

- 4-space indentation, `snake_case` functions/modules, `PascalCase` test classes, `ALL_CAPS` constants
- New runtime modules go at repo root; utilities go in `drayops/`
- Tests use `unittest` with `unittest.mock`; name tests explicitly (e.g. `test_build_system_prompt_scopes_memory_to_username`)
- Conventional Commits: `feat:`, `fix:`, `perf:` prefixes, imperative mood
- `ui/` uses CommonJS (`require`/`module.exports`)
