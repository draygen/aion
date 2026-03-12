# Verification Report

## Local Results
- Unit tests: `66/66` passing via `./.venv/bin/python -m unittest discover -p 'test_*.py'`
- Fixed regressions:
  - stale TF-IDF index state in [`brain.py`](/mnt/c/aion/brain.py)
  - prompt retrieval scope expectation in [`web.py`](/mnt/c/aion/web.py)
  - Vast tests depending on a secret `vast_api_key`

## Remote Vast Instance
- Host: `74.48.140.178:40515`
- GPU: `NVIDIA GeForce RTX 5090`
- Python: `3.10.12`
- Aion checkout: `/workspace/aion`

## Remote Runtime
- Verified health endpoint: `GET /api/system/public/health`
- Current working service mode: direct Flask process on port `5000`
- Health latency profile from inside the instance:
  - average: `2.556 ms`
  - p95: `2.882 ms`
  - max: `4.455 ms`

## Remote Tests
- Unit tests: `54/54` passing via `python3 -m unittest discover -p 'test_*.py'`

## Browser QA
- Added reusable Playwright smoke files:
  - [`playwright.config.js`](/mnt/c/aion/playwright.config.js)
  - [`smoke.spec.js`](/mnt/c/aion/qa/playwright/smoke.spec.js)
- Remote Playwright status:
  - Python Playwright installed
  - Chromium downloaded
  - required Linux browser deps installed
  - final browser launch still crashes with a Chromium `SIGSEGV` in this Vast container

## Deployment Notes
- [`redeploy.sh`](/mnt/c/aion/redeploy.sh) now supports host and port overrides and preserves remote secrets by excluding `config_local.py`.
- The repo now exposes a public health endpoint suitable for ops checks and future automated deployment verification.
