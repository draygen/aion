# Aion — Project Summary
**Date:** March 4, 2026
**Author:** Brian Wallace (draygen)
**Repo:** github.com/draygen/aion

---

## What Is Aion?

Aion is a personal AI assistant built on a local LLM (Ollama / qwen2.5:7b), deployed on Vast.ai GPU cloud instances. It has a web chat interface, persistent multi-user memory, voice output, and an admin panel for managing cloud deployments — all self-hosted and private.

---

## Architecture

### Backend
| File | Purpose |
|---|---|
| `web.py` | Flask web server — all routes and API endpoints |
| `brain.py` | TF-IDF semantic memory retrieval over JSONL fact files |
| `llm.py` | LLM abstraction — Ollama (local) or OpenAI |
| `auth.py` | bcrypt login, SQLite token sessions, `@login_required` decorator |
| `extractor.py` | Background daemon thread — extracts facts from conversations |
| `vast.py` | Vast.ai API client — search GPUs, deploy, destroy, redeploy |
| `config.py` | Central config dict (non-secret defaults) |
| `config_local.py` | Secret keys and passwords — gitignored, never committed |

### Frontend
| File | Purpose |
|---|---|
| `templates/index.html` | Main chat UI — login overlay, chat, memory browser |
| `templates/admin.html` | Admin panel — Vast.ai GPU market + instance management |
| `templates/logs.html` | Chat log viewer (admin-key protected) |

### Data (gitignored — all private)
| File | Contents |
|---|---|
| `data/aion.db` | SQLite: users, tokens, per-user chat history |
| `data/shared_learned.jsonl` | Facts learned from conversations (shared across all users) |
| `data/profile.jsonl` | Curated identity facts (highest retrieval priority) |
| `data/brian_facts.jsonl` | Brian's personal facts |
| `data/jenn_messages.jsonl` | Jennifer's Facebook messages (verbatim, with metadata) |
| `data/fb_messages_parsed.jsonl` | Brian's FB messages |
| `data/fb_qa_pairs.jsonl` | Parsed Q&A pairs from Facebook conversations |

---

## Key Features

### Multi-User Auth
- Login with username/password (bcrypt hashed)
- 30-day sliding session cookie (`aion_token`, httponly)
- Roles: `admin` and `user`
- Brian's admin account auto-created on first run
- Per-user chat history stored in SQLite (last 40 turns sent to LLM)

### Shared Memory
- All users share one fact store (`shared_learned.jsonl`)
- Facts learned by Brian are visible when Gary logs in
- `remember: Gary is Brian's friend from Laconia` — instant, no LLM needed
- TF-IDF retrieval injects the 15 most relevant facts into every system prompt

### Auto Fact Extraction
- After every LLM reply, a background thread asks the LLM to extract facts
- Extracted facts are added to shared memory automatically
- Zero latency impact on the user — fire-and-forget daemon thread

### Memory Browser
- Full Facebook message browser built into the chat UI
- Categorised by: Birth & Pregnancy, Love & Relationships, Family & Parenting, Health & Wellbeing, Loss & Grief, Major Life Events
- Expandable conversation threads with chat-bubble UI

### Vast.ai Admin Panel (`/admin`)
- **GPU Market:** search available instances by max $/hr, min VRAM, GPU name
- Shows: GPU model, VRAM, system RAM, disk, network speed, reliability %, price
- One-click **Deploy** — provisions instance, runs full auto-deploy script:
  - Installs Ollama + pulls qwen2.5:7b
  - Clones repo from GitHub
  - Installs Python deps
  - Starts Aion on port 5000
- **Running Instances:** shows status, SSH info, web URL, uptime, cost
- **Redeploy Code** button — rsync local changes + restart gunicorn via SSH
- **Destroy** button — terminates instance immediately

### CLI Scripts
| Script | Purpose |
|---|---|
| `deploy.sh` | Full first-time setup on a fresh Vast.ai instance |
| `redeploy.sh` | Sync code + restart (runs dos2unix automatically) |
| `destroy.sh` | List instances and destroy by ID |
| `start_web.sh` | Run Aion locally with Cloudflare tunnel |

---

## API Endpoints

### Auth
| Method | Path | Description |
|---|---|---|
| POST | `/api/login` | Set session cookie |
| POST | `/api/logout` | Clear session cookie |
| GET | `/api/whoami` | Return `{username, role}` |
| POST | `/api/admin/users` | Create user (admin only) |
| DELETE | `/api/admin/users/<id>` | Delete user (admin only) |

### Chat
| Method | Path | Description |
|---|---|---|
| POST | `/api/chat` | Send message, get LLM response |

### Memory
| Method | Path | Description |
|---|---|---|
| GET | `/api/memory/browse` | Facebook message categories |
| GET | `/api/memory/thread/<id>` | Individual thread messages |

### Vast.ai (admin only)
| Method | Path | Description |
|---|---|---|
| GET | `/api/admin/vast/offers` | Search GPU offers |
| GET | `/api/admin/vast/instances` | List running instances |
| POST | `/api/admin/vast/deploy` | Deploy on an offer |
| DELETE | `/api/admin/vast/instances/<id>` | Destroy instance |
| POST | `/api/admin/vast/instances/<id>/redeploy` | Push code + restart |

---

## Security
- All API keys and passwords live in `config_local.py` (gitignored)
- `data/` directory is gitignored — all private family data stays local
- `.gitattributes` enforces LF line endings; `core.autocrlf=input` set globally
- ElevenLabs key previously committed to git — **rotate at elevenlabs.io**
- Admin panel protected server-side by role check before rendering

---

## Infrastructure

- **Local dev:** WSL2 on Windows (draygen@draygendesktop), `/mnt/c/aion`
- **Production:** Vast.ai GPU instance, deployed via admin panel or `./deploy.sh`
- **Public URL:** https://drayhub.org (Cloudflare tunnel)
- **LLM:** qwen2.5:7b via Ollama (local inference, no API cost)
- **Python venv:** `/mnt/c/aion/.venv`

---

## Planned / Next Up
- UI enhancements
