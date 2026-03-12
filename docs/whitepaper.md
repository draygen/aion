# Aion Whitepaper

## Overview
Aion is a practical personal-assistant stack built around one constraint: responses should be grounded in user-specific memory rather than treated as generic chatbot output. The repository pairs conventional web application pieces, including auth, persistence, and admin tooling, with retrieval-augmented LLM behavior tuned for personal context.

## Design Approach
The system intentionally uses a layered memory model. Curated facts and imported QA pairs form the most stable retrieval layer. User-learned facts extend that layer without polluting global state. Semantic memory and goals add optional higher-level continuity. This is simpler than a fully agentic memory graph, but easier to audit and reason about.

The web stack is similarly pragmatic. Flask is enough for authenticated chat, operator controls, and a memory browser. The design avoids over-abstraction: routes remain close to the business logic, and SQLite is used where the workload is bounded and local-first.

## Technical Merits
- Scoped retrieval prevents one user’s learned facts from bleeding into another user’s context.
- Chat envelopes preserve session and thread metadata, which makes cross-channel replay and auditing feasible.
- The codebase supports local Ollama inference and OpenAI-compatible APIs without forcing one vendor path.
- Deployment can be kept minimal on ephemeral GPU instances such as Vast.ai.

## Current Findings
The codebase is in materially better shape after verification:
- Local unit coverage is green at `66/66`.
- Remote unit coverage is green at `54/54`.
- Public health now has a stable JSON endpoint for automation and ops checks.
- Remote health latency on the active Vast instance averaged about `2.56 ms` over ten in-instance requests.

## Current Risks
- Gunicorn worker boot on the active Vast container is unreliable; the app was verified under a direct Flask process instead.
- Browser automation is not yet stable in this container. Playwright package install worked, Chromium downloaded, and Linux deps installed, but Chromium still crashes in this environment.
- Ollama embedding APIs differ by deployment, so semantic embedding quality depends on endpoint compatibility.

## Recommended Next Step
Treat the current state as a verified beta deployment. Stabilize the production WSGI path and container-level browser runtime before expanding UI automation or adding more operator surfaces.
