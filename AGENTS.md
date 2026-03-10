# Repository Guidelines

## Project Structure & Module Organization
This repository is primarily a flat Python application rooted at the project top level. Core runtime modules include `app.py` for the CLI flow, `web.py` for the Flask web server, `brain.py` and `llm.py` for retrieval and model access, plus supporting modules such as `auth.py`, `tools.py`, and `vast.py`. Tests live beside the code as `test_*.py`. HTML templates are in `templates/`, operational services and presets are in `drayops/`, and the Electron desktop client is isolated under `ui/`. Runtime data such as SQLite stores and JSONL memory files belong in `data/`.

## Build, Test, and Development Commands
Use the repository virtualenv rather than the system Python.

- `./.venv/bin/python app.py`: start the CLI assistant.
- `./.venv/bin/python web.py`: run the Flask web UI locally.
- `./.venv/bin/python -m unittest discover -p 'test_*.py'`: run the Python test suite.
- `./run.sh "Hello"`: send a quick prompt to a local Ollama instance.
- `cd ui && npm start`: launch the Electron client.
- `cd ui && npm run build`: build the Windows Electron package into `ui/dist/`.

## Coding Style & Naming Conventions
Follow the existing Python style: 4-space indentation, snake_case for functions and modules, PascalCase for test classes, and concise module-level constants in ALL_CAPS. Keep new Python modules at the repo root only if they are first-class runtime components; otherwise prefer existing folders such as `drayops/` or `templates/`. JavaScript in `ui/` uses CommonJS (`require`, `module.exports` style). No formatter or linter config is checked in, so match surrounding code closely and keep imports grouped and readable.

## Testing Guidelines
Add or update `test_*.py` files for behavioral changes. The suite uses `unittest` with heavy `unittest.mock` patching, even when executed through discovery. Prefer targeted unit tests near the affected module and keep test names explicit, for example `test_build_system_prompt_scopes_memory_to_username`. Current baseline: `./.venv/bin/python -m unittest discover -p 'test_*.py'` reports two existing failures in `test_brain.py` and `test_web_security.py`.

## Commit & Pull Request Guidelines
Recent history follows short Conventional Commit prefixes such as `feat:`, `perf:`, and scoped summaries. Keep commits focused and imperative, for example `fix: scope web memory retrieval to username`. PRs should state the user-visible impact, list validation steps, link related issues, and include screenshots for `templates/` or `ui/` changes. Call out config, schema, or deployment implications explicitly.
