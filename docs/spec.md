# Aion Specification

## Purpose
Aion is a personal AI assistant that combines chat, retrieval, memory, and operator tooling in one Python codebase. It serves three primary surfaces: a CLI assistant, a Flask web app, and a small Electron wrapper in `ui/`.

## Core Components
- `app.py`: interactive CLI loop with commands, retrieval, and optional TTS.
- `web.py`: Flask app for authenticated chat, admin tools, memory browsing, and Vast.ai controls.
- `brain.py`: fact loading, scoped retrieval, TF-IDF indexing, and lightweight caching.
- `memory_store.py` and `goals_store.py`: long-lived semantic memory and goals persistence.
- `llm.py`: LLM backend selection across Ollama and OpenAI-compatible flows.
- `auth.py`: SQLite-backed users, tokens, bootstrap admin password flow, and role checks.
- `drayops/`: operational entry points, service registry, and deployment presets.

## Runtime Behavior
- Primary web port: `5000`.
- Authentication model: cookie-based session token (`aion_token`) with role-gated admin and Vast endpoints.
- Retrieval model: scoped facts first, then semantic memory and goals where enabled.
- Health probe: `GET /api/system/public/health`.
- Default remote inference path: Ollama.

## Data Model
- Structured facts are loaded from JSONL sources in `data/`.
- Shared and user-specific learned facts are stored separately.
- SQLite is used for auth, history, events, memory, and goals.
- Message history stores `session_id`, `thread_id`, `channel`, and message envelope metadata for replayable conversations.

## Operational Requirements
- Python 3.10+ is sufficient on the current Vast instance.
- Remote deployment must preserve `data/` and `config_local.py`.
- Gunicorn startup is currently unreliable on the active Vast container; the verified fallback is direct Flask on port `5000`.
- Ollama embedding endpoints are inconsistent across environments, so `memory_embeddings.py` now attempts multiple endpoint variants before falling back.

## Acceptance Criteria
- Local suite passes with `./.venv/bin/python -m unittest discover -p 'test_*.py'`.
- Remote suite passes with `python3 -m unittest discover -p 'test_*.py'`.
- Health endpoint returns `200` with JSON payload.
- Browser QA is considered complete when the login page loads and a credentialed sign-in succeeds under Playwright.
